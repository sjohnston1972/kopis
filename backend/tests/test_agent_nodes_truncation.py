"""Regression coverage: each of the four LLM-backed agent nodes must
refuse a truncated/unparseable Anthropic response — zero
recommendations/findings, plus a visible entry in `errors` — rather than
treat a partial or garbled result as real output (see issues #18/#19 and
`agents/nodes/_llm_guard.py`).

Covers `remediation_node`, `topology_node`, `escalation_node`, and
`escalation_remediation_node` from `agents/nodes/`. Each test monkeypatches
the single shared `anthropic_client` singleton's `.message()` coroutine —
every node module imports the same instance from `integrations.anthropic`,
so patching the instance method covers all of them without needing to
patch each module's local name separately.

No network access (the Anthropic call is mocked out entirely) and no
database — `agents.state.KopisState` is a plain TypedDict, and
`services.activity.activity_bus` is in-memory. Runs standalone, no
Postgres needed.
"""

from unittest.mock import AsyncMock

import pytest

from agents.nodes import escalation, escalation_remediation, remediation, topology
from integrations.anthropic import anthropic_client

TRUNCATED_RESULT = {"_truncated": True, "_tokens": 42, "_model": "claude-sonnet-test"}
PARSE_ERROR_RESULT = {
    "_parse_error": True,
    "text": "not json",
    "_tokens": 17,
    "_model": "claude-sonnet-test",
}


def _patch_message(monkeypatch, return_value):
    # `remediation_node`/etc. mutate the returned dict in place (they
    # `.pop()` "_tokens"/"_model" off it). Return a FRESH copy on every
    # call so the shared TRUNCATED_RESULT/PARSE_ERROR_RESULT module
    # constants used across parametrized tests are never mutated.
    monkeypatch.setattr(
        anthropic_client, "message", AsyncMock(side_effect=lambda *a, **kw: dict(return_value))
    )


def _remediable_finding(escalate_remediation=False):
    return {
        "id": "f1",
        "category": "interface",
        "severity": "high",
        "confidence": 0.9,
        "title": "Interface Gi0/1 is admin-down",
        "affected_entity": "GigabitEthernet0/1",
        "requires_remediation": True,
        "escalate_remediation": escalate_remediation,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", [TRUNCATED_RESULT, PARSE_ERROR_RESULT])
class TestRemediationNodeRefusesUnusableResult:
    async def test_zero_recommendations_and_error_recorded(self, monkeypatch, bad_result):
        _patch_message(monkeypatch, bad_result)
        state = {
            "device_hostname": "r1",
            "device_platform": "iosxe",
            "findings": [_remediable_finding()],
            "errors": [],
        }

        out = await remediation.remediation_node(state)

        assert out["recommendations"] == []
        assert out["processing_stage"] == "complete"
        assert len(out["errors"]) == 1
        assert "Remediation agent" in out["errors"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", [TRUNCATED_RESULT, PARSE_ERROR_RESULT])
class TestTopologyNodeRefusesUnusableResult:
    async def test_zero_findings_and_error_recorded(self, monkeypatch, bad_result):
        _patch_message(monkeypatch, bad_result)
        state = {
            "device_hostname": "r1",
            "device_platform": "iosxe",
            "normalised_data": {},
            "interface_summary": [],
            "routing_summary": [],
            # Non-empty so the node doesn't short-circuit BEFORE calling the LLM.
            "anomalies_detected": [{"type": "interface_down", "entity": "Gi0/1"}],
            "snapshot_diff": {},
            "errors": [],
        }

        out = await topology.topology_node(state)

        assert out["findings"] == []
        assert out["escalate_to_opus"] is False
        assert out["processing_stage"] == "complete"
        assert len(out["errors"]) == 1
        assert "Topology agent" in out["errors"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", [TRUNCATED_RESULT, PARSE_ERROR_RESULT])
class TestEscalationNodeRefusesUnusableResult:
    async def test_falls_back_to_pre_escalation_findings_zero_recommendations(
        self, monkeypatch, bad_result
    ):
        _patch_message(monkeypatch, bad_result)
        pre_escalation_findings = [_remediable_finding(escalate_remediation=True)]
        state = {
            "device_hostname": "r1",
            "device_platform": "iosxe",
            "normalised_data": {},
            "findings": pre_escalation_findings,
            "anomalies_detected": [],
            "errors": [],
        }

        out = await escalation.escalation_node(state)

        # Falls back to the pre-escalation findings rather than guessing —
        # never invents new ones from an unusable response.
        assert out["findings"] == pre_escalation_findings
        assert out["recommendations"] == []
        assert out["escalate_to_opus"] is False
        assert out["processing_stage"] == "complete"
        assert len(out["errors"]) == 1
        assert "Escalation agent" in out["errors"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", [TRUNCATED_RESULT, PARSE_ERROR_RESULT])
class TestEscalationRemediationNodeRefusesUnusableResult:
    async def test_zero_recommendations_and_error_recorded_no_standard_findings(
        self, monkeypatch, bad_result
    ):
        _patch_message(monkeypatch, bad_result)
        state = {
            "device_hostname": "r1",
            "device_platform": "iosxe",
            "findings": [_remediable_finding(escalate_remediation=True)],
            "errors": [],
        }

        out = await escalation_remediation.escalation_remediation_node(state)

        assert out["recommendations"] == []
        assert out["processing_stage"] == "complete"  # no standard findings left to route onward
        assert len(out["errors"]) == 1
        assert "Escalation remediation agent" in out["errors"][0]

    async def test_standard_findings_still_route_onward_despite_opus_refusal(
        self, monkeypatch, bad_result
    ):
        """Even when Opus's response for the escalated findings is unusable,
        any remaining standard-tier findings must still be routed to the
        Sonnet remediation node rather than being dropped."""
        _patch_message(monkeypatch, bad_result)
        state = {
            "device_hostname": "r1",
            "device_platform": "iosxe",
            "findings": [
                _remediable_finding(escalate_remediation=True),
                _remediable_finding(escalate_remediation=False),
            ],
            "errors": [],
        }

        out = await escalation_remediation.escalation_remediation_node(state)

        assert out["recommendations"] == []
        assert out["processing_stage"] == "remediation"
        assert len(out["errors"]) == 1
