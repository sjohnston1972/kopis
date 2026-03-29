"""Topology agent node — Haiku-powered finding classification.

Tier 1 (Haiku, fast + cheap). Analyses normalised device data and
produces classified findings with severity, confidence, and evidence.
"""

import json
from pathlib import Path

import structlog

from agents.state import KopisState
from config import settings
from integrations.anthropic import anthropic_client

log = structlog.get_logger()

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "topology.md").read_text()


async def topology_node(state: KopisState) -> dict:
    """LangGraph node: classify findings from normalised data via Haiku."""
    hostname = state.get("device_hostname", "unknown")
    log.info("topology_start", hostname=hostname)

    normalised = state.get("normalised_data", {})
    interfaces = state.get("interface_summary", [])
    routing = state.get("routing_summary", [])
    anomalies = state.get("anomalies_detected", [])

    prompt = (
        f"Device: {hostname} (platform: {state.get('device_platform', 'unknown')})\n\n"
        f"## Normalised Data\n```json\n{json.dumps(normalised, default=str, indent=2)}\n```\n\n"
        f"## Interface Summary\n```json\n{json.dumps(interfaces, default=str, indent=2)}\n```\n\n"
        f"## Routing Summary\n```json\n{json.dumps(routing, default=str, indent=2)}\n```\n\n"
        f"## Anomalies Detected by Normaliser\n```json\n{json.dumps(anomalies, default=str, indent=2)}\n```\n\n"
        "Analyse this device and produce your findings as specified."
    )

    try:
        result = await anthropic_client.message(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=settings.haiku_model,
            temperature=0.15,
        )
    except Exception as e:
        log.error("topology_failed", hostname=hostname, error=str(e))
        return {
            "findings": [],
            "escalate_to_opus": False,
            "processing_stage": "complete",
            "errors": state.get("errors", []) + [f"Topology agent failed: {e}"],
        }

    tokens = result.pop("_tokens", 0)
    model = result.pop("_model", settings.haiku_model)
    token_tracking = state.get("tokens_used", {})
    token_tracking[model] = token_tracking.get(model, 0) + tokens

    findings = result.get("findings", [])
    escalate = result.get("escalate_to_opus", False)

    # Tag each finding with the model that produced it
    for f in findings:
        f["_model"] = model

    needs_remediation = any(f.get("requires_remediation") for f in findings)

    # Determine next stage
    if escalate:
        next_stage = "escalation"
    elif needs_remediation:
        next_stage = "remediation"
    else:
        next_stage = "complete"

    log.info(
        "topology_complete",
        hostname=hostname,
        findings=len(findings),
        escalate=escalate,
        next_stage=next_stage,
    )

    return {
        "findings": findings,
        "escalate_to_opus": escalate,
        "processing_stage": next_stage,
        "tokens_used": token_tracking,
    }
