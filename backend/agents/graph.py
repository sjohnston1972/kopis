"""LangGraph pipeline definition — assembles nodes with conditional edges."""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from agents.nodes.escalation import escalation_node
from agents.nodes.normaliser import normaliser_node
from agents.nodes.remediation import remediation_node
from agents.nodes.topology import topology_node
from agents.state import KopisState
from db.tables import AgentRun, Approval, Finding, Recommendation

log = structlog.get_logger()


def _route_after_topology(state: KopisState) -> str:
    """Conditional edge: decide where to go after the topology agent."""
    if state.get("escalate_to_opus"):
        return "escalation"
    stage = state.get("processing_stage", "complete")
    if stage == "remediation":
        return "remediation"
    return "complete"


def _route_after_escalation(state: KopisState) -> str:
    """Conditional edge: decide where to go after Opus escalation."""
    stage = state.get("processing_stage", "complete")
    if stage == "remediation":
        return "remediation"
    return "complete"


try:
    from langgraph.graph import END, StateGraph

    workflow = StateGraph(KopisState)

    # Add nodes
    workflow.add_node("normaliser", normaliser_node)
    workflow.add_node("topology", topology_node)
    workflow.add_node("remediation", remediation_node)
    workflow.add_node("escalation", escalation_node)

    # Entry point
    workflow.set_entry_point("normaliser")

    # Edges
    workflow.add_edge("normaliser", "topology")
    workflow.add_conditional_edges(
        "topology",
        _route_after_topology,
        {"escalation": "escalation", "remediation": "remediation", "complete": END},
    )
    workflow.add_conditional_edges(
        "escalation",
        _route_after_escalation,
        {"remediation": "remediation", "complete": END},
    )
    workflow.add_edge("remediation", END)

    # Compile the graph
    pipeline = workflow.compile()

except ImportError:
    log.warning("langgraph_not_installed", detail="Pipeline will not be available")
    pipeline = None


async def run_pipeline(
    db: AsyncSession,
    snapshot_id: str,
    device_id: str,
    device_hostname: str,
    device_platform: str,
    raw_snapshot: dict,
) -> KopisState:
    """Execute the full LangGraph pipeline for a single device snapshot.

    Persists findings, recommendations, and approvals to the database.
    """
    if pipeline is None:
        raise RuntimeError("LangGraph is not installed")

    # Create agent run record
    agent_run = AgentRun(snapshot_id=snapshot_id)
    db.add(agent_run)
    await db.flush()

    initial_state: KopisState = {
        "snapshot_id": snapshot_id,
        "device_id": device_id,
        "device_hostname": device_hostname,
        "device_platform": device_platform,
        "raw_snapshot": raw_snapshot,
        "normalised_data": {},
        "interface_summary": [],
        "routing_summary": [],
        "anomalies_detected": [],
        "findings": [],
        "recommendations": [],
        "escalate_to_opus": False,
        "processing_stage": "normalise",
        "errors": [],
        "tokens_used": {},
    }

    log.info("pipeline_start", hostname=device_hostname, snapshot_id=snapshot_id)

    # Run the graph
    final_state = await pipeline.ainvoke(initial_state)

    # Persist findings
    for f in final_state.get("findings", []):
        finding = Finding(
            id=f.get("id", str(uuid.uuid4())),
            snapshot_id=snapshot_id,
            device_id=device_id,
            category=f.get("category", "unknown"),
            severity=f.get("severity", "info"),
            confidence=f.get("confidence", 0.0),
            title=f.get("title", ""),
            description=f.get("description", ""),
            affected_entity=f.get("affected_entity", ""),
            evidence=f.get("evidence"),
            requires_remediation=f.get("requires_remediation", False),
            agent_model=f.get("_model"),
            tokens_used=None,
        )
        db.add(finding)

    # Persist recommendations, create approval records, and raise Jira tickets
    from integrations.jira import jira_client
    from integrations.slack import slack_client

    # Build a finding lookup for linking recommendations to finding details
    finding_lookup: dict[str, dict] = {
        f.get("id", ""): f for f in final_state.get("findings", [])
    }

    for r in final_state.get("recommendations", []):
        rec_id = r.get("id", str(uuid.uuid4()))
        rec = Recommendation(
            id=rec_id,
            finding_id=r.get("finding_id", ""),
            action_description=r.get("action", ""),
            commands=r.get("commands", []),
            rollback_commands=r.get("rollback_commands", []),
            risk_level=r.get("risk_level", "medium"),
            reasoning=r.get("reasoning", ""),
            agent_model=r.get("model_used"),
            tokens_used=None,
        )
        db.add(rec)

        # Auto-create a pending approval for each recommendation
        approval = Approval(recommendation_id=rec_id, status="pending")

        # Create Jira service request
        linked_finding = finding_lookup.get(r.get("finding_id", ""), {})
        jira_result = await jira_client.create_service_request(
            title=linked_finding.get("title", r.get("action", "Remediation")),
            description=r.get("reasoning", ""),
            severity=linked_finding.get("severity", "medium"),
            device_hostname=device_hostname,
            approval_id=approval.id,
            commands=r.get("commands"),
            risk_level=r.get("risk_level", "medium"),
        )
        if jira_result:
            approval.jira_issue_key = jira_result["key"]
            approval.jira_issue_url = jira_result["url"]

        db.add(approval)

        # Send Slack notification
        await slack_client.notify_new_approval(
            approval_id=approval.id,
            finding_title=linked_finding.get("title", "Unknown"),
            severity=linked_finding.get("severity", "medium"),
            device_hostname=device_hostname,
            action_description=r.get("action", ""),
            risk_level=r.get("risk_level", "medium"),
            commands=r.get("commands"),
            jira_url=jira_result["url"] if jira_result else None,
        )

    # Update agent run
    agent_run.completed_at = datetime.now(timezone.utc)
    agent_run.total_tokens_used = sum(final_state.get("tokens_used", {}).values())
    agent_run.models_used = final_state.get("tokens_used", {})
    agent_run.errors = final_state.get("errors") or None
    agent_run.graph_state = {
        "processing_stage": final_state.get("processing_stage"),
        "escalated": final_state.get("escalate_to_opus", False),
        "finding_count": len(final_state.get("findings", [])),
        "recommendation_count": len(final_state.get("recommendations", [])),
    }

    await db.commit()

    # Send Slack summary of all findings
    await slack_client.notify_new_findings(
        device_hostname=device_hostname,
        findings=final_state.get("findings", []),
        recommendations_count=len(final_state.get("recommendations", [])),
    )

    log.info(
        "pipeline_complete",
        hostname=device_hostname,
        findings=len(final_state.get("findings", [])),
        recommendations=len(final_state.get("recommendations", [])),
        tokens=agent_run.total_tokens_used,
        errors=final_state.get("errors"),
    )

    return final_state
