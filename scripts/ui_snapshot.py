"""Capture the UI-driving state in one shot for visual-indicator testing.

Run from inside the kopis-backend container:
  python /app/ui_snapshot.py <label>

Reports every value that drives a visible dashboard / insights tile so
we can verify "do indicators reflect issues" and "do they return to
normal after service restored".
"""

import asyncio
import json
import sys

import httpx

API = "http://localhost:8000/api/v1"


async def fetch():
    async with httpx.AsyncClient(timeout=30) as c:
        metrics = (await c.get(f"{API}/dashboard/metrics")).json()
        incidents = (await c.get(f"{API}/findings/incidents/list")).json()
        findings = (await c.get(f"{API}/findings?limit=200")).json()
        approvals = (await c.get(f"{API}/approvals")).json()
        deps = (await c.get(f"{API}/health/dependencies")).json()
    return metrics, incidents, findings, approvals, deps


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    metrics, incidents, findings, approvals, deps = asyncio.run(fetch())

    intf = metrics.get("interfaces", {})
    bgp = metrics.get("bgp", {})
    routing = metrics.get("routing", {})
    findings_by_sev = metrics.get("findings", {})
    devices = metrics.get("devices", {})

    total_findings = sum(findings_by_sev.values())
    crit_high = (findings_by_sev.get("critical", 0) +
                 findings_by_sev.get("high", 0))

    deps_map = deps.get("dependencies", {})
    deps_up = sum(1 for d in deps_map.values()
                  if d.get("status") in ("ok", "healthy"))
    deps_total = len(deps_map)

    # Visual indicator rules from Dashboard.jsx + Insights.jsx
    network_health_tile = (
        "100% / Anomaly Free (GREEN)" if total_findings == 0
        else f"{total_findings} / Issues Detected ({'RED' if crit_high > 0 else 'AMBER'})"
    )
    intf_state = "GREEN" if intf.get("down", 0) == 0 else "RED"
    bgp_state = "GREEN" if bgp.get("down", 0) == 0 else "RED"

    print(f"================ {label} ================")
    print()
    print("=== HERO TILE: Network Health ===")
    print(f"  Active findings:    {total_findings}")
    print(f"  Severity counts:    {findings_by_sev}")
    print(f"  Visual:             {network_health_tile}")
    print()
    print("=== METRIC TILES ===")
    print(f"  Devices:            {devices.get('with_snapshots', 0)}/{devices.get('total', 0)} with snapshots")
    print(f"  Interfaces:         {intf.get('up', 0)}/{intf.get('total', 0)} up  [Visual: {intf_state}]")
    print(f"  BGP sessions:       {bgp.get('established', 0)}/{bgp.get('total', 0)} established  [Visual: {bgp_state}]")
    print(f"  Routes:             {routing.get('routes', 0)}")
    print(f"  ARP entries:        {routing.get('arp_entries', 0)}")
    print(f"  VLANs:              {routing.get('vlans', 0)}")
    print(f"  Services up:        {deps_up}/{deps_total}")
    print()
    print("=== INCIDENTS PANEL ===")
    print(f"  Active incidents:   {len(incidents)}")
    for i in incidents:
        corr = "CORRELATED" if i.get("is_correlated") else "solo"
        print(f"    [{i.get('max_severity','?'):8}] {corr:11} {i['finding_count']} findings on {i['affected_device_count']} devices")
        print(f"              root: {i['root_cause']['title'][:80]}")
        print(f"              devices: {i['affected_devices']}")
    print()
    print("=== APPROVALS PANEL ===")
    print(f"  Pending approvals:  {len(approvals)}")
    for a in approvals:
        f = a.get('finding') or {}
        dev = a.get('device') or {}
        print(f"    [{f.get('severity','?'):8}] {dev.get('hostname','?').split('.')[0]:12} JIRA={a.get('jira_key','none')}: {f.get('title','?')[:60]}")
    print()
    print("=== FINDINGS LIST ===")
    print(f"  Active findings (visible to operator): {len(findings)}")
    print()


if __name__ == "__main__":
    main()
