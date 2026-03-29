"""Device inventory endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from models.device import DeviceRead
from services import inventory

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceRead])
async def list_devices(db: AsyncSession = Depends(get_db)):
    return await inventory.list_devices(db)


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(device_id: str, db: AsyncSession = Depends(get_db)):
    device = await inventory.get_device(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.post("/refresh", response_model=list[DeviceRead])
async def refresh_devices(db: AsyncSession = Depends(get_db)):
    return await inventory.refresh_inventory(db)
