"""Escalation remediation node — Opus-powered command generation.

Tier 3 (Opus, expensive). Invoked only when the topology agent flags
specific findings as needing Opus-level remediation reasoning — complex
multi-step fixes, cascading risks, or non-trivial rollback scenarios.

Handles both escalated and standard findings in one pass: Opus generates
recommendations for the escalated findings, Sonnet-tier findings are
passed through to the regular remediation node.
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

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "remediation.md").read_text()

# Extra context for Opus about why it was called
OPUS_PREAMBLE = (
    "You have been invoked because the topology agent determined these findings "
    "require deeper reasoning for safe remediation. Pay special attention to "
    "command sequencing, cascading effects on other devices, and rollback safety.\n\n"
)


async def escalation_remediation_node(state: KopisState) -> dict:
    """LangGraph node: split findings by escalation tier, run Opus on escalated ones."""
    hostname = state.get("device_hostname", "unknown")
    findings = state.get("findings", [])

    escalated = [f for f in findings if f.get("requires_remediation") and f.get("escalate_remediation")]
    standard = [f for f in findings if f.get("requires_remediation") and not f.get("escalate_remediation")]

    if not escalated:
        # Nothing actually needs Opus — shouldn't happen but handle gracefully
        log.info("escalation_remediation_skip", hostname=hostname, reason="no escalated findings")
        return {"processing_stage": "remediation" if standard else "complete"}

    log.info("escalation_remediation_start", hostname=hostname, escalated=len(escalated), standard=len(standard))
    act_id = activity_bus.start(
        pipeline_run=state.get("snapshot_id", ""),
        node="escalation_remediation",
        model=settings.opus_model,
        device=hostname,
        detail=f"Opus generating complex remediation for {len(escalated)} escalated findings on {hostname}",
    )

    prompt = (
        OPUS_PREAMBLE
        + f"Device: {hostname} (platform: {state.get('device_platform', 'unknown')})\n\n"
        + f"## Findings Requiring Remediation\n```json\n{json.dumps(escalated, default=str, indent=2)}\n```\n\n"
        + "Generate remediation recommendations for each finding as specified."
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
        log.error("escalation_remediation_failed", hostname=hostname, error=str(e))
        activity_bus.fail(act_id, f"Opus remediation failed for {hostname}: {e}")
        return {
            "processing_stage": "remediation" if (escalated or standard) else "complete",
            "errors": state.get("errors", []) + [f"Escalation remediation failed: {e}"],
        }

    tokens = result.pop("_tokens", 0)
    model = result.pop("_model", settings.opus_model)
    token_tracking = state.get("tokens_used", {})
    token_tracking[model] = token_tracking.get(model, 0) + tokens

    # Never store recommendations from a truncated or unparseable response
    # (see #18/#19). Standard-tier findings still route onward so the
    # Sonnet remediation node gets a chance at them.
    unusable_reason = llm_result_unusable(result, node="escalation_remediation", hostname=hostname)
    if unusable_reason:
        activity_bus.fail(act_id, f"Opus complex remediation for {hostname}: {unusable_reason}")
        return {
            "recommendations": [],
            "processing_stage": "remediation" if standard else "complete",
            "tokens_used": token_tracking,
            "errors": state.get("errors", []) + [
                f"Escalation remediation agent: {unusable_reason} for {hostname} — no recommendations produced"
            ],
        }

    recommendations = result.get("recommendations", [])
    for r in recommendations:
        r["model_used"] = model

    activity_bus.complete(act_id, tokens=tokens, detail=f"Opus produced {len(recommendations)} complex remediation plans for {hostname}")
    log.info(
        "escalation_remediation_complete",
        hostname=hostname,
        recommendations=len(recommendations),
        remaining_standard=len(standard),
    )

    # If there are still standard findings, route to Sonnet remediation node
    # which will pick up the remaining ones. The recommendations from Opus
    # are added to state and the remediation node appends to them.
    if standard:
        return {
            "recommendations": recommendations,
            "processing_stage": "remediation",
            "tokens_used": token_tracking,
        }

    return {
        "recommendations": recommendations,
        "processing_stage": "complete",
        "tokens_used": token_tracking,
    }
