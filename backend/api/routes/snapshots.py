"""Snapshot CRUD and trigger endpoints."""

import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db, async_session
from db.tables import Setting
from models.snapshot import SnapshotDetail, SnapshotDiff, SnapshotRead, SnapshotTrigger
from services import snapshot_engine

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
log = structlog.get_logger()

SNAP_STATUS_KEY = "snapshot_status"


async def _read_status(db: AsyncSession) -> dict:
    result = await db.execute(select(Setting).where(Setting.key == SNAP_STATUS_KEY))
    row = result.scalar_one_or_none()
    return row.value if row else {"running": False}


async def _write_status(db: AsyncSession, value: dict):
    result = await db.execute(select(Setting).where(Setting.key == SNAP_STATUS_KEY))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(Setting(key=SNAP_STATUS_KEY, value=value))
    await db.commit()


async def _run_snapshot_background(device_id: str | None):
    """Run snapshot in the background, updating status in the settings table."""
    async with async_session() as db:
        started = datetime.now(timezone.utc)
        try:
            await _write_status(db, {
                "running": True,
                "started_at": started.isoformat(),
                "device_id": device_id,
            })
            results = await snapshot_engine.take_snapshot(db, device_id=device_id)
            finished = datetime.now(timezone.utc)

            # Build per-device breakdown
            # Eager-load device hostnames
            dev_ids = [s.device_id for s in results]
            dev_map = {}
            if dev_ids:
                from db.tables import Device
                dev_result = await db.execute(
                    select(Device).where(Device.id.in_(dev_ids))
                )
                dev_map = {d.id: d.hostname.split(".")[0] for d in dev_result.scalars().all()}

            per_device = []
            ok_devices = 0
            failed_devices = 0
            total_duration = 0.0
            successful_snapshots = []
            for s in results:
                has_error = "error" in (s.snapshot_data or {})
                features = s.features_learned or []
                if has_error:
                    failed_devices += 1
                else:
                    ok_devices += 1
                    successful_snapshots.append(s)
                total_duration += s.duration_seconds or 0
                per_device.append({
                    "hostname": dev_map.get(s.device_id, s.device_id[:8]),
                    "features": len(features),
                    "ok": not has_error,
                })

            await _write_status(db, {
                "running": False,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "result": "ok" if failed_devices == 0 else "partial",
                "devices_total": len(results),
                "devices_ok": ok_devices,
                "devices_failed": failed_devices,
                "per_device": per_device,
                "duration": round(total_duration, 1),
            })

            # Auto-trigger the LangGraph pipeline for each successful snapshot
            if successful_snapshots:
                log.info("pipeline_auto_trigger", count=len(successful_snapshots))
                from agents.graph import run_pipeline

                for snap in successful_snapshots:
                    try:
                        hostname = dev_map.get(snap.device_id, "unknown")
                        # Load device for platform info
                        dev_result2 = await db.execute(
                            select(Device).where(Device.id == snap.device_id)
                        )
                        dev = dev_result2.scalar_one_or_none()
                        platform = dev.platform if dev else "unknown"

                        await run_pipeline(
                            db=db,
                            snapshot_id=snap.id,
                            device_id=snap.device_id,
                            device_hostname=hostname,
                            device_platform=platform,
                            raw_snapshot=snap.snapshot_data,
                        )
                        log.info("pipeline_auto_complete", hostname=hostname)
                    except Exception as pipe_err:
                        log.error("pipeline_auto_failed",
                                  hostname=dev_map.get(snap.device_id, snap.device_id[:8]),
                                  error=str(pipe_err))
        except Exception as e:
            log.error("background_snapshot_failed", error=str(e))
            await _write_status(db, {
                "running": False,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": "error",
                "error": str(e),
            })


@router.get("/status")
async def snapshot_status(db: AsyncSession = Depends(get_db)):
    """Return current snapshot run status.

    If a snapshot has been 'running' for more than 30 minutes, it is
    assumed to have crashed (e.g. container restart) and is auto-reset.
    """
    status = await _read_status(db)
    if status.get("running") and status.get("started_at"):
        started = datetime.fromisoformat(status["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        if elapsed > 1800:  # 30 minutes
            log.warning("snapshot_stale_reset", elapsed=elapsed)
            status = {
                "running": False,
                "started_at": status["started_at"],
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result": "error",
                "error": "Snapshot timed out (exceeded 30 minutes)",
            }
            await _write_status(db, status)
    return status


@router.post("", response_model=list[SnapshotRead])
async def trigger_snapshot(
    body: SnapshotTrigger | None = None,
    db: AsyncSession = Depends(get_db),
):
    device_id = body.device_id if body else None

    # Check if one is already running
    status = await _read_status(db)
    if status.get("running"):
        raise HTTPException(status_code=409, detail="Snapshot already in progress")

    # Launch in background so the response returns immediately
    asyncio.create_task(_run_snapshot_background(device_id))
    return []


@router.get("", response_model=list[SnapshotRead])
async def list_snapshots(
    device_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    return await snapshot_engine.list_snapshots(db, device_id=device_id, limit=limit, offset=offset)


@router.get("/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot(snapshot_id: str, db: AsyncSession = Depends(get_db)):
    snapshot = await snapshot_engine.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@router.get("/{snapshot_id}/diff", response_model=SnapshotDiff)
async def get_snapshot_diff(snapshot_id: str, db: AsyncSession = Depends(get_db)):
    diff = await snapshot_engine.get_snapshot_diff(db, snapshot_id)
    if "error" in diff:
        raise HTTPException(status_code=404, detail=diff["error"])
    return diff
