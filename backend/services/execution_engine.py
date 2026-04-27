"""Execution engine — send approved remediation commands to devices.

Only executes commands from APPROVED recommendations. Captures output,
updates approval status, and triggers a verification snapshot.
"""

import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.tables import Approval, Device, Finding, Recommendation
from services import approval_service
from services.activity import activity_bus

log = structlog.get_logger()


async def execute_approved(db: AsyncSession, approval_id: str) -> dict:
    """Execute the commands for an approved recommendation.

    Returns execution result dict with command outputs.
    """
    approval = await approval_service.get_approval(db, approval_id)
    if not approval or approval.status != "approved":
        return {"error": "Approval not found or not in approved state"}

    # Load recommendation
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.id == approval.recommendation_id)
    )
    rec = rec_result.scalar_one_or_none()
    if not rec:
        return {"error": "Recommendation not found"}

    # Load finding -> device
    finding_result = await db.execute(
        select(Finding).where(Finding.id == rec.finding_id)
    )
    finding = finding_result.scalar_one_or_none()
    if not finding:
        return {"error": "Finding not found"}

    device_result = await db.execute(
        select(Device).where(Device.id == finding.device_id)
    )
    device = device_result.scalar_one_or_none()
    if not device:
        return {"error": "Device not found"}

    # Extract commands
    commands = rec.commands
    if not commands:
        return {"error": "No commands to execute"}

    # Flatten if commands are dicts (from JSON)
    if isinstance(commands[0], dict):
        commands = [c.get("command", str(c)) for c in commands]

    log.info(
        "execution_start",
        approval_id=approval_id,
        hostname=device.hostname,
        command_count=len(commands),
    )

    act_id = activity_bus.start(
        pipeline_run=f"exec:{approval_id}",
        node="execution",
        model="pyats",
        device=device.hostname,
        detail=f"Executing {len(commands)} commands on {device.hostname}",
    )

    # Execute via pyATS/Netmiko (blocking — run in thread)
    import asyncio
    result = await asyncio.to_thread(_send_commands_sync, device, commands)

    # Update approval record
    success = not result.get("error")
    duration = result.get("duration_seconds", 0)
    if success:
        activity_bus.complete(act_id, detail=f"Executed {len(commands)} commands on {device.hostname} in {duration}s")
    else:
        activity_bus.fail(act_id, f"Execution failed on {device.hostname}: {result.get('error', 'unknown')}")

    await approval_service.mark_executed(db, approval_id, result, success=success)

    # Update Jira ticket
    if approval.jira_issue_key:
        from integrations.jira import jira_client

        status = "executed" if success else "failed"
        duration = result.get("duration_seconds", 0)
        cmd_count = len(result.get("outputs", []))
        ok_count = sum(1 for o in result.get("outputs", []) if o.get("success"))

        comment_parts = [
            f"h3. Execution {'Succeeded' if success else 'FAILED'}",
            f"*Device:* {device.hostname}",
            f"*Duration:* {duration}s",
            f"*Commands:* {ok_count}/{cmd_count} succeeded",
        ]
        if rec.agent_model:
            comment_parts.append(f"*Remediation Model:* {rec.agent_model}")
        if rec.reasoning:
            comment_parts.append(f"\n*AI Reasoning:*\n{rec.reasoning}")
        comment_parts.append(
            f"\n*Command Outputs:*\n{{code}}\n{_format_outputs(result)}\n{{code}}"
        )
        if rec.rollback_commands:
            rb_list = rec.rollback_commands
            if isinstance(rb_list[0], str):
                rb_text = "\n".join(f"  {c}" for c in rb_list)
            else:
                rb_text = str(rb_list)
            comment_parts.append(
                f"\n*Rollback Commands (if needed):*\n{{code}}\n{rb_text}\n{{code}}"
            )

        comment = "\n".join(comment_parts)
        await jira_client.transition_issue(approval.jira_issue_key, status, comment)

    # Notify Slack
    from integrations.slack import slack_client

    await slack_client.notify_approval_update(
        approval, "executed" if success else "failed"
    )

    # Trigger verification snapshot + pipeline re-analysis
    if success:
        snap_act_id = activity_bus.start(
            pipeline_run=f"verify:{approval_id}",
            node="verification",
            model="pyats",
            device=device.hostname,
            detail=f"Taking verification snapshot of {device.hostname}",
        )
        try:
            from services.snapshot_engine import take_snapshot

            log.info("verification_snapshot_start", hostname=device.hostname)
            new_snaps = await take_snapshot(db, device_id=device.id, triggered_by="post-execution")
            activity_bus.complete(snap_act_id, detail=f"Verification snapshot of {device.hostname} complete")

            # Auto-trigger pipeline on the new snapshot
            if new_snaps:
                from agents.graph import run_pipeline
                from services.snapshot_engine import get_snapshot_diff

                for snap in new_snaps:
                    try:
                        diff_result = await get_snapshot_diff(db, snap.id)
                        snapshot_diff = diff_result.get("changes", {})
                        await run_pipeline(
                            db=db,
                            snapshot_id=snap.id,
                            device_id=device.id,
                            device_hostname=device.hostname,
                            device_platform=device.platform,
                            raw_snapshot=snap.snapshot_data,
                            snapshot_diff=snapshot_diff,
                        )
                    except Exception as pipe_err:
                        log.error("verification_pipeline_failed", hostname=device.hostname, error=str(pipe_err))
        except Exception as e:
            log.warning("verification_snapshot_failed", error=str(e))
            activity_bus.fail(snap_act_id, f"Verification snapshot failed: {e}")

    return result


def _send_commands_sync(device, commands: list[str]) -> dict:
    """Connect to a device and send commands (blocking — run via asyncio.to_thread).

    Uses pyATS Unicon if available, falls back to a dry-run mode.
    """
    from services.testbed_generator import generate_testbed

    outputs: list[dict] = []
    start = time.time()

    try:
        from genie.testbed import load as load_testbed

        testbed_dict = generate_testbed([device])
        testbed = load_testbed(testbed_dict)
        tb_device = testbed.devices.get(device.hostname)

        if not tb_device:
            return {"error": f"Device {device.hostname} not in testbed"}

        tb_device.connect(
            learn_hostname=True,
            log_stdout=False,
            connection_timeout=settings.pyats_connect_timeout,
        )

        for cmd in commands:
            try:
                output = tb_device.execute(cmd, timeout=settings.pyats_command_timeout)
                outputs.append({"command": cmd, "output": output, "success": True})
            except Exception as e:
                outputs.append(
                    {"command": cmd, "output": str(e), "success": False}
                )
                break

        try:
            tb_device.disconnect()
        except Exception:
            pass

    except ImportError:
        for cmd in commands:
            outputs.append(
                {"command": cmd, "output": "[DRY RUN] pyATS not installed", "success": True}
            )

    duration = round(time.time() - start, 2)
    all_success = all(o["success"] for o in outputs)

    return {
        "hostname": device.hostname,
        "outputs": outputs,
        "duration_seconds": duration,
        "success": all_success,
        **({"error": "One or more commands failed"} if not all_success else {}),
    }


def _format_outputs(result: dict) -> str:
    """Format execution outputs for display in Jira/Slack."""
    lines = []
    for o in result.get("outputs", []):
        status = "OK" if o.get("success") else "FAIL"
        lines.append(f"[{status}] {o.get('command', '?')}")
        if o.get("output"):
            lines.append(f"  {o['output'][:200]}")
    return "\n".join(lines) or "No output"
