"""Finding query and management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from db.tables import Finding
from models.finding import FindingRead

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("", response_model=list[FindingRead])
async def list_findings(
    severity: str | None = None,
    category: str | None = None,
    device_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    q = select(Finding).order_by(Finding.created_at.desc()).limit(limit).offset(offset)
    if severity:
        q = q.where(Finding.severity == severity)
    if category:
        q = q.where(Finding.category == category)
    if device_id:
        q = q.where(Finding.device_id == device_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{finding_id}", response_model=FindingRead)
async def get_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding
