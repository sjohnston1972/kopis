"""Regression coverage for Slack request-signature verification.

Kopis pushes configuration changes to live network devices once a
recommendation is approved, and the Slack Approve/Deny buttons are a
direct path to that ``approve()`` call (see ``integrations/slack_verify.py``
module docstring). Signature verification is the ONLY thing standing
between "someone on the internet POSTs to /slack/actions" and "a config
change gets pushed to a router" — this file locks down the full matrix
that was previously verified only ad hoc:

  - correctly-signed request is ACCEPTED
  - REJECTED: tampered body, tampered signature, stale timestamp,
    missing signature header, missing timestamp header, wrong secret,
    and an unset signing secret (fail-closed, not "verification
    disabled")

Two layers are covered:
  1. ``verify_slack_signature()`` directly (unit level, no HTTP/DB).
  2. A real HTTP round-trip through ``api.routes.slack.router`` via
     FastAPI's TestClient, so the wiring between the endpoint and the
     verifier (raw-body handling, header extraction, 401 on failure)
     is exercised too — not just the helper in isolation.

Postgres requirement
---------------------
The pure signature-matrix tests (unit + HTTP-reject-path) never touch the
database — verification fails before ``api/routes/slack.py`` opens a
session. Only the two "signature accepted" HTTP tests reach the
approval_service DB calls and need the real Postgres described in
conftest.py's module docstring.
"""

import hmac
import json
import time
import urllib.parse
from hashlib import sha256

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings
from integrations.slack_verify import verify_slack_signature

SIGNING_SECRET = "test-signing-secret-123"


def _sign(secret: str, timestamp: str, raw_body: bytes) -> str:
    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    digest = hmac.new(secret.encode("utf-8"), base, sha256).hexdigest()
    return "v0=" + digest


@pytest.fixture(autouse=True)
def _configured_secret(monkeypatch):
    """Every test in this module gets a known signing secret configured
    unless it explicitly overrides it (e.g. the unset-secret case).
    """
    monkeypatch.setattr(settings, "slack_signing_secret", SIGNING_SECRET)


# ── verify_slack_signature() — direct unit coverage ─────────────────────


class TestVerifySlackSignatureHelper:
    def test_correctly_signed_is_accepted(self):
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        sig = _sign(SIGNING_SECRET, ts, body)
        assert verify_slack_signature(body, ts, sig) is True

    def test_tampered_body_is_rejected(self):
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        sig = _sign(SIGNING_SECRET, ts, body)
        tampered_body = b'{"hello": "world!"}'
        assert verify_slack_signature(tampered_body, ts, sig) is False

    def test_tampered_signature_is_rejected(self):
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        sig = _sign(SIGNING_SECRET, ts, body)
        # Flip the last hex character of the digest.
        last = sig[-1]
        flipped = "0" if last != "0" else "1"
        tampered_sig = sig[:-1] + flipped
        assert verify_slack_signature(body, ts, tampered_sig) is False

    def test_stale_timestamp_is_rejected(self):
        body = b'{"hello": "world"}'
        # 6 minutes old — outside the 5 minute window.
        stale_ts = str(int(time.time()) - 6 * 60)
        sig = _sign(SIGNING_SECRET, stale_ts, body)
        assert verify_slack_signature(body, stale_ts, sig) is False

    def test_future_timestamp_outside_window_is_rejected(self):
        """Skew is checked with abs() — a clock far in the future must
        also be rejected, not just a stale one."""
        body = b'{"hello": "world"}'
        future_ts = str(int(time.time()) + 6 * 60)
        sig = _sign(SIGNING_SECRET, future_ts, body)
        assert verify_slack_signature(body, future_ts, sig) is False

    def test_missing_signature_header_is_rejected(self):
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        assert verify_slack_signature(body, ts, None) is False

    def test_missing_timestamp_header_is_rejected(self):
        body = b'{"hello": "world"}'
        sig = _sign(SIGNING_SECRET, str(int(time.time())), body)
        assert verify_slack_signature(body, None, sig) is False

    def test_wrong_secret_is_rejected(self):
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        sig = _sign("not-the-configured-secret", ts, body)
        assert verify_slack_signature(body, ts, sig) is False

    def test_unset_signing_secret_fails_closed(self, monkeypatch):
        """An unset SLACK_SIGNING_SECRET must reject EVERY request — even
        one signed with what would otherwise be a perfectly valid
        signature under some secret — never treat it as 'skip
        verification'.
        """
        monkeypatch.setattr(settings, "slack_signing_secret", "")
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        # Sign with a secret that would be "the real one" in production —
        # doesn't matter, an unset secret must reject regardless.
        sig = _sign("some-secret-that-would-otherwise-be-valid", ts, body)
        assert verify_slack_signature(body, ts, sig) is False

    def test_non_v0_prefixed_signature_is_rejected(self):
        """Guards the format check itself, not just the HMAC comparison."""
        body = b'{"hello": "world"}'
        ts = str(int(time.time()))
        assert verify_slack_signature(body, ts, "v1=deadbeef") is False

    def test_non_numeric_timestamp_is_rejected(self):
        body = b'{"hello": "world"}'
        sig = _sign(SIGNING_SECRET, "not-a-number", body)
        assert verify_slack_signature(body, "not-a-number", sig) is False


# ── HTTP round-trip through the real router ─────────────────────────────


@pytest.fixture
def slack_app():
    """Mount ONLY the real slack router (no lifespan/scheduler/other
    routers) so TestClient exercises the actual endpoint wiring —
    raw-body reading, header extraction, verify -> 401 — without pulling
    in unrelated startup machinery.
    """
    import api.routes.slack as slack_route_module

    app = FastAPI()
    app.include_router(slack_route_module.router)
    return app


