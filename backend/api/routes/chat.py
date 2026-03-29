"""Chat endpoint — streaming conversation with Claude about this network."""

import json
import re

import httpx
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.postgres import get_db
from db.tables import Device, Snapshot, Finding

router = APIRouter(prefix="/chat", tags=["chat"])
log = structlog.get_logger()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}]
    model: str | None = None


def _summarise_snapshot(snap_data: dict) -> str:
    """Build a concise text summary of a pyATS snapshot."""
    if not isinstance(snap_data, dict):
        return "  (invalid snapshot data)"

    if "error" in snap_data:
        return f"  Error: {snap_data['error']}"

    sections = []

    # Interfaces
    intfs = snap_data.get("interface", {})
    if isinstance(intfs, dict):
        up, down, total = 0, 0, 0
        intf_details = []
        for name, data in intfs.items():
            if not isinstance(data, dict):
                continue
            total += 1
            oper = data.get("oper_status", "unknown")
            if oper == "up":
                up += 1
            else:
                down += 1
            # Include IP info
            ipv4 = data.get("ipv4", {})
            ips = list(ipv4.keys()) if isinstance(ipv4, dict) else []
            status = "UP" if oper == "up" else "DOWN"
            line = f"    {name}: {status}"
            if ips:
                line += f" ({', '.join(ips)})"
            # Error counters
            counters = data.get("counters", {})
            if isinstance(counters, dict):
                in_err = counters.get("in_errors", 0)
                out_err = counters.get("out_errors", 0)
                in_disc = counters.get("in_discards", 0)
                if in_err or out_err or in_disc:
                    line += f" [errors: in={in_err} out={out_err} discards={in_disc}]"
            intf_details.append(line)
        sections.append(f"  Interfaces: {up} up / {down} down / {total} total")
        if intf_details:
            sections.append("\n".join(intf_details))

    # BGP
    bgp = snap_data.get("bgp", {})
    if isinstance(bgp, dict):
        neighbors = []
        for inst in bgp.get("instance", {}).values():
            if not isinstance(inst, dict):
                continue
            for vrf_name, vrf in inst.get("vrf", {}).items():
                if not isinstance(vrf, dict):
                    continue
                for neigh_ip, ndata in vrf.get("neighbor", {}).items():
                    if not isinstance(ndata, dict):
                        continue
                    state = ndata.get("session_state", "Unknown")
                    remote_as = ndata.get("remote_as", "?")
                    neighbors.append(f"    {neigh_ip} AS{remote_as} — {state}")
        if neighbors:
            sections.append("  BGP Neighbors:")
            sections.append("\n".join(neighbors))

    # OSPF
    ospf = snap_data.get("ospf", {})
    if isinstance(ospf, dict):
        ospf_lines = []
        for inst_id, inst in ospf.get("vrf", {}).items() if isinstance(ospf.get("vrf"), dict) else []:
            pass
        # Try alternative structure
        for inst_key, inst in ospf.items():
            if not isinstance(inst, dict):
                continue
            areas = inst.get("areas", {})
            if isinstance(areas, dict):
                for area_id, area in areas.items():
                    intfs_in_area = area.get("interfaces", {}) if isinstance(area, dict) else {}
                    intf_names = list(intfs_in_area.keys()) if isinstance(intfs_in_area, dict) else []
                    if intf_names:
                        ospf_lines.append(f"    Area {area_id}: {', '.join(intf_names)}")
        if ospf_lines:
            sections.append("  OSPF:")
            sections.append("\n".join(ospf_lines))

    # VLANs
    vlan = snap_data.get("vlan", {})
    if isinstance(vlan, dict):
        vlans = vlan.get("vlans", {})
        if isinstance(vlans, dict) and vlans:
            vlan_list = []
            for vid, vdata in sorted(vlans.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 9999):
                name = vdata.get("name", "") if isinstance(vdata, dict) else ""
                state = vdata.get("state", "") if isinstance(vdata, dict) else ""
                vlan_list.append(f"    VLAN {vid}: {name} ({state})")
            sections.append("  VLANs:")
            sections.append("\n".join(vlan_list[:20]))  # Cap at 20

    # Platform
    platform = snap_data.get("platform", {})
    if isinstance(platform, dict):
        chassis = platform.get("chassis", "")
        version = platform.get("os", platform.get("software_version", ""))
        uptime = platform.get("uptime", "")
        if chassis or version:
            sections.append(f"  Platform: {chassis} {version}")
        if uptime:
            sections.append(f"  Uptime: {uptime}")

    # Routing table summary
    routing = snap_data.get("routing", {})
    if isinstance(routing, dict):
        for vrf_name, vrf in routing.get("vrf", {}).items():
            if not isinstance(vrf, dict):
                continue
            for af_name, af in vrf.get("address_family", {}).items():
                if not isinstance(af, dict):
                    continue
                routes = af.get("routes", {})
                if isinstance(routes, dict):
                    sections.append(f"  Routes ({vrf_name}/{af_name}): {len(routes)} entries")

    return "\n".join(sections) if sections else "  (snapshot collected but no parseable features)"


