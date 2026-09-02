"""Regression coverage for rollback-on-failed-apply.

Kopis pushes configuration to live network devices; when a config apply
fails partway through, ``_send_commands_sync`` / ``_run_rollback`` in
``services/execution_engine.py`` are the last line of defense against
leaving a device in an unknown, half-configured state. This was verified
ad hoc against a stubbed pyATS device before any permanent test existed —
this file locks down that matrix:

  - apply fails, rollback SUCCEEDS
  - apply fails, rollback itself FAILS (must surface `rolled_back=False`
    with the manual-intervention reason, never swallowed)
  - no rollback commands present
  - auto-rollback disabled via the `AUTO_ROLLBACK` setting

No real device, network, or pyATS/genie install is required or touched:
``genie.testbed`` is injected into ``sys.modules`` as a fake module whose
``load()`` returns a stub testbed exposing one fake device object we
fully control (``.connect`` / ``.execute`` / ``.configure`` /
``.disconnect``), and ``services.testbed_generator.generate_testbed`` is
monkeypatched to a no-op stub. None of this touches the database, so this
whole file runs standalone (no Postgres needed).
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import settings
from services import execution_engine


def _make_device(hostname: str = "test-router") -> SimpleNamespace:
    return SimpleNamespace(
        id="dev-1",
        hostname=hostname,
        management_ip="10.0.0.1",
        platform="iosxe",
        device_type="router",
    )


@pytest.fixture
def fake_tb_device():
    """A fully-controllable stand-in for a pyATS `testbed.devices[...]`
    connected device object.
    """
    return Mock(name="fake_tb_device")


@pytest.fixture(autouse=True)
def fake_pyats(monkeypatch, fake_tb_device):
    """Make `from genie.testbed import load as load_testbed` (inside
    `_send_commands_sync`) resolve to a fake `load()` that hands back a
    stub testbed wrapping `fake_tb_device`, regardless of whether the real
    pyats/genie package is installed in this environment.
    """
    fake_testbed = Mock(name="fake_testbed")
    fake_testbed.devices = Mock()
    fake_testbed.devices.get = Mock(return_value=fake_tb_device)
    load_mock = Mock(return_value=fake_testbed)

    genie_mod = sys.modules.get("genie") or types.ModuleType("genie")
    testbed_mod = types.ModuleType("genie.testbed")
    testbed_mod.load = load_mock
    genie_mod.testbed = testbed_mod

    monkeypatch.setitem(sys.modules, "genie", genie_mod)
    monkeypatch.setitem(sys.modules, "genie.testbed", testbed_mod)

    monkeypatch.setattr(
        "services.testbed_generator.generate_testbed",
        Mock(return_value={"testbed": {"name": "fake"}, "devices": {}}),
    )
    monkeypatch.setattr(settings, "auto_rollback", True)
    return load_mock


APPLY_COMMANDS = ["configure terminal", "interface GigabitEthernet0/1", "shutdown", "end"]
ROLLBACK_COMMANDS = ["configure terminal", "interface GigabitEthernet0/1", "no shutdown", "end"]


# ── _run_rollback() — direct unit coverage ──────────────────────────────


class TestRunRollbackDirect:
    def test_rollback_success_returns_true_and_no_error(self, fake_tb_device):
        fake_tb_device.configure = Mock(return_value="Configuration applied.\n")
        outputs, success, error = execution_engine._run_rollback(
            fake_tb_device, ["interface GigabitEthernet0/1", "no shutdown"]
        )
        assert success is True
        assert error is None
        assert len(outputs) == 1
        assert outputs[0]["success"] is True
        fake_tb_device.configure.assert_called_once()

    def test_rollback_failure_returns_false_and_error_message(self, fake_tb_device):
        fake_tb_device.configure = Mock(side_effect=Exception("rollback rejected by device"))
        outputs, success, error = execution_engine._run_rollback(
            fake_tb_device, ["interface GigabitEthernet0/1", "no shutdown"]
        )
        assert success is False
        assert error == "rollback rejected by device"
        assert len(outputs) == 1
        assert outputs[0]["success"] is False


# ── _send_commands_sync() — full apply+rollback matrix ──────────────────


class TestSendCommandsSyncRollbackMatrix:
    def test_apply_fails_rollback_succeeds(self, fake_tb_device):
        fake_tb_device.configure = Mock(
            side_effect=[Exception("interface config rejected"), "Configuration applied.\n"]
        )

        result = execution_engine._send_commands_sync(
            _make_device(), APPLY_COMMANDS, ROLLBACK_COMMANDS
        )

        assert result["success"] is False
        assert result["error"] == "One or more commands failed"
        assert result["rolled_back"] is True
        assert "executed successfully" in result["rollback_reason"]
        assert len(result["rollback_outputs"]) == 1
        assert result["rollback_outputs"][0]["success"] is True
        assert fake_tb_device.configure.call_count == 2
        fake_tb_device.disconnect.assert_called_once()

    def test_apply_fails_rollback_also_fails_not_swallowed(self, fake_tb_device):
        fake_tb_device.configure = Mock(
            side_effect=[Exception("interface config rejected"), Exception("rollback also rejected")]
        )

        result = execution_engine._send_commands_sync(
            _make_device(), APPLY_COMMANDS, ROLLBACK_COMMANDS
        )

        # The overall failure must never be masked by a partially-successful
        # rollback attempt.
        assert result["success"] is False
        assert result["error"] == "One or more commands failed"
        assert result["rolled_back"] is False
        assert "MANUAL INTERVENTION REQUIRED NOW" in result["rollback_reason"]
        assert "rollback also rejected" in result["rollback_reason"]
        assert len(result["rollback_outputs"]) == 1
        assert result["rollback_outputs"][0]["success"] is False
        assert fake_tb_device.configure.call_count == 2

    def test_apply_fails_no_rollback_commands(self, fake_tb_device):
        fake_tb_device.configure = Mock(side_effect=Exception("interface config rejected"))

        result = execution_engine._send_commands_sync(_make_device(), APPLY_COMMANDS, [])

        assert result["success"] is False
        assert result["rolled_back"] is False
        assert result["rollback_outputs"] == []
        assert "no rollback commands were available" in result["rollback_reason"]
        # Only the forward apply attempt — never even tries a rollback call.
        assert fake_tb_device.configure.call_count == 1

    def test_apply_fails_auto_rollback_disabled(self, fake_tb_device, monkeypatch):
        monkeypatch.setattr(settings, "auto_rollback", False)
        fake_tb_device.configure = Mock(side_effect=Exception("interface config rejected"))

        result = execution_engine._send_commands_sync(
            _make_device(), APPLY_COMMANDS, ROLLBACK_COMMANDS
        )

        assert result["success"] is False
        assert result["rolled_back"] is False
        assert result["rollback_outputs"] == []
        assert "AUTO_ROLLBACK is disabled" in result["rollback_reason"]
        # Rollback commands existed but must NOT have been sent to the device.
        assert fake_tb_device.configure.call_count == 1

    def test_apply_succeeds_no_rollback_attempted(self, fake_tb_device):
        """Sanity check: a successful apply never touches rollback at all."""
        fake_tb_device.configure = Mock(return_value="Configuration applied.\n")

        result = execution_engine._send_commands_sync(
            _make_device(), APPLY_COMMANDS, ROLLBACK_COMMANDS
        )

        assert result["success"] is True
        assert "error" not in result
        assert result["rolled_back"] is False
        assert result["rollback_reason"] is None
        assert result["rollback_outputs"] == []
        assert fake_tb_device.configure.call_count == 1
