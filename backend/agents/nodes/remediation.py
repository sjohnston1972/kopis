"""Remediation agent node — Sonnet-powered command generation.

Tier 2 (Sonnet, deeper reasoning). Receives findings that require
remediation and generates specific CLI commands, risk assessments,
and rollback plans.
"""

import json
from pathlib import Path

import structlog

from agents.state import KopisState
from config import settings
from integrations.anthropic import anthropic_client

log = structlog.get_logger()

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "remediation.md").read_text()


async def remediation_node(state: KopisState) -> dict:
    """LangGraph node: generate remediation recommendations via Sonnet."""
    hostname = state.get("device_hostname", "unknown")
    findings = state.get("findings", [])
    actionable = [f for f in findings if f.get("requires_remediation")]

    if not actionable:
        log.info("remediation_skip", hostname=hostname, reason="no actionable findings")
        return {"recommendations": [], "processing_stage": "complete"}

    log.info("remediation_start", hostname=hostname, findings=len(actionable))

    prompt = (
        f"Device: {hostname} (platform: {state.get('device_platform', 'unknown')})\n\n"
        f"## Findings Requiring Remediation\n```json\n{json.dumps(actionable, default=str, indent=2)}\n```\n\n"
        "Generate remediation recommendations for each finding as specified."
    )

    try:
        result = await anthropic_client.message(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=settings.sonnet_model,
            max_tokens=8192,
            temperature=0.2,
        )
    except Exception as e:
        log.error("remediation_failed", hostname=hostname, error=str(e))
        return {
            "recommendations": [],
            "processing_stage": "complete",
            "errors": state.get("errors", []) + [f"Remediation agent failed: {e}"],
        }

    tokens = result.pop("_tokens", 0)
    model = result.pop("_model", settings.sonnet_model)
    token_tracking = state.get("tokens_used", {})
    token_tracking[model] = token_tracking.get(model, 0) + tokens

    recommendations = result.get("recommendations", [])
    for r in recommendations:
        r["model_used"] = model

    log.info(
        "remediation_complete",
        hostname=hostname,
        recommendations=len(recommendations),
    )

    return {
        "recommendations": recommendations,
        "processing_stage": "complete",
        "tokens_used": token_tracking,
    }
