"""
APScheduler integration for SecureStats.

Jobs
────
daily_etl    — runs run_daily_etl() every day at 06:00 America/New_York
               (most MLB games finish by ~2 AM ET the night before).

live_update  — runs run_live_update() every 15 minutes; the job itself
               checks whether the current ET time falls inside game hours
               (12:00 PM – 01:00 AM) and exits early if not.

Both jobs are registered at startup via start_scheduler() and cancelled
cleanly via stop_scheduler(), called from FastAPI's lifespan context.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.etl import run_daily_etl, run_live_update

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# ── Singleton scheduler ───────────────────────────────────────────────────────
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=ET)
    return _scheduler


# ── Game-hours guard ──────────────────────────────────────────────────────────


def _is_game_hours() -> bool:
    """
    Return True if current Eastern Time is within typical MLB game hours.
    Window: 12:00 PM – 01:00 AM ET  (hour 12-23 or hour 0).
    """
    hour = datetime.now(ET).hour
    return hour >= 12 or hour == 0


# ── Job callables ─────────────────────────────────────────────────────────────


async def _daily_etl_job() -> None:
    logger.info("Scheduler: daily ETL job fired")
    try:
        result = await run_daily_etl()
        logger.info("Scheduler: daily ETL finished — %s", result.summary())
    except Exception:
        logger.exception("Scheduler: daily ETL job raised an unhandled exception")


async def _live_update_job() -> None:
    if not _is_game_hours():
        logger.debug("Scheduler: live-update skipped (outside game hours)")
        return
    logger.info("Scheduler: live-update job fired")
    try:
        result = await run_live_update()
        logger.info("Scheduler: live-update finished — %s", result.summary())
    except Exception:
        logger.exception("Scheduler: live-update job raised an unhandled exception")


# ── Public start / stop ───────────────────────────────────────────────────────


def start_scheduler() -> AsyncIOScheduler:
    """
    Register all jobs and start the scheduler.
    Called from FastAPI's lifespan startup.
    """
    scheduler = get_scheduler()

    # ── Daily full ETL — 06:00 ET ─────────────────────────────────────────────
    scheduler.add_job(
        _daily_etl_job,
        CronTrigger(hour=6, minute=0, timezone=ET),
        id="daily_etl",
        name="Daily MLB ETL",
        replace_existing=True,
        misfire_grace_time=3_600,   # tolerate up to 1-hr startup delay
    )

    # ── Live update — every 15 min (game-hours gate is inside the callable) ───
    scheduler.add_job(
        _live_update_job,
        IntervalTrigger(minutes=15),
        id="live_update",
        name="Live Game Update",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — daily ETL @ 06:00 ET, live update every 15 min"
    )
    return scheduler


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Called from FastAPI lifespan shutdown."""
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
