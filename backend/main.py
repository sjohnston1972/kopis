"""Kopis — FastAPI application entry point."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from api.routes import approvals, chat, dashboard, devices, execution, findings, health, pipeline, snapshots, topology
from db.postgres import engine

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("kopis_starting")
    await _reset_stale_snapshot_status()
    yield
    await engine.dispose()
    log.info("kopis_shutdown")


app = FastAPI(
    title="Kopis",
    description="AI-augmented network operations platform",
    version="0.1.0",
    lifespan=lifespan,
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
