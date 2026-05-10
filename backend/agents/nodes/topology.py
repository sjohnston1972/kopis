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
from services.activity import activity_bus

log = structlog.get_logger()

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "topology.md").read_text()


def _diff_has_meaningful_change(diff: dict) -> bool:
    """True if the diff contains a state change worth analysing.

    The normaliser already filters timer/counter noise into anomalies. Here
    we look at the *raw* diff to decide whether the topology agent has any
    real work to do. Any of the following counts as meaningful:
      - interface oper_status changing
      - BGP/OSPF session state changing
      - routing entries removed (path withdrawn)
      - ARP entries removed (peer went away)
    Pure additions (new ARP, new routes) are NORMAL and don't warrant a
    Haiku call on their own.
    """
    if not isinstance(diff, dict) or diff.get("note"):
        return False
    for key, change in diff.items():
        if not isinstance(change, dict):
            continue
        status = change.get("status", "")
        klow = key.lower()
        if status == "removed" and ("arp" in klow or "routing" in klow or "neighbor" in klow):
            return True
        if status == "changed":
            if "oper_status" in klow and change.get("new") == "down":
                return True
            if "session_state" in klow and change.get("old") == "Established" and change.get("new") != "Established":
                return True
            if "enabled" in klow and change.get("new") is False:
                return True
    return False


async def topology_node(state: KopisState) -> dict:
    """LangGraph node: classify findings from normalised data via Haiku.

    Token-saving short-circuit: if the normaliser flagged zero anomalies AND
    the diff contains nothing meaningful (or doesn't exist), the device is
    healthy and unchanged — skip the Haiku call entirely. The agent's prompt
    already says "return [] for healthy devices" so this just saves the round
    trip for the most common case.
    """
    hostname = state.get("device_hostname", "unknown")
    log.info("topology_start", hostname=hostname)
    act_id = activity_bus.start(
        pipeline_run=state.get("snapshot_id", ""),
        node="topology",
        model=settings.haiku_model,
        device=hostname,
        detail=f"Haiku classifying findings for {hostname}",
    )

    normalised = state.get("normalised_data", {})
    interfaces = state.get("interface_summary", [])
    routing = state.get("routing_summary", [])
    anomalies = state.get("anomalies_detected", [])

    # Include diff summary if available
    diff = state.get("snapshot_diff", {})

    # Short-circuit: healthy device + unchanged state = no Haiku call needed.
    # The deterministic normaliser flags non-Established BGP/OSPF, down
    # interfaces, high error counters, removed routes, etc. If it found
    # nothing AND the diff has nothing meaningful, there's nothing for
    # Haiku to analyse. Trust the extractor — it covers the cases that
    # would have been actionable findings anyway.
    if not anomalies and not _diff_has_meaningful_change(diff):
        activity_bus.complete(
            act_id,
            tokens=0,
            detail=f"Skipped Haiku for {hostname} — no anomalies, no meaningful diff",
        )
        log.info(
            "topology_skipped_no_change",
            hostname=hostname,
            anomaly_count=len(anomalies),
        )
        return {
            "findings": [],
            "escalate_to_opus": False,
            "processing_stage": "complete",
            "tokens_used": state.get("tokens_used", {}),
        }

    diff_section = ""
    if diff and not diff.get("note"):
        # Summarise the diff — focus on key changes, not raw data
        diff_str = json.dumps(diff, default=str, indent=2)
        if len(diff_str) > 15_000:
            diff_str = diff_str[:15_000] + "\n... [TRUNCATED]"
        diff_section = (
            f"## Changes Since Last Snapshot (DIFF)\n"
            f"These are the specific changes detected between the previous and current snapshot. "
            f"Pay close attention — removed ARP entries, routing changes, and BGP state transitions "
            f"indicate real network events.\n```json\n{diff_str}\n```\n\n"
        )

    prompt = (
        f"Device: {hostname} (platform: {state.get('device_platform', 'unknown')})\n\n"
        f"## Normalised Data\n```json\n{json.dumps(normalised, default=str, indent=2)}\n```\n\n"
        f"## Interface Summary\n```json\n{json.dumps(interfaces, default=str, indent=2)}\n```\n\n"
        f"## Routing Summary\n```json\n{json.dumps(routing, default=str, indent=2)}\n```\n\n"
        f"## Anomalies Detected by Normaliser\n```json\n{json.dumps(anomalies, default=str, indent=2)}\n```\n\n"
        f"{diff_section}"
        "Analyse this device and produce your findings as specified."
    )

    try:
        result = await anthropic_client.message(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=settings.haiku_model,
            max_tokens=8192,
            temperature=0.15,
        )
    except Exception as e:
        log.error("topology_failed", hostname=hostname, error=str(e))
        activity_bus.fail(act_id, f"Haiku analysis failed for {hostname}: {e}")
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

    severity_counts = {}
    for f in findings:
        s = f.get("severity", "unknown")
        severity_counts[s] = severity_counts.get(s, 0) + 1
    sev_str = ", ".join(f"{c} {s}" for s, c in severity_counts.items()) if severity_counts else "none"
    esc_str = " → escalating to Opus" if escalate else ""
    activity_bus.complete(act_id, tokens=tokens, detail=f"Haiku found {len(findings)} issues on {hostname} ({sev_str}){esc_str}")
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
