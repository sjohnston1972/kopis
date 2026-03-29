"""Snapshot CRUD and trigger endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from models.snapshot import SnapshotDetail, SnapshotDiff, SnapshotRead, SnapshotTrigger
from services import snapshot_engine

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.post("", response_model=list[SnapshotRead])
async def trigger_snapshot(
    body: SnapshotTrigger | None = None,
    db: AsyncSession = Depends(get_db),
):
    device_id = body.device_id if body else None
    snapshots = await snapshot_engine.take_snapshot(db, device_id=device_id)
    return snapshots


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
