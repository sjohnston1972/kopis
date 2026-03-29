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


def _fallback_normalise(raw: dict, hostname: str, platform: str) -> dict:
    """Extract key data directly from pyATS snapshot when Ollama is unavailable."""
    interface_summary = []
    anomalies = []
    routing_summary = []

    # Interfaces
    interfaces = raw.get("interface", {})
    if isinstance(interfaces, dict):
        for name, idata in interfaces.items():
            if not isinstance(idata, dict):
                continue
            oper = idata.get("oper_status", "unknown")
            admin = idata.get("enabled", True)
            ip_addr = None
            ipv4 = idata.get("ipv4", {})
            if isinstance(ipv4, dict):
                for addr, info in ipv4.items():
                    if isinstance(info, dict):
                        prefix = info.get("prefix_length", "")
                        ip_addr = f"{addr}/{prefix}" if prefix else addr
                        break

            in_errors = idata.get("counters", {}).get("in_errors", 0) if isinstance(idata.get("counters"), dict) else 0
            out_errors = idata.get("counters", {}).get("out_errors", 0) if isinstance(idata.get("counters"), dict) else 0
            in_crc = idata.get("counters", {}).get("in_crc_errors", 0) if isinstance(idata.get("counters"), dict) else 0

            status = "up" if oper == "up" else ("admin-down" if not admin else "down")
            interface_summary.append({
                "name": name,
                "status": status,
                "ip_address": ip_addr,
                "speed": idata.get("bandwidth", None),
                "in_errors": in_errors,
                "out_errors": out_errors,
                "in_crc": in_crc,
                "description": idata.get("description"),
            })

            if status == "down" and admin:
                anomalies.append({
                    "type": "interface_down",
                    "entity": name,
                    "detail": f"Interface {name} is operationally down but admin-up",
                })
            if in_errors > 100 or out_errors > 100:
                anomalies.append({
                    "type": "high_errors",
                    "entity": name,
                    "detail": f"Interface {name} has {in_errors} in_errors, {out_errors} out_errors",
                })

    # BGP
    bgp = raw.get("bgp", {})
    if isinstance(bgp, dict):
        bgp_neighbors = []
        for instance in bgp.get("instance", {}).values():
            if not isinstance(instance, dict):
                continue
            for vrf in instance.get("vrf", {}).values():
                if not isinstance(vrf, dict):
                    continue
                for neighbor_addr, ndata in vrf.get("neighbor", {}).items():
                    if not isinstance(ndata, dict):
                        continue
                    session_state = ndata.get("session_state", "unknown")
                    bgp_neighbors.append({"id": neighbor_addr, "state": session_state})
                    if session_state != "Established":
                        anomalies.append({
                            "type": "missing_neighbour",
                            "entity": f"BGP neighbor {neighbor_addr}",
                            "detail": f"BGP neighbor {neighbor_addr} is in state {session_state} (not Established)",
                        })
        if bgp_neighbors:
            routing_summary.append({
                "protocol": "bgp",
                "neighbours": bgp_neighbors,
                "route_count": 0,
                "areas": [],
            })

    # OSPF
    ospf = raw.get("ospf", {})
    if isinstance(ospf, dict):
        ospf_neighbors = []
        areas = set()
        for instance in ospf.get("vrf", {}).values():
            if not isinstance(instance, dict):
                continue
            for area_id, area_data in instance.get("areas", {}).items():
                if not isinstance(area_data, dict):
                    continue
                areas.add(area_id)
                for iface_data in area_data.get("interfaces", {}).values():
                    if not isinstance(iface_data, dict):
                        continue
                    for nbr_id, nbr_data in iface_data.get("neighbors", {}).items():
                        if isinstance(nbr_data, dict):
                            state = nbr_data.get("state", "unknown")
                            ospf_neighbors.append({"id": nbr_id, "state": state})
        if ospf_neighbors:
            routing_summary.append({
                "protocol": "ospf",
                "neighbours": ospf_neighbors,
                "route_count": 0,
                "areas": list(areas),
            })

    # Platform
    plat = raw.get("platform", {})
    platform_info = {}
    if isinstance(plat, dict):
        platform_info = {
            "hostname": hostname,
            "os": platform,
            "version": plat.get("version") or plat.get("os", ""),
            "uptime": str(plat.get("uptime", "")),
            "serial": plat.get("chassis_sn") or plat.get("serial", None),
        }

    return {
        "interface_summary": interface_summary,
        "routing_summary": routing_summary,
        "platform": platform_info,
        "anomalies_detected": anomalies,
    }


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
        log.warning("normaliser_ollama_failed_using_fallback", hostname=hostname, error=str(e))
        fallback = _fallback_normalise(raw, hostname, state.get("device_platform", "unknown"))
        return {
            "normalised_data": fallback,
            "interface_summary": fallback.get("interface_summary", []),
            "routing_summary": fallback.get("routing_summary", []),
            "anomalies_detected": fallback.get("anomalies_detected", []),
            "processing_stage": "topology",
            "errors": state.get("errors", []) + [f"Normaliser failed: {e} (used fallback)"],
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
