"""Kopis — FastAPI application entry point."""

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    """Mark any 'approved' (executing) approvals as failed on startup.

    If the container restarted while an execution was in-flight, the
    asyncio.create_task was lost.  These approvals would otherwise be
    stuck in 'approved' forever.
    """
    from db.postgres import async_session
    from db.tables import Approval
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(
            select(Approval).where(Approval.status == "approved")
        )
        stuck = result.scalars().all()
        for a in stuck:
            a.status = "failed"
            a.execution_result = {"error": "Execution lost — container restarted before completion"}
            log.warning("orphaned_approval_reset", approval_id=a.id)
        if stuck:
            await db.commit()
            log.info("orphaned_approvals_fixed", count=len(stuck))


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

app.include_router(health.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(devices.router, prefix="/api/v1")
app.include_router(snapshots.router, prefix="/api/v1")
app.include_router(findings.router, prefix="/api/v1")
app.include_router(approvals.router, prefix="/api/v1")
app.include_router(topology.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(pipeline.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(schedules.router, prefix="/api/v1")
app.include_router(slack.router, prefix="/api/v1")
