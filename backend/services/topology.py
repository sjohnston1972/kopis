"""Build topology graph from device inventory and snapshot data."""

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.tables import Device, Setting, Snapshot

log = structlog.get_logger()


async def build_topology(db: AsyncSession) -> dict:
    """Build a topology graph from the latest snapshot per device.

    Nodes come from the device inventory.  Edges are inferred from:
    - BGP neighbor relationships (most reliable)
    - Shared subnets between interfaces

    Returns {"nodes": [...], "edges": [...]}.
    """
    # Fetch all devices
    result = await db.execute(select(Device).order_by(Device.hostname))
    devices = list(result.scalars().all())

    if not devices:
        return {"nodes": [], "edges": []}

    # Fetch latest *successful* snapshot per device (has features_learned).
    # A failed/empty snapshot from an interrupted run should not hide good data.
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

    # Build IP → device_id mapping from interfaces
    ip_to_device: dict[str, str] = {}
    device_subnets: dict[str, list[tuple[str, str]]] = {}  # device_id → [(ip, subnet)]

    for device in devices:
        snap = snapshots.get(device.id)
        if not snap or not isinstance(snap.snapshot_data, dict):
            continue
        interfaces = snap.snapshot_data.get("interface", {})
        if not isinstance(interfaces, dict):
            continue

        for _intf_name, intf_data in interfaces.items():
            if not isinstance(intf_data, dict):
                continue
            if not intf_data.get("enabled") or intf_data.get("oper_status") != "up":
                continue
            ipv4 = intf_data.get("ipv4", {})
            if not isinstance(ipv4, dict):
                continue
            for addr_str in ipv4:
                ip = addr_str.split("/")[0]
                ip_to_device[ip] = device.id
                # Compute /24 subnet for shared-subnet detection
                parts = ip.split(".")
                if len(parts) == 4:
                    subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
                    device_subnets.setdefault(device.id, []).append((ip, subnet))

        # Also register management IP
        if device.management_ip:
            ip_to_device[device.management_ip] = device.id

    # Build edges from BGP neighbors
    edges: list[dict] = []
    edge_set: set[tuple[str, str]] = set()

    for device in devices:
        snap = snapshots.get(device.id)
        if not snap or not isinstance(snap.snapshot_data, dict):
            continue
        bgp = snap.snapshot_data.get("bgp", {})
        if not isinstance(bgp, dict):
            continue

        for instance in bgp.get("instance", {}).values():
            if not isinstance(instance, dict):
                continue
            for vrf_name, vrf in instance.get("vrf", {}).items():
                if not isinstance(vrf, dict):
                    continue
                for neighbor_ip, ndata in vrf.get("neighbor", {}).items():
                    if not isinstance(ndata, dict):
                        continue
                    peer_device_id = ip_to_device.get(neighbor_ip)
                    if not peer_device_id or peer_device_id == device.id:
                        continue

                    pair = tuple(sorted([device.id, peer_device_id]))
                    if pair in edge_set:
                        continue
                    edge_set.add(pair)

                    state = ndata.get("session_state", "Unknown")
                    health = "optimal" if state == "Established" else "critical"

                    edges.append({
                        "from": device.id,
                        "to": peer_device_id,
                        "type": "bgp",
                        "health": health,
                        "label": f"eBGP AS{ndata.get('remote_as', '?')}",
                        "session_state": state,
                    })

    # Build edges from shared subnets (for devices not already linked by BGP)
    subnet_members: dict[str, list[str]] = {}  # subnet → [device_ids]
    for dev_id, subnets in device_subnets.items():
        for _ip, subnet in subnets:
            # Skip management subnet (too broad, connects everything)
            if subnet.startswith("192.168.20."):
                continue
            subnet_members.setdefault(subnet, []).append(dev_id)

    for subnet, members in subnet_members.items():
        unique = list(set(members))
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                pair = tuple(sorted([unique[i], unique[j]]))
                if pair in edge_set:
                    continue
                edge_set.add(pair)
                edges.append({
                    "from": unique[i],
                    "to": unique[j],
                    "type": "subnet",
                    "health": "optimal",
                    "label": subnet,
                })

    # Load unmonitored interface settings for all devices
    unmonitored_keys = [f"unmonitored:{d.id}" for d in devices]
    unmonitored_map: dict[str, set[str]] = {}
    if unmonitored_keys:
        result = await db.execute(
            select(Setting).where(Setting.key.in_(unmonitored_keys))
        )
        for setting in result.scalars().all():
            dev_id = setting.key.split(":", 1)[1]
            unmonitored_map[dev_id] = set(setting.value.get("interfaces", []))

    # Build nodes
    nodes = []
    for device in devices:
        snap = snapshots.get(device.id)
        intf_up = 0
        intf_total = 0
        um = unmonitored_map.get(device.id, set())
        if snap and isinstance(snap.snapshot_data, dict):
            interfaces = snap.snapshot_data.get("interface", {})
            if isinstance(interfaces, dict):
                for _name, data in interfaces.items():
                    if isinstance(data, dict):
                        if _name in um:
                            continue
                        intf_total += 1
                        if data.get("oper_status") == "up":
                            intf_up += 1

        has_snapshot = snap is not None and isinstance(snap.snapshot_data, dict) and "error" not in snap.snapshot_data
        node_type = device.device_type or "unknown"

        nodes.append({
            "id": device.id,
            "hostname": device.hostname.split(".")[0],  # short name
            "hostname_fqdn": device.hostname,
            "management_ip": device.management_ip,
            "platform": device.platform,
            "device_type": node_type,
            "has_snapshot": has_snapshot,
            "interfaces_up": intf_up,
            "interfaces_total": intf_total,
            "tags": device.tags or {},
        })

    log.info("topology_built", nodes=len(nodes), edges=len(edges))
    return {"nodes": nodes, "edges": edges}
