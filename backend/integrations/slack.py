"""Slack integration — webhook notifications and interactive approval messages."""

import httpx
import structlog

from config import settings

log = structlog.get_logger()

SEVERITY_EMOJI = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":large_blue_circle:",
    "info": ":white_circle:",
}

RISK_EMOJI = {
    "high": ":warning:",
    "medium": ":large_yellow_circle:",
    "low": ":white_check_mark:",
}


def _format_rollback_status_slack(result: dict) -> str:
    """One-glance rollback line for a failed-execution Slack message.

    Mirrors the Jira rollback summary (execution_engine.py) so the same
    ran/succeeded/failed/none outcome is visible in both places.
    """
    rolled_back = result.get("rolled_back", False)
    rb_outputs = result.get("rollback_outputs") or []

    if rolled_back:
        return ":leftwards_arrow_with_hook: *Rollback: SUCCEEDED* — device was restored."
    if rb_outputs:
        return (
            ":rotating_light: *Rollback: FAILED — MANUAL INTERVENTION REQUIRED* "
            "— device is likely left in a partially-configured state."
        )
    return (
        ":rotating_light: *Rollback: NOT ATTEMPTED — MANUAL INTERVENTION REQUIRED* "
        "— device may be left in a partially-configured state."
    )


class SlackClient:
    def __init__(self) -> None:
        self.webhook_url = settings.slack_webhook_url
        self._enabled = bool(self.webhook_url)

    async def _post(self, payload: dict) -> bool:
        if not self._enabled:
            log.debug("slack_skip", reason="not configured")
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(self.webhook_url, json=payload)
                r.raise_for_status()
                return True
        except Exception as e:
            log.error("slack_post_failed", error=str(e))
            return False

    async def notify_new_findings(
        self,
        device_hostname: str,
        findings: list[dict],
        recommendations_count: int,
    ) -> bool:
        """Post a summary of new findings from a pipeline run."""
        if not findings:
            return False

        severity_counts = {}
        for f in findings:
            s = f.get("severity", "info")
            severity_counts[s] = severity_counts.get(s, 0) + 1

        severity_line = "  ".join(
            f"{SEVERITY_EMOJI.get(s, '')} {s}: {c}" for s, c in severity_counts.items()
        )

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Kopis — New findings for {device_hostname}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{len(findings)} finding(s)* detected\n"
                        f"{severity_line}\n"
                        f"*{recommendations_count}* remediation(s) pending approval"
                    ),
                },
            },
            {"type": "divider"},
        ]

        # Top 5 findings
        for f in findings[:5]:
            emoji = SEVERITY_EMOJI.get(f.get("severity", ""), "")
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{emoji} *{f.get('title', 'Untitled')}*\n"
                            f"Severity: {f.get('severity')} | "
                            f"Confidence: {f.get('confidence', 0):.0%}\n"
                            f"Entity: `{f.get('affected_entity', 'N/A')}`"
                        ),
                    },
                }
            )

        if len(findings) > 5:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"_...and {len(findings) - 5} more finding(s)_",
                        }
                    ],
                }
            )

        return await self._post({"blocks": blocks})

    async def notify_new_approval(
        self,
        approval_id: str,
        finding_title: str,
        severity: str,
        device_hostname: str,
        action_description: str,
        risk_level: str,
        commands: list | None = None,
        jira_url: str | None = None,
    ) -> bool:
        """Post an approval request to Slack."""
        emoji = SEVERITY_EMOJI.get(severity, "")
        risk_emoji = RISK_EMOJI.get(risk_level, "")

        cmd_preview = ""
        if commands:
            cmd_list = commands[:5] if isinstance(commands[0], str) else [str(c) for c in commands[:5]]
            joined = "\n".join(cmd_list)
            cmd_preview = f"\n```\n{joined}\n```"
            if len(commands) > 5:
                cmd_preview += f"\n_...and {len(commands) - 5} more command(s)_"

        jira_line = f"\n:jira: <{jira_url}|View in Jira>" if jira_url else ""

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Kopis — Approval Required",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji} *{finding_title}*\n"
                        f"Device: `{device_hostname}` | Risk: {risk_emoji} {risk_level}\n\n"
                        f"*Recommended action:* {action_description}"
                        f"{cmd_preview}"
                        f"{jira_line}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Approval ID: `{approval_id}`",
                    }
                ],
            },
        ]

        action_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                "style": "primary",
                "action_id": "approve_remediation",
                "value": approval_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Deny", "emoji": True},
                "style": "danger",
                "action_id": "deny_remediation",
                "value": approval_id,
            },
        ]
        if jira_url:
            action_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View in Jira", "emoji": True},
                    "action_id": "view_jira_issue",
                    "url": jira_url,
                }
            )
        blocks.append({"type": "actions", "block_id": "approval_actions", "elements": action_elements})

        return await self._post({"blocks": blocks})

    async def notify_approval_update(
        self, approval, action: str, result: dict | None = None
    ) -> bool:
        """Notify that an approval was approved/denied/executed/failed.

        `result` is the execution result dict (see execution_engine.py) and
        is only expected on a `failed` action — it's how a rollback outcome
        (ran/succeeded/failed/none) reaches Slack at a glance instead of
        operators having to dig through Jira or the DB to find out whether
        the device was restored or needs manual attention right now.
        """
        emoji = {
            "approved": ":white_check_mark:",
            "denied": ":no_entry_sign:",
            "executed": ":rocket:",
            "failed": ":x:",
            "expired": ":hourglass:",
        }.get(action, ":grey_question:")

        text = (
            f"{emoji} *Approval {action}*\n"
            f"ID: `{approval.id}`\n"
            f"By: {approval.approved_by or 'system'}"
        )
        if approval.notes:
            text += f"\nNotes: {approval.notes}"

        if action == "failed" and result:
            text += f"\n{_format_rollback_status_slack(result)}"

        return await self._post({"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]})


slack_client = SlackClient()
