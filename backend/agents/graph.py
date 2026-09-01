"""LangGraph pipeline definition — assembles nodes with conditional edges."""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from agents.nodes.escalation import escalation_node
from agents.nodes.escalation_remediation import escalation_remediation_node
from agents.nodes.normaliser import normaliser_node
from agents.nodes.remediation import remediation_node
from agents.nodes.topology import topology_node
from agents.state import KopisState
from db.tables import AgentRun, Approval, Finding, Recommendation
from db.vector import delete_by_snapshot, embed_finding, find_similar

log = structlog.get_logger()


def _route_after_topology(state: KopisState) -> str:
    """Conditional edge: decide where to go after the topology agent."""
    if state.get("force_escalation") or state.get("escalate_to_opus"):
        return "escalation"
    # In batch (multi-device) mode, stop here. Remediation is generated
    # post-correlation, once per incident — not once per device.
    if state.get("defer_remediation"):
        return "complete"
    stage = state.get("processing_stage", "complete")
    if stage == "remediation":
        # Check if any findings want Opus-level remediation
        findings = state.get("findings", [])
        has_opus_remediation = any(
            f.get("escalate_remediation") and f.get("requires_remediation")
            for f in findings
        )
        if has_opus_remediation:
            return "escalation_remediation"
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
    workflow.add_node("escalation_remediation", escalation_remediation_node)

    # Entry point
    workflow.set_entry_point("normaliser")

    # Edges
    workflow.add_edge("normaliser", "topology")
    workflow.add_conditional_edges(
        "topology",
        _route_after_topology,
        {
            "escalation": "escalation",
            "escalation_remediation": "escalation_remediation",
            "remediation": "remediation",
            "complete": END,
        },
    )
    workflow.add_conditional_edges(
        "escalation",
        _route_after_escalation,
        {"remediation": "remediation", "complete": END},
    )
    # Escalation remediation → Sonnet remediation (for non-escalated findings) or complete
    workflow.add_conditional_edges(
        "escalation_remediation",
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
    force_escalation: bool = False,
    snapshot_diff: dict | None = None,
    create_approvals: bool = True,
    defer_remediation: bool = False,
) -> KopisState:
    """Execute the full LangGraph pipeline for a single device snapshot.

    Persists findings and recommendations. When ``create_approvals`` is True
    (the default, used for single-device manual reruns), also creates the
    pending approval, Jira ticket, and Slack notification per recommendation.

    When ``create_approvals`` is False (used by the multi-device snapshot
    route), approvals/Jira/Slack are deferred so the cross-device correlation
    step can collapse cascade duplicates into a single incident first.
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
        "snapshot_diff": snapshot_diff or {},
        "normalised_data": {},
        "interface_summary": [],
        "routing_summary": [],
        "anomalies_detected": [],
        "findings": [],
        "recommendations": [],
        "escalate_to_opus": False,
        "force_escalation": force_escalation,
        "defer_remediation": defer_remediation,
        "processing_stage": "normalise",
        "errors": [],
        "tokens_used": {},
    }

    log.info("pipeline_start", hostname=device_hostname, snapshot_id=snapshot_id)

    # Run the graph
    final_state = await pipeline.ainvoke(initial_state)

    # Clear any existing findings for this snapshot (handles re-runs and escalations)
    from sqlalchemy import select as sa_select

    existing_findings = await db.execute(
        sa_select(Finding).where(Finding.snapshot_id == snapshot_id)
    )
    for old_finding in existing_findings.scalars().all():
        # Delete linked recommendations → approvals first
        old_recs = await db.execute(
            sa_select(Recommendation).where(Recommendation.finding_id == old_finding.id)
        )
        for old_rec in old_recs.scalars().all():
            old_apprs = await db.execute(
                sa_select(Approval).where(Approval.recommendation_id == old_rec.id)
            )
            for old_appr in old_apprs.scalars().all():
                await db.delete(old_appr)
            await db.delete(old_rec)
        await db.delete(old_finding)
    await db.flush()

    # Clean vector store for this snapshot (handles re-runs)
    delete_by_snapshot(snapshot_id)

    # Persist findings — remap AI-generated IDs to real UUIDs
    # Deduplicate against historical findings in ChromaDB
    finding_id_map: dict[str, str] = {}  # old_id → new_id
    deduped_count = 0
    deduped_finding_ids: set[str] = set()  # real IDs of findings that were deduped
    new_findings = []
    for f in final_state.get("findings", []):
        # Check for near-duplicate in vector store (from previous snapshots)
        similar = find_similar(
            device_id=device_id,
            title=f.get("title", ""),
            description=f.get("description", ""),
            affected_entity=f.get("affected_entity", ""),
            exclude_snapshot_id=snapshot_id,
        )
        if similar:
            deduped_count += 1
            log.info(
                "finding_deduped",
                title=f.get("title", ""),
                similar_to=similar[0]["finding_id"],
                distance=similar[0]["distance"],
            )
            # Map the AI ID to the existing finding's real ID. Update the
            # existing finding's snapshot_id to THIS snapshot — it's still
            # the same problem, just re-observed in a fresh snapshot. This
            # keeps cross-device correlation (which queries by snapshot_id)
            # honest about what's currently affecting the network.
            old_id = f.get("id", "")
            existing_id = similar[0]["finding_id"]
            finding_id_map[old_id] = existing_id
            deduped_finding_ids.add(existing_id)

            existing_row = await db.execute(
                sa_select(Finding).where(Finding.id == existing_id)
            )
            existing_finding = existing_row.scalar_one_or_none()
            if existing_finding is not None:
                existing_finding.snapshot_id = snapshot_id
            continue

        old_id = f.get("id", "")
        finding_id = str(uuid.uuid4())
        finding_id_map[old_id] = finding_id
        f["id"] = finding_id
        finding = Finding(
            id=finding_id,
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
        new_findings.append(f)

        # Embed in vector store for future dedup
        embed_finding(
            finding_id=finding_id,
            device_id=device_id,
            title=f.get("title", ""),
            description=f.get("description", ""),
            category=f.get("category", "unknown"),
            severity=f.get("severity", "info"),
            affected_entity=f.get("affected_entity", ""),
            snapshot_id=snapshot_id,
        )

    if deduped_count:
        log.info("findings_deduped_total", count=deduped_count, kept=len(new_findings))

    # Persist recommendations. Approvals/Jira/Slack are conditional —
    # in multi-device runs we defer them so the correlation pass can
    # collapse cascade duplicates into one incident.
    finding_lookup: dict[str, dict] = {
        f.get("id", ""): f for f in final_state.get("findings", [])
    }

    if create_approvals:
        from integrations.jira import jira_client
        from integrations.slack import slack_client

    for r in final_state.get("recommendations", []):
        # Remap AI-generated finding_id to the real UUID we assigned
        raw_finding_id = r.get("finding_id", "")
        real_finding_id = finding_id_map.get(raw_finding_id, raw_finding_id)

        # Skip recommendations for deduped findings (they already have approvals)
        if real_finding_id in deduped_finding_ids:
            continue

        # Defense in depth: nodes already refuse to emit recommendations
        # from truncated/parse-errored LLM responses (#18/#19), but never
        # persist/approve/ticket one here either if a stray marker or an
        # empty commands list slips through — a recommendation with no
        # commands isn't well-formed and must not become an approval.
        if r.get("_truncated") or r.get("_parse_error") or not r.get("commands"):
            log.warning(
                "recommendation_skipped_malformed",
                finding_id=real_finding_id,
                reason="truncated/parse-errored or missing commands",
            )
            continue

        rec_id = str(uuid.uuid4())
        rec = Recommendation(
            id=rec_id,
            finding_id=real_finding_id,
            action_description=r.get("action", ""),
            commands=r.get("commands", []),
            rollback_commands=r.get("rollback_commands", []),
            risk_level=r.get("risk_level", "medium"),
            reasoning=r.get("reasoning", ""),
            agent_model=r.get("model_used"),
            tokens_used=None,
        )
        db.add(rec)

        if not create_approvals:
            continue

        # Auto-create a pending approval for each recommendation
        approval = Approval(recommendation_id=rec_id, status="pending")

        # Create Jira service request
        linked_finding = finding_lookup.get(real_finding_id, finding_lookup.get(raw_finding_id, {}))
        jira_result = await jira_client.create_service_request(
            title=linked_finding.get("title", r.get("action", "Remediation")),
            description=r.get("reasoning", ""),
            severity=linked_finding.get("severity", "medium"),
            device_hostname=device_hostname,
            approval_id=approval.id,
            commands=r.get("commands"),
            risk_level=r.get("risk_level", "medium"),
            reasoning=r.get("reasoning"),
            rollback_commands=r.get("rollback_commands"),
            analysis_model=linked_finding.get("agent_model"),
            remediation_model=r.get("model_used"),
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

    # Per-device Slack summary — skipped in deferred mode; the multi-device
    # caller posts ONE incident summary after correlation instead.
    if create_approvals:
        from integrations.slack import slack_client
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