def _find_mentioned_devices(user_message: str, hostnames: list[str]) -> list[str]:
    """Find device hostnames mentioned in the user's message."""
    msg_lower = user_message.lower()
    matched = []
    for hostname in hostnames:
        short = hostname.split(".")[0].lower()
        if short in msg_lower or hostname.lower() in msg_lower:
            matched.append(hostname)
    return matched


async def _build_system_prompt(db: AsyncSession, user_message: str) -> str:
    """Build a system prompt with live network context."""
    # Device summary
    result = await db.execute(
        select(
            Device.device_type,
            func.count(Device.id),
        ).group_by(Device.device_type)
    )
    type_counts = {row[0]: row[1] for row in result.all()}
    total_devices = sum(type_counts.values())

    # All devices
    result = await db.execute(
        select(Device).order_by(Device.hostname)
    )
    devices = list(result.scalars().all())
    hostnames = [d.hostname for d in devices]
    device_map = {d.id: d for d in devices}

    device_list = "\n".join(
        f"  - {d.hostname} ({d.management_ip}) — {d.platform} {d.device_type}"
        for d in devices
    )

    # Snapshot stats
    result = await db.execute(select(func.count(Snapshot.id)))
    snap_count = result.scalar() or 0

    # Latest successful snapshot per device
    latest_sq = (
        select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
        .where(func.array_length(Snapshot.features_learned, 1) > 0)
        .group_by(Snapshot.device_id)
        .subquery()
    )
    result = await db.execute(
        select(Snapshot)
        .join(
            latest_sq,
            (Snapshot.device_id == latest_sq.c.device_id)
            & (Snapshot.created_at == latest_sq.c.max_ts),
        )
    )
    snapshots = {s.device_id: s for s in result.scalars().all()}

    # Find which devices the user is asking about
    mentioned = _find_mentioned_devices(user_message, hostnames)

    # Build snapshot sections
    # For mentioned devices: full detail. For others: one-line summary.
    mentioned_set = set(d.hostname for d in devices if d.hostname in mentioned)
    snapshot_sections = []

    for device in devices:
        snap = snapshots.get(device.id)
        short = device.hostname.split(".")[0]
        if not snap or not isinstance(snap.snapshot_data, dict):
            snapshot_sections.append(f"### {short} — No snapshot data")
            continue

        if device.hostname in mentioned_set:
            # Full detail for mentioned devices
            summary = _summarise_snapshot(snap.snapshot_data)
            features = ", ".join(snap.features_learned or [])
            snapshot_sections.append(
                f"### {short} ({device.management_ip}) — DETAILED\n"
                f"  Features learned: {features}\n"
                f"  Snapshot taken: {snap.created_at.isoformat()}\n"
                f"{summary}"
            )
        else:
            # Brief one-liner for others
            intfs = snap.snapshot_data.get("interface", {})
            up = sum(1 for d in intfs.values() if isinstance(d, dict) and d.get("oper_status") == "up") if isinstance(intfs, dict) else 0
            total = len(intfs) if isinstance(intfs, dict) else 0
            snapshot_sections.append(f"### {short} — {up}/{total} interfaces up")

    snapshot_text = "\n".join(snapshot_sections)

    # Recent findings
    result = await db.execute(
        select(Finding.title, Finding.severity, Finding.affected_entity, Finding.category)
        .order_by(Finding.created_at.desc())
        .limit(10)
    )
    findings = result.all()
    findings_text = "\n".join(
        f"  - [{f.severity.upper()}] {f.title} — {f.affected_entity} ({f.category})"
        for f in findings
    ) if findings else "  No findings recorded yet."

    return f"""You are Kopis, an AI network operations assistant for a homelab network.
You are an expert network engineer with deep knowledge of Cisco IOS-XE, IOS-v, NX-OS, BGP, OSPF, spanning-tree, VLANs, and general enterprise networking.

## Your Role
- Help the operator understand, diagnose, and plan changes to their network
- Answer questions about device configurations, routing, topology, and best practices
- Suggest remediation steps for network issues
- Explain findings and alerts in plain language
- You have access to real snapshot data from pyATS — use it to give specific, accurate answers

## Network Overview
This is a homelab network running in GNS3, monitored by the Kopis platform.
- **Total devices:** {total_devices}
- **Breakdown:** {', '.join(f'{count} {dtype}s' for dtype, count in type_counts.items())}
- **Snapshots collected:** {snap_count}

## Device Inventory
{device_list}

## Snapshot Data
{snapshot_text}

## Recent Findings (last 10)
{findings_text}

## Guidelines
- Be concise and direct — this operator is an experienced network engineer
- When discussing a device, reference the actual snapshot data above
- When suggesting commands, use the correct syntax for the device's platform (IOS-XE vs NX-OS)
- If a device has no snapshot, say so and suggest taking one
- Format CLI commands in code blocks
- Never invent data — only reference what's in the snapshots above"""


@router.post("")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    # Use the latest user message for context-aware prompt building
    user_message = ""
    for msg in reversed(req.messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break

    system = await _build_system_prompt(db, user_message)
    model = req.model or settings.haiku_model

    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.3,
        "system": system,
        "messages": req.messages,
        "stream": True,
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async def generate():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", ANTHROPIC_API_URL, headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield f"data: {json.dumps({'text': delta['text']})}\n\n"
                    elif etype == "message_stop":
                        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
