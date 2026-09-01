"""Shared FastAPI dependencies — auth."""

import secrets

import structlog
from fastapi import Header, HTTPException

from config import settings

log = structlog.get_logger()

_warned_missing_token = False


def _warn_missing_token_once():
    """Log loudly (once) that no API_AUTH_TOKEN is configured.

    Kopis pushes configuration to live network devices, so an unset
    token must never be treated as "auth disabled" — every request is
    rejected instead (see require_auth). This just makes the
    misconfiguration loud and easy to spot in startup/request logs.
    """
    global _warned_missing_token
    if not _warned_missing_token:
        log.error(
            "api_auth_token_not_configured",
            message=(
                "API_AUTH_TOKEN is not set. ALL authenticated requests will be "
                "rejected with 401 until it is configured. This is fail-closed "
                "by design — do not add a bypass for this."
            ),
        )
        _warned_missing_token = True


async def require_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """Require a valid API credential on the request.

    Accepts either an ``Authorization: Bearer <token>`` header or an
    ``X-API-Key: <token>`` header. Compares against
    ``settings.api_auth_token`` using a constant-time comparison.

    Fails CLOSED: if no token is configured server-side, every request
    is rejected (401) rather than silently allowed through — an unset
    token is a misconfiguration, never an "auth disabled" signal.

    Returns a verified identity string that callers should use in
    place of any client-supplied identity (e.g. approved_by).
    """
    configured_token = settings.api_auth_token
    if not configured_token:
        _warn_missing_token_once()
        raise HTTPException(status_code=401, detail="API authentication is not configured")

    supplied_token: str | None = None
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            supplied_token = value
    if not supplied_token and x_api_key:
        supplied_token = x_api_key

    if not supplied_token or not secrets.compare_digest(supplied_token, configured_token):
        raise HTTPException(status_code=401, detail="Missing or invalid API credential")

    # Single shared-token model for this iteration (see issue #7/#9) — the
    # identity is a fixed label for the service credential, not a per-user
    # principal. This is what approved_by / audit trails should record.
    return "operator"
