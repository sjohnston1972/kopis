"""Pydantic schemas for approvals."""

from datetime import datetime

from pydantic import BaseModel


class ApprovalAction(BaseModel):
    approved_by: str | None = None
    approved_via: str | None = None  # web, slack, jira
    notes: str | None = None


class ApprovalRead(BaseModel):
    id: str
    recommendation_id: str
    status: str
    approved_by: str | None = None
    approved_via: str | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    execution_result: dict | None = None
    notes: str | None = None
    jira_issue_key: str | None = None
    jira_issue_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApprovalDetail(ApprovalRead):
    """Extended approval with recommendation and finding context."""
    finding_title: str | None = None
    finding_severity: str | None = None
    device_hostname: str | None = None
    action_description: str | None = None
    commands: list | None = None
    rollback_commands: list | None = None
    risk_level: str | None = None
    reasoning: str | None = None
