"""Approval queue endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from models.approval import ApprovalAction, ApprovalDetail
from services import approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalDetail])
async def list_approvals(db: AsyncSession = Depends(get_db)):
    """List all pending approvals with full context."""
    return await approval_service.list_pending(db)


@router.post("/{approval_id}/approve", response_model=ApprovalDetail)
async def approve(
    approval_id: str,
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
):
    body = body or ApprovalAction()
    approval = await approval_service.approve(
        db,
        approval_id,
        approved_by=body.approved_by,
        approved_via=body.approved_via or "web",
        notes=body.notes,
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or not pending")

    # Update Jira ticket if linked
    if approval.jira_issue_key:
        from integrations.jira import jira_client

        await jira_client.transition_issue(
            approval.jira_issue_key,
            status="approved",
            comment=f"Approved by {body.approved_by or 'unknown'} via {body.approved_via or 'web'}",
        )

    # Notify Slack
    from integrations.slack import slack_client

    await slack_client.notify_approval_update(approval, "approved")

    return (await approval_service._enrich_approval(db, approval))


@router.post("/{approval_id}/deny", response_model=ApprovalDetail)
async def deny(
    approval_id: str,
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
):
    body = body or ApprovalAction()
    approval = await approval_service.deny(
        db,
        approval_id,
        approved_by=body.approved_by,
        approved_via=body.approved_via or "web",
        notes=body.notes,
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or not pending")

    if approval.jira_issue_key:
        from integrations.jira import jira_client

        await jira_client.transition_issue(
            approval.jira_issue_key,
            status="denied",
            comment=f"Denied by {body.approved_by or 'unknown'}: {body.notes or 'No reason given'}",
        )

    from integrations.slack import slack_client

    await slack_client.notify_approval_update(approval, "denied")

    return (await approval_service._enrich_approval(db, approval))


@router.get("/history", response_model=list[ApprovalDetail])
async def approval_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    return await approval_service.list_history(db, limit=limit)


@router.post("/expire")
async def expire_stale(db: AsyncSession = Depends(get_db)):
    """Manually trigger expiration of stale approvals."""
    count = await approval_service.expire_stale(db)
    return {"expired": count}
