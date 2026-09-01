"""Slack request signature verification.

Kopis pushes configuration changes to live network devices once a
recommendation is approved. The Slack Approve/Deny buttons (see
``api/routes/slack.py``) are a direct path to that ``approve()`` call, so
this verifier is the only thing standing between "someone on the internet
POSTs to /api/v1/slack/actions" and "a config change gets pushed to a
router". Get this wrong and the approval workflow is decorative.

Implements Slack's documented request-signing scheme:
https://api.slack.com/authentication/verifying-requests-from-slack

    base_string = "v0:{timestamp}:{raw_body}"
    signature   = "v0=" + hex(HMAC-SHA256(signing_secret, base_string))

Security properties this module guarantees:
- Comparison is constant-time (``hmac.compare_digest``), never ``==``.
- Stale timestamps (outside a 5 minute window) are rejected to stop replay
  of a captured, still-validly-signed request.
- **Fails closed**: if ``SLACK_SIGNING_SECRET`` is not configured, every
  request is rejected. An unset secret must never be treated as
  "verification disabled" — that would turn a misconfiguration into an
  open approval endpoint for live network changes.
- Verification MUST run against the exact raw request bytes Slack signed.
  Callers must read the raw body before any framework form/JSON parsing —
  parsing and re-serialising would change the byte string and every
  signature would (correctly) fail to match.
"""

import hmac
import time
from hashlib import sha256

from config import settings

# Slack's own guidance: reject anything outside a 5 minute window.
_MAX_TIMESTAMP_SKEW_SECONDS = 5 * 60


def verify_slack_signature(
    raw_body: bytes,
    timestamp: str | None,
    signature: str | None,
    *,
    now: float | None = None,
) -> bool:
    """Verify a Slack interactivity request.

    Args:
        raw_body: the exact, unparsed request body bytes as received.
        timestamp: the ``X-Slack-Request-Timestamp`` header value.
        signature: the ``X-Slack-Signature`` header value (``v0=...``).
        now: injectable current time (epoch seconds) for testing.

    Returns:
        True only if the secret is configured, the timestamp is fresh,
        and the signature matches. False in every other case — this
        function fails closed by design.
    """
    secret = settings.slack_signing_secret
    if not secret:
        # No secret configured => cannot verify => reject everything.
        # Do NOT change this to `return True`; a missing secret is not
        # "verification disabled", it is "verification impossible".
        return False

    if not timestamp or not signature:
        return False

    try:
        request_ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    current_ts = time.time() if now is None else now
    if abs(current_ts - request_ts) > _MAX_TIMESTAMP_SKEW_SECONDS:
        return False

    if not signature.startswith("v0="):
        return False

    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    digest = hmac.new(secret.encode("utf-8"), base, sha256).hexdigest()
    computed_signature = "v0=" + digest

    return hmac.compare_digest(computed_signature, signature)
