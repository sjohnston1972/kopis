"""Background scheduler — periodic jobs (inventory refresh, etc.)."""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from db.postgres import async_session
from services import inventory, schedule_service

log = structlog.get_logger()

_scheduler: AsyncIOScheduler | None = None


async def _refresh_inventory_job() -> None:
    try:
        async with async_session() as db:
            devices = await inventory.refresh_inventory(db)
        log.info("scheduled_inventory_refresh_ok", count=len(devices))
    except Exception as exc:
        log.error("scheduled_inventory_refresh_failed", error=str(exc))


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _refresh_inventory_job,
        trigger=IntervalTrigger(minutes=settings.inventory_refresh_minutes),
        id="inventory_refresh",
        next_run_time=None,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    schedule_service.bind_scheduler(_scheduler)
    log.info("scheduler_started", inventory_refresh_minutes=settings.inventory_refresh_minutes)


async def load_persistent_schedules() -> None:
    """Re-register snapshot schedules from the DB after startup.

    Tolerates a missing ``snapshot_schedules`` table so the app can boot
    in environments where the migration hasn't been applied yet.
    """
    try:
        await schedule_service.reload_all_schedules()
    except Exception as exc:
        log.warning("schedule_load_skipped", error=str(exc))


def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    log.info("scheduler_stopped")
