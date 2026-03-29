"""Finding query and management endpoints."""

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db, async_session
from db.tables import Approval, Device, Finding, Recommendation, Snapshot
from models.finding import FindingRead

router = APIRouter(prefix="/findings", tags=["findings"])
log = structlog.get_logger()


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


@router.get("/{finding_id}")
async def get_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    """Return finding with device context, recommendations, and approval status."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Load device
    dev_result = await db.execute(select(Device).where(Device.id == finding.device_id))
    device = dev_result.scalar_one_or_none()

    # Load recommendations + approvals for this finding
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.finding_id == finding_id)
    )
    recs = rec_result.scalars().all()

    rec_data = []
    for rec in recs:
        appr_result = await db.execute(
            select(Approval).where(Approval.recommendation_id == rec.id)
        )
        approval = appr_result.scalar_one_or_none()
        rec_data.append({
            "id": rec.id,
            "action_description": rec.action_description,
            "commands": rec.commands,
            "rollback_commands": rec.rollback_commands,
            "risk_level": rec.risk_level,
            "reasoning": rec.reasoning,
            "agent_model": rec.agent_model,
            "approval": {
                "id": approval.id,
                "status": approval.status,
                "jira_issue_key": approval.jira_issue_key,
                "jira_issue_url": approval.jira_issue_url,
            } if approval else None,
        })

    return {
        "id": finding.id,
        "snapshot_id": finding.snapshot_id,
        "device_id": finding.device_id,
        "category": finding.category,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "title": finding.title,
        "description": finding.description,
        "affected_entity": finding.affected_entity,
        "evidence": finding.evidence,
        "requires_remediation": finding.requires_remediation,
        "agent_model": finding.agent_model,
        "tokens_used": finding.tokens_used,
        "created_at": finding.created_at,
        "device": {
            "id": device.id,
            "hostname": device.hostname,
            "management_ip": device.management_ip,
            "platform": device.platform,
            "device_type": device.device_type,
        } if device else None,
        "recommendations": rec_data,
    }


@router.delete("/{finding_id}")
async def dismiss_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    """Dismiss (delete) a finding and its linked recommendations/approvals."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Delete linked approvals → recommendations → finding
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.finding_id == finding_id)
    )
    for rec in rec_result.scalars().all():
        appr_result = await db.execute(
            select(Approval).where(Approval.recommendation_id == rec.id)
        )
        for appr in appr_result.scalars().all():
            await db.delete(appr)
        await db.delete(rec)

    await db.delete(finding)
    await db.commit()
    log.info("finding_dismissed", finding_id=finding_id, title=finding.title)
    return {"status": "dismissed", "id": finding_id}


@router.post("/{finding_id}/escalate")
async def escalate_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    """Re-analyse this finding's snapshot with Opus (Tier 3) escalation."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Load snapshot and device
    snap_result = await db.execute(
        select(Snapshot).where(Snapshot.id == finding.snapshot_id)
    )
    snapshot = snap_result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    dev_result = await db.execute(
        select(Device).where(Device.id == finding.device_id)
    )
    device = dev_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Launch escalation in background
    asyncio.create_task(_escalate_background(
        snapshot_id=snapshot.id,
        device_id=device.id,
        device_hostname=device.hostname,
        device_platform=device.platform,
        raw_snapshot=snapshot.snapshot_data,
    ))

    return {
        "status": "escalating",
        "finding_id": finding_id,
        "device": device.hostname,
        "message": "Re-analysing with Opus. New findings will appear shortly.",
    }


async def _escalate_background(
    snapshot_id: str,
    device_id: str,
    device_hostname: str,
    device_platform: str,
    raw_snapshot: dict,
):
    """Run the full pipeline with forced Opus escalation."""
    async with async_session() as db:
        try:
            from agents.graph import run_pipeline

            await run_pipeline(
                db=db,
                snapshot_id=snapshot_id,
                device_id=device_id,
                device_hostname=device_hostname,
                device_platform=device_platform,
                raw_snapshot=raw_snapshot,
                force_escalation=True,
            )

            log.info("escalation_complete", hostname=device_hostname)
        except Exception as e:
            log.error("escalation_failed", hostname=device_hostname, error=str(e))
