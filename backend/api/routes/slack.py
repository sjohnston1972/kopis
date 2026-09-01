"""Slack interactivity endpoint — receives Approve/Deny button clicks.

SECURITY: this route authenticates requests using Slack's HMAC request
signature (see ``integrations/slack_verify.verify_slack_signature``), NOT
the token-based auth dependency used elsewhere in this API. Slack has no
way to send our bearer token — its interactivity callbacks are signed
with a shared secret instead. Do NOT add ``Depends(require_api_token)``
(or whatever the token dependency ends up being called) to this route: it
would simply make every real Slack click fail with 401. Signature
verification against the raw request body is the correct — and
sufficient — authentication for this endpoint.

The raw body is read via ``await request.body()`` before any form/JSON
parsing happens, and that exact byte string is what gets verified. Slack
signs the literal bytes it sent; parsing and re-serialising first would
produce a different byte string and every signature would fail.
"""

import asyncio
import json
import urllib.parse

import structlog
from fastapi import APIRouter, HTTPException, Request

from db.postgres import async_session
from integrations.slack_verify import verify_slack_signature
from services import approval_service

router = APIRouter(prefix="/slack", tags=["slack"])
log = structlog.get_logger()

_APPROVE_ACTION_ID = "approve_remediation"
_DENY_ACTION_ID = "deny_remediation"


@router.post("/actions")
async def slack_actions(request: Request):
    """Handle a Slack `block_actions` interactivity payload.

    Verifies the request signature, extracts the clicked button and the
    approval it targets, and drives the same approval_service.approve/deny
    methods the web UI route uses — no transition logic is duplicated here.
    """
    # Read the raw body FIRST. Nothing before this line may touch/parse
    # the request body, or the signature check below will not match.
    raw_body = await request.body()

    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    if not verify_slack_signature(raw_body, timestamp, signature):
        log.warning("slack_signature_rejected")
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    # Slack posts `application/x-www-form-urlencoded` with a `payload`
    # field containing URL-encoded JSON. Parsed by hand (rather than
    # request.form()) so we don't pull in an extra form-parsing
    # dependency for a single well-known field.
    form = urllib.parse.parse_qs(raw_body.decode("utf-8"))
    payload_values = form.get("payload")
    if not payload_values:
        raise HTTPException(status_code=400, detail="Missing payload field")

    try:
        payload = json.loads(payload_values[0])
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed payload JSON")

    actions = payload.get("actions") or []
    if not actions:
        raise HTTPException(status_code=400, detail="No action present in payload")

    action = actions[0]
    action_id = action.get("action_id")
    approval_id = action.get("value")

    if action_id not in (_APPROVE_ACTION_ID, _DENY_ACTION_ID) or not approval_id:
        raise HTTPException(status_code=400, detail="Unrecognized Slack action")

    # Approver identity comes from the verified Slack payload — never from
    # anything else the client could have supplied.
    slack_user = payload.get("user") or {}
    approved_by = slack_user.get("username") or slack_user.get("name") or slack_user.get("id") or "slack"

    async with async_session() as db:
        if action_id == _APPROVE_ACTION_ID:
            approval = await approval_service.approve(
                db, approval_id, approved_by=approved_by, approved_via="slack",
            )
            outcome = "approved"
        else:
            approval = await approval_service.deny(
                db, approval_id, approved_by=approved_by, approved_via="slack",
            )
            outcome = "denied"

        if not approval:
            return {
                "response_type": "ephemeral",
                "text": f"Approval `{approval_id}` was not found, or is no longer pending.",
            }

        if approval.jira_issue_key:
            from integrations.jira import jira_client

            await jira_client.transition_issue(
                approval.jira_issue_key,
                status=outcome,
                comment=f"{outcome.capitalize()} by {approved_by} via slack",
            )

    from integrations.slack import slack_client

    await slack_client.notify_approval_update(approval, outcome)

    if outcome == "approved":
        # Reuse the same background-execution trigger the web approve
        # route uses, rather than duplicating execution-kickoff logic.
        from api.routes.approvals import _execute_background

        asyncio.create_task(_execute_background(approval_id))

    log.info("slack_action_processed", approval_id=approval_id, outcome=outcome, by=approved_by)

    return {
        "response_type": "in_channel",
        "replace_original": True,
        "text": f":white_check_mark: Approval `{approval_id}` {outcome} by {approved_by}."
        if outcome == "approved"
        else f":no_entry_sign: Approval `{approval_id}` {outcome} by {approved_by}.",
    }
