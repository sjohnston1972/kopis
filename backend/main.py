"""Kopis — FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import require_auth
from api.routes import approvals, chat, dashboard, devices, execution, findings, health, pipeline, schedules, slack, snapshots, topology
from config import settings
from db.postgres import engine
from services import scheduler

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()


async def _reset_stale_snapshot_status():
    """Clear any 'running' snapshot status left over from a previous process."""
    from db.postgres import async_session
    from db.tables import Setting
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(select(Setting).where(Setting.key == "snapshot_status"))
        row = result.scalar_one_or_none()
        if row and row.value.get("running"):
            log.warning("snapshot_status_reset_on_startup")
            row.value = {
                "running": False,
                "result": "error",
                "error": "Process restarted while snapshot was running",
            }
            await db.commit()


async def _reset_orphaned_approvals():
    """Mark any 'executing' (in-flight) approvals as failed on startup.

    If the container restarted while an execution was in-flight, the
    asyncio.create_task was lost. See
    services.approval_service.reset_orphaned_executing for the full
    rationale (including why 'approved' rows are deliberately left alone).
    """
    from db.postgres import async_session
    from services import approval_service

    async with async_session() as db:
        count = await approval_service.reset_orphaned_executing(db)
        if count:
            log.info("startup_orphan_reset", count=count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("kopis_starting")
    if not settings.api_auth_token:
        # Fail-CLOSED by design: an unset token means every non-health
        # request will be rejected with 401 (see api/deps.py::require_auth),
        # never treated as "auth disabled". This log exists so the
        # misconfiguration is impossible to miss on startup.
        log.error(
            "api_auth_token_not_configured",
            message="API_AUTH_TOKEN is not set — all authenticated endpoints will reject every request until it is configured.",
        )
    await _reset_stale_snapshot_status()
    await _reset_orphaned_approvals()
    # Refresh inventory immediately on startup so devices have fresh
    # last_seen/last_refreshed timestamps the moment the API comes up.
    # Don't rely on the scheduler's first fire — if APScheduler has any
    # hiccup, we'd otherwise stay stale until someone clicks refresh.
    await scheduler.refresh_inventory_now()
    scheduler.start()
    await scheduler.load_persistent_schedules()
    yield
    scheduler.shutdown()
    await engine.dispose()
    log.info("kopis_shutdown")


app = FastAPI(
    title="Kopis",
    description="AI-augmented network operations platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# `health` is the only router left unauthenticated — it's what the frontend
# (and Docker healthchecks) poll pre-login, and it exposes no network state
# or control surface. Every other router pushes or reveals live network
# data / control, so require_auth is applied to all of them at the
# router level (i.e. every method on every route in that router).
#
# NOTE for the Slack integration work (#13-#15): do not add
# `Depends(require_auth)` to a future `/slack/*` router — Slack requests
# are authenticated by Slack request-signature verification instead, not
# this bearer/X-API-Key token.
_auth_dep = [Depends(require_auth)]

app.include_router(dashboard.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(devices.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(snapshots.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(findings.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(approvals.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(topology.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(chat.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(pipeline.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(execution.router, prefix="/api/v1", dependencies=_auth_dep)
app.include_router(schedules.router, prefix="/api/v1", dependencies=_auth_dep)
# NOTE: slack router intentionally NOT protected by require_auth — Slack
# requests are authenticated by Slack request-signature verification
# instead (see #13-#15).
app.include_router(slack.router, prefix="/api/v1")
