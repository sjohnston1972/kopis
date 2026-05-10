"""Test helpers for the kopis test plan.

Run via:
  docker exec kopis-backend python /app/scripts/test_helpers.py <action> [args]

Actions:
  ssh-cmd <host_ip> "<commands separated by ;>"  - Send config commands to a device
  ssh-show <host_ip> "<show command>"            - Run a show command and print output
  trigger-snapshot                                - Trigger snapshot of all devices via API
  wait-snapshot                                   - Block until snapshot finishes
  summary                                         - Print findings + approvals summary
"""

import asyncio
import json
import os
import sys
import time

import httpx
import paramiko

API = "http://localhost:8000/api/v1"
USER = "steven"
PASS = "Extr748a"


def _ssh(ip: str) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip, port=22, username=USER, password=PASS, timeout=15,
              allow_agent=False, look_for_keys=False)
    return c


def _shell_send(ip: str, lines: list[str]) -> str:
    """Open interactive shell, send config commands, capture full transcript."""
    c = _ssh(ip)
    chan = c.invoke_shell()
    chan.settimeout(10)
    out = []
    time.sleep(1.0)
    if chan.recv_ready():
        out.append(chan.recv(65535).decode(errors="ignore"))
    # Disable paging
    chan.send("terminal length 0\n")
    time.sleep(0.4)
    while chan.recv_ready():
        out.append(chan.recv(65535).decode(errors="ignore"))

    for line in lines:
        chan.send(line + "\n")
        time.sleep(0.6)
        # Drain
        end = time.time() + 3
        while time.time() < end:
            if chan.recv_ready():
                out.append(chan.recv(65535).decode(errors="ignore"))
                end = time.time() + 0.6
            else:
                time.sleep(0.1)
    chan.close()
    c.close()
    return "".join(out)


def cmd_ssh_cmd():
    ip = sys.argv[2]
    cmd_str = sys.argv[3]
    lines = [s.strip() for s in cmd_str.split(";") if s.strip()]
    print(_shell_send(ip, lines))


def cmd_ssh_show():
    ip = sys.argv[2]
    show = sys.argv[3]
    out = _shell_send(ip, [show])
    print(out)


async def _api_get(path: str):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API}{path}")
        r.raise_for_status()
        return r.json()


async def _api_post(path: str, body=None):
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{API}{path}", json=body or {})
        r.raise_for_status()
        return r.json()


async def trigger_snapshot():
    await _api_post("/snapshots", {})
    print("Snapshot triggered")


async def wait_snapshot(timeout: int = 1200):
    end = time.time() + timeout
    last_status = None
    while time.time() < end:
        s = await _api_get("/snapshots/status")
        status_summary = (s.get("running"), s.get("devices_done"), s.get("current_device"))
        if status_summary != last_status:
            last_status = status_summary
            print(json.dumps(s))
        if not s.get("running"):
            return s
        await asyncio.sleep(5)
    raise TimeoutError("snapshot did not finish")


async def summary():
    findings = await _api_get("/findings?limit=200")
    approvals = await _api_get("/approvals")
    devices = await _api_get("/devices")
    dev_map = {d["id"]: d["hostname"].split(".")[0] for d in devices}

    by_device = {}
    by_severity = {}
    by_category = {}
    by_title = {}
    for f in findings:
        host = dev_map.get(f.get("device_id"), f.get("device_id", "?")[:8])
        by_device.setdefault(host, []).append(f)
        sev = f.get("severity", "unknown")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        cat = f.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
        title = f.get("title", "?")
        by_title.setdefault(title, []).append(host)

    print(f"=== SUMMARY ===")
    print(f"Total findings: {len(findings)}")
    print(f"Total pending approvals: {len(approvals)}")
    print(f"Severities: {by_severity}")
    print(f"Categories: {by_category}")
    print(f"\nBy device:")
    for h, fs in sorted(by_device.items()):
        print(f"  {h}: {len(fs)} findings")
        for f in fs[:5]:
            print(f"    - [{f.get('severity'):8s}] {f.get('title')}  ({f.get('agent_model')})")

    print(f"\nFindings grouped by title (correlation indicator):")
    for title, hosts in sorted(by_title.items(), key=lambda x: -len(x[1])):
        if len(hosts) > 1:
            print(f"  {len(hosts)}× '{title}' on {', '.join(hosts)}  <-- DUPLICATE FINDING ACROSS DEVICES")
        else:
            print(f"  1× '{title}' on {hosts[0]}")

    print(f"\nApprovals (pending, by Jira):")
    for a in approvals:
        rec = a.get("recommendation", {})
        f = a.get("finding", {})
        host = a.get("device", {}).get("hostname", "?").split(".")[0]
        print(f"  - [{f.get('severity', '?'):8s}] {host}: {f.get('title', '?')}  [{a.get('jira_issue_key', 'no-jira')}]")


def cmd_trigger_snapshot(): asyncio.run(trigger_snapshot())
def cmd_wait_snapshot(): print(asyncio.run(wait_snapshot()))
def cmd_summary(): asyncio.run(summary())


ACTIONS = {
    "ssh-cmd": cmd_ssh_cmd,
    "ssh-show": cmd_ssh_show,
    "trigger-snapshot": cmd_trigger_snapshot,
    "wait-snapshot": cmd_wait_snapshot,
    "summary": cmd_summary,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ACTIONS:
        print(__doc__)
        sys.exit(1)
    ACTIONS[sys.argv[1]]()