@pytest.fixture
def client(slack_app):
    return TestClient(slack_app)


def _build_signed_request(secret: str, action_id: str, approval_id: str, *, ts: str | None = None):
    """Build (raw_body, headers) for a Slack block_actions payload signed
    with `secret`, ready to POST to /slack/actions.
    """
    payload = {
        "actions": [{"action_id": action_id, "value": approval_id}],
        "user": {"username": "alice"},
    }
    raw_body = ("payload=" + urllib.parse.quote(json.dumps(payload))).encode("utf-8")
    timestamp = ts or str(int(time.time()))
    signature = _sign(secret, timestamp, raw_body)
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }
    return raw_body, headers


class TestSlackActionsEndpointRejectsBadSignatures:
    """None of these reach the database — verification fails first."""

    def test_tampered_body_rejected_401(self, client):
        raw_body, headers = _build_signed_request(SIGNING_SECRET, "deny_remediation", "some-id")
        tampered = raw_body + b"&extra=1"
        resp = client.post("/slack/actions", content=tampered, headers=headers)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid Slack signature"

    def test_tampered_signature_rejected_401(self, client):
        raw_body, headers = _build_signed_request(SIGNING_SECRET, "deny_remediation", "some-id")
        sig = headers["X-Slack-Signature"]
        headers["X-Slack-Signature"] = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 401

    def test_stale_timestamp_rejected_401(self, client):
        stale_ts = str(int(time.time()) - 10 * 60)
        raw_body, headers = _build_signed_request(
            SIGNING_SECRET, "deny_remediation", "some-id", ts=stale_ts
        )
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 401

    def test_missing_signature_header_rejected_401(self, client):
        raw_body, headers = _build_signed_request(SIGNING_SECRET, "deny_remediation", "some-id")
        del headers["X-Slack-Signature"]
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 401

    def test_missing_timestamp_header_rejected_401(self, client):
        raw_body, headers = _build_signed_request(SIGNING_SECRET, "deny_remediation", "some-id")
        del headers["X-Slack-Request-Timestamp"]
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 401

    def test_wrong_secret_rejected_401(self, client):
        raw_body, headers = _build_signed_request("some-other-secret", "deny_remediation", "some-id")
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 401

    def test_unset_signing_secret_rejected_401(self, client, monkeypatch):
        """Fail-closed at the HTTP layer too: an unset secret must reject
        even a request signed with what would elsewhere be treated as
        the correct secret.
        """
        monkeypatch.setattr(settings, "slack_signing_secret", "")
        raw_body, headers = _build_signed_request(SIGNING_SECRET, "deny_remediation", "some-id")
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestSlackActionsEndpointAcceptsGoodSignature:
    """These reach approval_service and need the real Postgres from
    conftest.py — a correctly-signed request must be let through to the
    business logic rather than rejected.
    """

    @pytest.fixture(autouse=True)
    async def _dispose_app_engine_between_tests(self):
        """The slack route uses the app's own global `db.postgres.engine`
        (a module-level singleton, unrelated to the per-test `engine`
        fixture in conftest.py). TestClient drives each request through
        its own event loop/thread; if that global engine's connection
        pool holds onto an asyncpg connection opened on a PRIOR test's
        (now-closed) loop, the next TestClient call that reuses the pool
        breaks with an unrelated-looking AttributeError deep in asyncio's
        proactor transport. Disposing the pool before each test forces a
        fresh connection bound to the current call's loop — this is a
        test-isolation concern about a shared global engine across
        TestClient instances, not something app code needs to handle (a
        real server opens this engine exactly once, on one persistent
        event loop, for its whole process lifetime).
        """
        from db.postgres import engine as app_engine

        await app_engine.dispose()
        yield
        await app_engine.dispose()

    async def test_correctly_signed_unknown_approval_is_accepted_not_401(self, client):
        # No make_approval fixture used deliberately — the point here is
        # only to prove verification let the request PAST the signature
        # gate (a 401 vs. a non-401 status), still against the real DB
        # (approval_service.deny() runs one UPDATE that matches no row).
        raw_body, headers = _build_signed_request(
            SIGNING_SECRET, "deny_remediation", "00000000-0000-0000-0000-000000000000"
        )
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 200
        assert "was not found" in resp.json()["text"]

    async def test_correctly_signed_deny_transitions_real_approval(self, client, make_approval):
        """Full accepted path against a real pending approval: signature
        verified, deny() actually flips the row in Postgres — confirmed via
        the endpoint's own response, which only reports the "denied" outcome
        text when approval_service.deny() found and transitioned the row
        (a not-found/already-actioned approval gets a distinctly different
        "was not found, or is no longer pending" message instead — see
        api/routes/slack.py).

        Deliberately does NOT reopen a DB session after the TestClient call
        in this test to read the row back: TestClient drives the ASGI app
        through its own event loop, and on this Windows/asyncpg/ProactorEventLoop
        combination, awaiting a DB query on the outer test's event loop
        immediately after a TestClient call corrupts that loop's proactor
        transport (AttributeError: 'NoneType' object has no attribute
        'send') — an environment-specific interaction, not a bug in the
        code under test. The response-text assertion below still requires
        the real Postgres UPDATE to have actually matched and transitioned
        the row, since that's what determines which text the endpoint
        returns.
        """
        approval_id = await make_approval(status="pending")
        raw_body, headers = _build_signed_request(SIGNING_SECRET, "deny_remediation", approval_id)
        resp = client.post("/slack/actions", content=raw_body, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert f"`{approval_id}` denied by alice" in body["text"]
        assert "was not found" not in body["text"]
