"""Normaliser node — deterministic data reduction.

Tier 0 of the pipeline. Takes raw pyATS snapshot JSON and extracts a
compact structured summary: interface states, routing neighbours, error
counters, version info, and quick anomaly flags.

This used to call Ollama (qwen2.5) but Ollama on the homelab proved too
unreliable: 30s timeouts × 18 devices = ~9 min wasted per snapshot, and
the model often returned malformed JSON anyway. The deterministic
extractor below catches everything that mattered, runs in milliseconds,
and never fails. Haiku (Tier 1) does the actual anomaly analysis — the
normaliser just feeds it tidy data.

The Ollama integration is preserved (`integrations/ollama.py`) for future
use — e.g. if a small focused prompt becomes worthwhile, or for chat.
"""

import structlog

from agents.state import KopisState
from services.activity import activity_bus

log = structlog.get_logger()


def _fallback_normalise(raw: dict, hostname: str, platform: str, diff: dict | None = None) -> dict:
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

    # Diff-based change detection — only flag genuinely concerning changes
    if diff and isinstance(diff, dict):
        for key, change in diff.items():
            if not isinstance(change, dict):
                continue
            status = change.get("status", "")

            # ARP entries REMOVED — neighbour went away
            if "arp" in key and status == "removed":
                entity = key.split(".")
                intf_name = entity[2] if len(entity) > 2 else "unknown"
                detail = f"ARP entry removed: {key}"
                if isinstance(change.get("value"), dict):
                    neighbors = change["value"].get("neighbors", {})
                    if neighbors:
                        ips = list(neighbors.keys())
                        detail = f"ARP neighbours lost on {intf_name}: {', '.join(ips)}"
                anomalies.append({
                    "type": "state_change",
                    "entity": intf_name,
                    "detail": detail,
                })

            # Routing entries REMOVED — path withdrawal (not added — that's good)
            elif "routing" in key and status == "removed":
                anomalies.append({
                    "type": "state_change",
                    "entity": key.split(".")[-1] if "." in key else key,
                    "detail": f"Route withdrawn: {key}",
                })

            # BGP session state changing AWAY from Established
            elif "bgp" in key and "session_state" in key and status == "changed":
                new_state = change.get("new", "")
                old_state = change.get("old", "")
                if old_state == "Established" and new_state != "Established":
                    anomalies.append({
                        "type": "state_change",
                        "entity": key,
                        "detail": f"BGP session dropped from {old_state} to {new_state}",
                    })
            elif "bgp" in key and "neighbor" in key and status == "removed":
                anomalies.append({
                    "type": "state_change",
                    "entity": key,
                    "detail": f"BGP neighbour data removed: {key}",
                })

            # Interface going DOWN (not up — that's recovery)
            elif "interface" in key and "oper_status" in key and status == "changed":
                if change.get("new") == "down" and change.get("old") == "up":
                    anomalies.append({
                        "type": "state_change",
                        "entity": key,
                        "detail": f"Interface went down (was {change.get('old')})",
                    })

            # Interface admin-disabled (someone ran 'shutdown') — this is
            # the cascade-causing change, not background noise.
            elif "interface" in key and key.endswith(".enabled") and status == "changed":
                if change.get("old") is True and change.get("new") is False:
                    intf_name = key.split(".")[1] if "." in key else key
                    anomalies.append({
                        "type": "state_change",
                        "entity": intf_name,
                        "detail": f"Interface {intf_name} was shut down (admin-disabled) — was previously enabled",
                    })

    return {
        "interface_summary": interface_summary,
        "routing_summary": routing_summary,
        "platform": platform_info,
        "anomalies_detected": anomalies,
    }


async def normaliser_node(state: KopisState) -> dict:
    """LangGraph node: deterministic data reduction.

    Runs in milliseconds — no LLM call. Output feeds into the Haiku
    topology agent which does the actual anomaly analysis.
    """
    hostname = state.get("device_hostname", "unknown")
    raw = state.get("raw_snapshot", {})
    platform = state.get("device_platform", "unknown")

    act_id = activity_bus.start(
        pipeline_run=state.get("snapshot_id", ""),
        node="normaliser",
        model="deterministic",
        device=hostname,
        detail=f"Extracting key facts from {hostname} snapshot",
    )

    result = _fallback_normalise(raw, hostname, platform, state.get("snapshot_diff"))
    anomaly_count = len(result.get("anomalies_detected", []))

    activity_bus.complete(act_id, detail=f"Normalised {hostname}: {anomaly_count} anomalies flagged")
    log.info(
        "normaliser_complete",
        hostname=hostname,
        interfaces=len(result.get("interface_summary", [])),
        anomalies=anomaly_count,
    )

    return {
        "normalised_data": result,
        "interface_summary": result.get("interface_summary", []),
        "routing_summary": result.get("routing_summary", []),
        "anomalies_detected": result.get("anomalies_detected", []),
        "processing_stage": "topology",
        "tokens_used": state.get("tokens_used", {}),
    }
