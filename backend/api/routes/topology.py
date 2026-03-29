"""Topology view data endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from services.topology import build_topology

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("")
async def get_topology(db: AsyncSession = Depends(get_db)):
    return await build_topology(db)
