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

    # Execute via pyATS/Netmiko
    result = await _send_commands(device, commands)

    # Update approval record
    success = not result.get("error")
    await approval_service.mark_executed(db, approval_id, result, success=success)

    # Update Jira ticket
    if approval.jira_issue_key:
        from integrations.jira import jira_client

        status = "executed" if success else "failed"
        comment = (
            f"Execution {'succeeded' if success else 'FAILED'}.\n\n"
            f"Command outputs:\n{{code}}\n{_format_outputs(result)}\n{{code}}"
        )
        await jira_client.transition_issue(approval.jira_issue_key, status, comment)

    # Notify Slack
    from integrations.slack import slack_client

    await slack_client.notify_approval_update(
        approval, "executed" if success else "failed"
    )

    # Trigger verification snapshot
    if success:
        try:
            from services.snapshot_engine import take_snapshot

            log.info("verification_snapshot_start", hostname=device.hostname)
            await take_snapshot(db, device_id=device.id, triggered_by="post-execution")
        except Exception as e:
            log.warning("verification_snapshot_failed", error=str(e))

    return result


async def _send_commands(device, commands: list[str]) -> dict:
    """Connect to a device and send commands.

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
                log.info("command_sent", hostname=device.hostname, command=cmd)
            except Exception as e:
                outputs.append(
                    {"command": cmd, "output": str(e), "success": False}
                )
                log.error(
                    "command_failed",
                    hostname=device.hostname,
                    command=cmd,
                    error=str(e),
                )
                # Stop executing on failure
                break

        try:
            tb_device.disconnect()
        except Exception:
            pass

    except ImportError:
        log.warning("pyats_not_available", mode="dry_run")
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
