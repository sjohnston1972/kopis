"""Approval queue endpoints."""

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_auth
from db.postgres import get_db, async_session
from models.approval import ApprovalAction, ApprovalDetail
from services import approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])
log = structlog.get_logger()


def _resolve_notes(client_claimed_by: str | None, verified_identity: str, notes: str | None) -> str | None:
    """Never trust a client-supplied `approved_by` as the approver identity
    (see #9) — the verified identity from require_auth is always what gets
    persisted as approved_by. If the client sent one anyway, keep it only
    as a free-text display note, clearly labelled as unverified.
    """
    if client_claimed_by and client_claimed_by != verified_identity:
        note = f"(client-supplied approver claim, not authoritative: {client_claimed_by!r})"
        return f"{note} {notes}" if notes else note
    return notes


@router.get("", response_model=list[ApprovalDetail])
async def list_approvals(db: AsyncSession = Depends(get_db)):
    """List all pending and executing approvals with full context."""
    return await approval_service.list_active(db)


@router.post("/{approval_id}/approve", response_model=ApprovalDetail)
async def approve(
    approval_id: str,
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
    identity: str = Depends(require_auth),
):
    body = body or ApprovalAction()
    # approved_by is ALWAYS the server-verified identity (see #9) — a
    # client-supplied approved_by is never trusted for the audit trail.
    notes = _resolve_notes(body.approved_by, identity, body.notes)
    approval = await approval_service.approve(
        db,
        approval_id,
        approved_by=identity,
        approved_via=body.approved_via or "web",
        notes=notes,
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or not pending")

    # Update Jira ticket if linked
    if approval.jira_issue_key:
        from integrations.jira import jira_client

        await jira_client.transition_issue(
            approval.jira_issue_key,
            status="approved",
            comment=f"Approved by {identity} via {body.approved_via or 'web'}",
        )

    # Notify Slack
    from integrations.slack import slack_client

    await slack_client.notify_approval_update(approval, "approved")

    # Auto-trigger execution in background
    asyncio.create_task(_execute_background(approval_id))

    return (await approval_service._enrich_approval(db, approval))


async def _execute_background(approval_id: str):
    """Execute the approved remediation in the background."""
    async with async_session() as db:
        try:
            from services.execution_engine import execute_approved

            result = await execute_approved(db, approval_id)
            if result.get("error"):
                log.error("auto_execution_failed", approval_id=approval_id, error=result["error"])
            else:
                log.info("auto_execution_complete", approval_id=approval_id)
        except Exception as e:
            log.error("auto_execution_error", approval_id=approval_id, error=str(e))


@router.post("/{approval_id}/deny", response_model=ApprovalDetail)
async def deny(
    approval_id: str,
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
    identity: str = Depends(require_auth),
):
    body = body or ApprovalAction()
    # approved_by is ALWAYS the server-verified identity (see #9) — a
    # client-supplied approved_by is never trusted for the audit trail.
    notes = _resolve_notes(body.approved_by, identity, body.notes)
    approval = await approval_service.deny(
        db,
        approval_id,
        approved_by=identity,
        approved_via=body.approved_via or "web",
        notes=notes,
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or not pending")

    if approval.jira_issue_key:
        from integrations.jira import jira_client

        await jira_client.transition_issue(
            approval.jira_issue_key,
            status="denied",
            comment=f"Denied by {identity}: {notes or 'No reason given'}",
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
