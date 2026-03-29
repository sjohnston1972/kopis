"""Normaliser node — Ollama-powered data reduction.

Tier 0 (local, free). Takes raw pyATS snapshot JSON and extracts a
compact structured summary: interface states, routing neighbours,
error counters, version info, and quick anomaly flags.

This is a DATA REDUCTION step — fast and cheap. Analysis happens later.
"""

import json
import uuid

import structlog

from agents.state import KopisState
from integrations.ollama import ollama_client

log = structlog.get_logger()

SYSTEM_PROMPT = """\
You are a network data normaliser. You receive raw pyATS learned data from a
network device and produce a compact JSON summary.

Your job is DATA REDUCTION, not analysis. Be fast and factual.

Output MUST be valid JSON with exactly these top-level keys:
{
  "interface_summary": [
    {
      "name": "GigabitEthernet0/1",
      "status": "up|down|admin-down",
      "ip_address": "x.x.x.x/mask or null",
      "speed": "1Gbps",
      "in_errors": 0,
      "out_errors": 0,
      "in_crc": 0,
      "description": "string or null"
    }
  ],
  "routing_summary": [
    {
      "protocol": "ospf|bgp|static|connected",
      "neighbours": [{"id": "x.x.x.x", "state": "FULL|ESTABLISHED|etc"}],
      "route_count": 0,
      "areas": ["0.0.0.0"]
    }
  ],
  "platform": {
    "hostname": "string",
    "os": "string",
    "version": "string",
    "uptime": "string",
    "serial": "string or null"
  },
  "anomalies_detected": [
    {
      "type": "interface_down|high_errors|missing_neighbour|version_mismatch|other",
      "entity": "affected interface or protocol",
      "detail": "brief description"
    }
  ]
}

Rules:
- Only include interfaces that are configured (skip unassigned/unused).
- Flag interfaces with >100 errors as anomalies.
- Flag routing neighbours not in FULL/ESTABLISHED state.
- Flag interfaces that are operationally down but admin-up.
- Keep output compact. Do not include raw counters beyond what is specified.
"""


async def normaliser_node(state: KopisState) -> dict:
    """LangGraph node: normalise raw snapshot data via Ollama."""
    hostname = state.get("device_hostname", "unknown")
    raw = state.get("raw_snapshot", {})

    log.info("normaliser_start", hostname=hostname)

    # Truncate large snapshots to fit context window
    raw_str = json.dumps(raw, default=str)
    if len(raw_str) > 60_000:
        raw_str = raw_str[:60_000] + "\n... [TRUNCATED]"

    prompt = f"Device hostname: {hostname}\nPlatform: {state.get('device_platform', 'unknown')}\n\nRaw pyATS data:\n{raw_str}"

    try:
        result = await ollama_client.generate(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            temperature=0.05,
        )
    except Exception as e:
        log.error("normaliser_failed", hostname=hostname, error=str(e))
        return {
            "normalised_data": {},
            "interface_summary": [],
            "routing_summary": [],
            "anomalies_detected": [],
            "processing_stage": "normalise",
            "errors": state.get("errors", []) + [f"Normaliser failed: {e}"],
            "tokens_used": state.get("tokens_used", {}),
        }

    tokens = result.pop("_tokens", 0)
    token_tracking = state.get("tokens_used", {})
    token_tracking["ollama"] = token_tracking.get("ollama", 0) + tokens

    if result.get("_parse_error"):
        log.warning("normaliser_parse_error", hostname=hostname)
        return {
            "normalised_data": {},
            "interface_summary": [],
            "routing_summary": [],
            "anomalies_detected": [],
            "processing_stage": "normalise",
            "errors": state.get("errors", []) + ["Normaliser returned invalid JSON"],
            "tokens_used": token_tracking,
        }

    log.info(
        "normaliser_complete",
        hostname=hostname,
        interfaces=len(result.get("interface_summary", [])),
        anomalies=len(result.get("anomalies_detected", [])),
    )

    return {
        "normalised_data": result,
        "interface_summary": result.get("interface_summary", []),
        "routing_summary": result.get("routing_summary", []),
        "anomalies_detected": result.get("anomalies_detected", []),
        "processing_stage": "topology",
        "tokens_used": token_tracking,
    }
