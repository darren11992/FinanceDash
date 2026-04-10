"""
Scheduled jobs — APScheduler configuration for periodic tasks.

Jobs:
- Sync: runs every 4 hours, fetches data for all active bank connections.
- Consent checker: runs daily at 09:00 UTC, detects expiring/expired consent.

The scheduler is initialised and started during the FastAPI lifespan
(startup), and shut down cleanly on application exit.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from supabase import Client

from app.jobs.consent_checker import check_consent_expiry
from app.services.sync_engine import sync_all_active_connections
from app.services.truelayer import TrueLayerClient

logger = logging.getLogger(__name__)

# How often the scheduled sync runs (in hours).
SYNC_INTERVAL_HOURS = 4

# APScheduler max_instances prevents overlapping runs of the same job.
# With max_instances=1, if a run hasn't finished by the time the next
# trigger fires, the second run is skipped rather than queued.
MAX_INSTANCES = 1

# Module-level scheduler instance — created once, started/stopped by lifespan.
_scheduler: AsyncIOScheduler | None = None


async def _run_scheduled_sync(db: Client, truelayer_client: TrueLayerClient) -> None:
    """
    Job function invoked by APScheduler every SYNC_INTERVAL_HOURS.

    Fetches fresh data for all active bank connections. Errors are
    handled per-connection inside sync_all_active_connections — this
    function should never raise.
    """
    logger.info("Scheduled sync starting")
    try:
        results = await sync_all_active_connections(db, truelayer_client)
        ok_count = sum(1 for r in results if r.get("status") == "ok")
        err_count = sum(1 for r in results if r.get("status") == "error")
        skip_count = sum(1 for r in results if r.get("status") == "skipped")
        logger.info(
            "Scheduled sync complete: %d ok, %d errors, %d skipped (of %d total)",
            ok_count, err_count, skip_count, len(results),
        )
    except Exception:  # noqa: BLE001 — intentionally broad: scheduler top-level guard
        # Catch-all so the scheduler doesn't remove the job on unhandled exception.
        logger.exception("Scheduled sync failed unexpectedly")


async def _run_consent_checker(db: Client) -> None:
    """
    Job function invoked by APScheduler daily at 09:00 UTC.

    Scans for expiring/expired consent and updates connection statuses.
    Errors are handled inside check_consent_expiry — this function
    should never raise.
    """
    logger.info("Consent checker job starting")
    try:
        summary = await check_consent_expiry(db)
        logger.info(
            "Consent checker job complete: %d expiring_soon, %d expired, %d errors",
            summary.get("expiring_soon", 0),
            summary.get("expired", 0),
            summary.get("errors", 0),
        )
    except Exception:  # noqa: BLE001 — intentionally broad: scheduler top-level guard
        logger.exception("Consent checker job failed unexpectedly")


def start_scheduler(db: Client, truelayer_client: TrueLayerClient) -> AsyncIOScheduler:
    """
    Create and start the APScheduler instance.

    Call this during FastAPI lifespan startup. The scheduler runs in the
    same asyncio event loop as FastAPI.

    Args:
        db: Supabase client (service_role) for database access.
        truelayer_client: TrueLayer API client instance.

    Returns:
        The running scheduler instance (caller should store it for shutdown).
    """
    global _scheduler

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _run_scheduled_sync,
        trigger=IntervalTrigger(hours=SYNC_INTERVAL_HOURS),
        id="scheduled_sync",
        name="Sync all active bank connections",
        max_instances=MAX_INSTANCES,
        kwargs={"db": db, "truelayer_client": truelayer_client},
        # Don't run immediately on startup — let the app settle first.
        # The first run will be SYNC_INTERVAL_HOURS after startup.
        # Users can trigger a manual sync via POST /api/v1/sync at any time.
    )

    # Consent checker: daily at 09:00 UTC.
    # Detects connections with expiring/expired Open Banking consent
    # and updates their status (expiring_soon / expired).
    scheduler.add_job(
        _run_consent_checker,
        trigger=CronTrigger(hour=9, minute=0, timezone="UTC"),
        id="consent_checker",
        name="Check consent expiry for all connections",
        max_instances=MAX_INSTANCES,
        kwargs={"db": db},
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started: sync (every %d hours) + consent checker (daily 09:00 UTC)", SYNC_INTERVAL_HOURS)

    return scheduler


def stop_scheduler() -> None:
    """
    Shut down the scheduler gracefully.

    Call this during FastAPI lifespan shutdown. Waits for any running
    job to complete before returning.
    """
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=True)
        logger.info("Scheduled sync stopped")
        _scheduler = None
