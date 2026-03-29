"""Topology view data endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from db.tables import Setting
from services.topology import build_topology

router = APIRouter(prefix="/topology", tags=["topology"])

LAYOUT_KEY = "topology_layout"


class TopologyLayout(BaseModel):
    positions: dict = {}
    zones: list = []


@router.get("")
async def get_topology(db: AsyncSession = Depends(get_db)):
    return await build_topology(db)


@router.get("/layout")
async def get_layout(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting).where(Setting.key == LAYOUT_KEY))
    row = result.scalar_one_or_none()
    if not row:
        return {"positions": {}, "zones": []}
    return row.value


@router.put("/layout")
async def save_layout(layout: TopologyLayout, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting).where(Setting.key == LAYOUT_KEY))
    row = result.scalar_one_or_none()
    data = layout.model_dump()
    if row:
        row.value = data
    else:
        db.add(Setting(key=LAYOUT_KEY, value=data))
    await db.commit()
    return data
