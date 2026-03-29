"""Dashboard metrics endpoint — aggregates live device health from snapshots."""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from db.postgres import get_db
from db.tables import Device, Finding, Setting, Snapshot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/metrics")
async def dashboard_metrics(db: AsyncSession = Depends(get_db)):
    """Aggregate device health metrics for the overview dashboard.

    Sources data from:
    - Device inventory (from Grafana)
    - Latest *successful* snapshot per device
    - Unmonitored interface settings
    - Recent findings
    """
    # All devices
    result = await db.execute(select(Device).order_by(Device.hostname))
    devices = list(result.scalars().all())

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

    # Load unmonitored interface settings
    um_keys = [f"unmonitored:{d.id}" for d in devices]
    unmonitored_map: dict[str, set[str]] = {}
    if um_keys:
        result = await db.execute(select(Setting).where(Setting.key.in_(um_keys)))
        for setting in result.scalars().all():
            dev_id = setting.key.split(":", 1)[1]
            unmonitored_map[dev_id] = set(setting.value.get("interfaces", []))

    # Aggregate metrics
    total_devices = len(devices)
    devices_with_snapshots = 0
    intf_up = 0
    intf_down = 0
    intf_total = 0
    bgp_established = 0
    bgp_down = 0
    bgp_total = 0
    total_routes = 0
    total_vlans = 0
    total_arp = 0

    device_summaries = []

    for device in devices:
        snap = snapshots.get(device.id)
        um = unmonitored_map.get(device.id, set())
        summary = {
            "id": device.id,
            "hostname": device.hostname,
            "management_ip": device.management_ip,
            "platform": device.platform,
            "device_type": device.device_type,
            "has_snapshot": False,
            "interfaces_up": 0,
            "interfaces_down": 0,
            "interfaces_total": 0,
            "bgp_established": 0,
            "bgp_down": 0,
        }

        if not snap or not isinstance(snap.snapshot_data, dict):
            device_summaries.append(summary)
            continue

        devices_with_snapshots += 1
        summary["has_snapshot"] = True
        data = snap.snapshot_data

        # Interfaces (excluding unmonitored)
        interfaces = data.get("interface", {})
        if isinstance(interfaces, dict):
            for name, idata in interfaces.items():
                if not isinstance(idata, dict) or name in um:
                    continue
                intf_total += 1
                summary["interfaces_total"] += 1
                if idata.get("oper_status") == "up":
                    intf_up += 1
                    summary["interfaces_up"] += 1
                else:
                    intf_down += 1
                    summary["interfaces_down"] += 1

        # BGP
        bgp = data.get("bgp", {})
        if isinstance(bgp, dict):
            for instance in bgp.get("instance", {}).values():
                if not isinstance(instance, dict):
                    continue
                for vrf in instance.get("vrf", {}).values():
                    if not isinstance(vrf, dict):
                        continue
                    for ndata in vrf.get("neighbor", {}).values():
                        if not isinstance(ndata, dict):
                            continue
                        bgp_total += 1
                        state = ndata.get("session_state", "")
                        if state == "Established":
                            bgp_established += 1
                            summary["bgp_established"] += 1
                        else:
                            bgp_down += 1
                            summary["bgp_down"] += 1

        # Routes
        routing = data.get("routing", {})
        if isinstance(routing, dict):
            for vrf in routing.get("vrf", {}).values():
                if not isinstance(vrf, dict):
                    continue
                for af in vrf.get("address_family", {}).values():
                    if not isinstance(af, dict):
                        continue
                    total_routes += len(af.get("routes", {}))

        # VLANs
        vlan = data.get("vlan", {})
        if isinstance(vlan, dict):
            total_vlans += len(vlan.get("vlans", {}))

        # ARP
        arp = data.get("arp", {})
        if isinstance(arp, dict):
            for iface in arp.get("interfaces", {}).values():
                if isinstance(iface, dict):
                    total_arp += len((iface.get("ipv4") or {}).get("neighbors", {}))

        device_summaries.append(summary)

    # Recent findings count by severity
    result = await db.execute(
        select(Finding.severity, func.count(Finding.id))
        .group_by(Finding.severity)
    )
    finding_counts = {row[0]: row[1] for row in result.all()}

    return {
        "devices": {
            "total": total_devices,
            "with_snapshots": devices_with_snapshots,
            "without_snapshots": total_devices - devices_with_snapshots,
        },
        "interfaces": {
            "up": intf_up,
            "down": intf_down,
            "total": intf_total,
        },
        "bgp": {
            "established": bgp_established,
            "down": bgp_down,
            "total": bgp_total,
        },
        "routing": {
            "routes": total_routes,
            "vlans": total_vlans,
            "arp_entries": total_arp,
        },
        "findings": finding_counts,
        "device_summaries": device_summaries,
    }
