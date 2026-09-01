"""Escalation node — Opus-powered deep analysis.

Tier 3 (Opus, expensive — use sparingly). Invoked only when the
topology agent flags low confidence on critical findings. Can
override classifications and generate remediation directly.
"""

import json
from pathlib import Path

import structlog

from agents.nodes._llm_guard import llm_result_unusable
from agents.state import KopisState
from config import settings
from integrations.anthropic import anthropic_client
from services.activity import activity_bus

log = structlog.get_logger()

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "escalation.md").read_text()


async def escalation_node(state: KopisState) -> dict:
    """LangGraph node: deep re-analysis via Opus."""
    hostname = state.get("device_hostname", "unknown")
    log.info("escalation_start", hostname=hostname)
    act_id = activity_bus.start(
        pipeline_run=state.get("snapshot_id", ""),
        node="escalation",
        model=settings.opus_model,
        device=hostname,
        detail=f"Opus deep re-analysis — Haiku was not confident on {hostname}",
    )

    prompt = (
        f"Device: {hostname} (platform: {state.get('device_platform', 'unknown')})\n\n"
        f"## Normalised Data\n```json\n{json.dumps(state.get('normalised_data', {}), default=str, indent=2)}\n```\n\n"
        f"## Topology Agent Findings\n```json\n{json.dumps(state.get('findings', []), default=str, indent=2)}\n```\n\n"
        f"## Anomalies Detected\n```json\n{json.dumps(state.get('anomalies_detected', []), default=str, indent=2)}\n```\n\n"
        "The topology agent escalated this to you because it was not confident.\n"
        "Re-analyse the findings, correct any misclassifications, and provide "
        "remediation recommendations where appropriate."
    )

    try:
        result = await anthropic_client.message(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=settings.opus_model,
            max_tokens=8192,
            temperature=0.2,
        )
    except Exception as e:
        log.error("escalation_failed", hostname=hostname, error=str(e))
        activity_bus.fail(act_id, f"Opus escalation failed for {hostname}: {e}")
        return {
            "processing_stage": "complete",
            "errors": state.get("errors", []) + [f"Escalation failed: {e}"],
        }

    tokens = result.pop("_tokens", 0)
    model = result.pop("_model", settings.opus_model)
    token_tracking = state.get("tokens_used", {})
    token_tracking[model] = token_tracking.get(model, 0) + tokens

    # Never accept updated findings/recommendations from a truncated or
    # unparseable response — fall back to the pre-escalation findings and
    # produce zero recommendations rather than guess (see #18/#19).
    unusable_reason = llm_result_unusable(result, node="escalation", hostname=hostname)
    if unusable_reason:
        activity_bus.fail(act_id, f"Opus escalation for {hostname}: {unusable_reason}")
        return {
            "findings": state.get("findings", []),
            "recommendations": [],
            "escalate_to_opus": False,
            "processing_stage": "complete",
            "tokens_used": token_tracking,
            "errors": state.get("errors", []) + [
                f"Escalation agent: {unusable_reason} for {hostname} — no updated findings/recommendations produced"
            ],
        }

    # Opus may return updated findings and/or direct recommendations
    updated_findings = result.get("findings", state.get("findings", []))
    recommendations = result.get("recommendations", [])

    for f in updated_findings:
        f["_model"] = model
    for r in recommendations:
        r["model_used"] = model

    # If Opus provided recommendations, go straight to complete.
    # Otherwise route to remediation node for the updated findings.
    has_recommendations = len(recommendations) > 0
    needs_remediation = any(f.get("requires_remediation") for f in updated_findings)

    if has_recommendations or not needs_remediation:
        next_stage = "complete"
    else:
        next_stage = "remediation"

    activity_bus.complete(act_id, tokens=tokens, detail=f"Opus re-analysed {hostname}: {len(updated_findings)} findings, {len(recommendations)} direct recommendations")
    log.info(
        "escalation_complete",
        hostname=hostname,
        findings=len(updated_findings),
        recommendations=len(recommendations),
        next_stage=next_stage,
    )

    return {
        "findings": updated_findings,
        "recommendations": recommendations,
        "escalate_to_opus": False,
        "processing_stage": next_stage,
        "tokens_used": token_tracking,
    }
