"""
Tests for the scheduled jobs (APScheduler integration).

Covers:
- start_scheduler: creates scheduler, adds sync + consent checker jobs, starts it
- stop_scheduler: shuts down cleanly, clears module-level reference
- _run_scheduled_sync: delegates to sync_all_active_connections, logs results
- _run_consent_checker: delegates to check_consent_expiry, logs results
- Error handling (catch-all never raises)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.jobs.scheduled_sync import (
    SYNC_INTERVAL_HOURS,
    _run_consent_checker,
    _run_scheduled_sync,
    start_scheduler,
    stop_scheduler,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_truelayer_client():
    return MagicMock()


# ---------------------------------------------------------------------------
# start_scheduler
# ---------------------------------------------------------------------------


class TestStartScheduler:

    @patch("app.jobs.scheduled_sync.AsyncIOScheduler")
    def test_creates_and_starts_scheduler(self, MockScheduler, mock_db, mock_truelayer_client):
        """start_scheduler should create an AsyncIOScheduler, add two jobs, and start it."""
        scheduler_instance = MockScheduler.return_value

        result = start_scheduler(mock_db, mock_truelayer_client)

        MockScheduler.assert_called_once()
        assert scheduler_instance.add_job.call_count == 2  # sync + consent checker
        scheduler_instance.start.assert_called_once()
        assert result is scheduler_instance

    @patch("app.jobs.scheduled_sync.AsyncIOScheduler")
    def test_sync_job_configured_correctly(self, MockScheduler, mock_db, mock_truelayer_client):
        """The sync job should have the correct ID, max_instances, and kwargs."""
        scheduler_instance = MockScheduler.return_value

        start_scheduler(mock_db, mock_truelayer_client)

        # First add_job call is the sync job
        sync_call = scheduler_instance.add_job.call_args_list[0]
        assert sync_call.kwargs["id"] == "scheduled_sync"
        assert sync_call.kwargs["max_instances"] == 1
        assert sync_call.kwargs["kwargs"]["db"] is mock_db
        assert sync_call.kwargs["kwargs"]["truelayer_client"] is mock_truelayer_client

    @patch("app.jobs.scheduled_sync.AsyncIOScheduler")
    def test_consent_checker_job_configured_correctly(self, MockScheduler, mock_db, mock_truelayer_client):
        """The consent checker job should have the correct ID and kwargs."""
        scheduler_instance = MockScheduler.return_value

        start_scheduler(mock_db, mock_truelayer_client)

        # Second add_job call is the consent checker
        consent_call = scheduler_instance.add_job.call_args_list[1]
        assert consent_call.kwargs["id"] == "consent_checker"
        assert consent_call.kwargs["max_instances"] == 1
        assert consent_call.kwargs["kwargs"]["db"] is mock_db
        # Consent checker doesn't need truelayer_client
        assert "truelayer_client" not in consent_call.kwargs["kwargs"]

    @patch("app.jobs.scheduled_sync.AsyncIOScheduler")
    def test_sync_interval_trigger_uses_configured_hours(self, MockScheduler, mock_db, mock_truelayer_client):
        """Sync IntervalTrigger should use SYNC_INTERVAL_HOURS."""
        scheduler_instance = MockScheduler.return_value

        start_scheduler(mock_db, mock_truelayer_client)

        sync_call = scheduler_instance.add_job.call_args_list[0]
        trigger = sync_call.kwargs["trigger"]
        # IntervalTrigger stores the interval as a timedelta.
        assert trigger.interval.total_seconds() == SYNC_INTERVAL_HOURS * 3600


# ---------------------------------------------------------------------------
# stop_scheduler
# ---------------------------------------------------------------------------


class TestStopScheduler:

    @patch("app.jobs.scheduled_sync._scheduler", None)
    def test_stop_with_no_scheduler_does_nothing(self):
        """stop_scheduler should be safe to call when no scheduler exists."""
        # Should not raise.
        stop_scheduler()

    @patch("app.jobs.scheduled_sync.AsyncIOScheduler")
    def test_stop_shuts_down_scheduler(self, MockScheduler, mock_db, mock_truelayer_client):
        """stop_scheduler should call shutdown(wait=True) and clear the reference."""
        import app.jobs.scheduled_sync as module

        scheduler_instance = MockScheduler.return_value
        start_scheduler(mock_db, mock_truelayer_client)
        assert module._scheduler is scheduler_instance

        stop_scheduler()

        scheduler_instance.shutdown.assert_called_once_with(wait=True)
        assert module._scheduler is None


# ---------------------------------------------------------------------------
# _run_scheduled_sync
# ---------------------------------------------------------------------------


class TestRunScheduledSync:

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.sync_all_active_connections", new_callable=AsyncMock)
    async def test_calls_sync_all_active_connections(self, mock_sync, mock_db, mock_truelayer_client):
        """_run_scheduled_sync should delegate to sync_all_active_connections."""
        mock_sync.return_value = [
            {"connection_id": "c1", "status": "ok"},
            {"connection_id": "c2", "status": "ok"},
        ]

        await _run_scheduled_sync(mock_db, mock_truelayer_client)

        mock_sync.assert_awaited_once_with(mock_db, mock_truelayer_client)

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.sync_all_active_connections", new_callable=AsyncMock)
    async def test_handles_mixed_results(self, mock_sync, mock_db, mock_truelayer_client):
        """Should handle results with mixed statuses without raising."""
        mock_sync.return_value = [
            {"connection_id": "c1", "status": "ok"},
            {"connection_id": "c2", "status": "error", "error": "token expired"},
            {"connection_id": "c3", "status": "skipped"},
        ]

        # Should not raise.
        await _run_scheduled_sync(mock_db, mock_truelayer_client)

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.sync_all_active_connections", new_callable=AsyncMock)
    async def test_handles_empty_results(self, mock_sync, mock_db, mock_truelayer_client):
        """Should handle case where there are no connections to sync."""
        mock_sync.return_value = []

        await _run_scheduled_sync(mock_db, mock_truelayer_client)

        mock_sync.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.sync_all_active_connections", new_callable=AsyncMock)
    async def test_catches_unexpected_exceptions(self, mock_sync, mock_db, mock_truelayer_client):
        """_run_scheduled_sync should never raise — catches all exceptions."""
        mock_sync.side_effect = RuntimeError("Database connection lost")

        # Should not raise despite the exception.
        await _run_scheduled_sync(mock_db, mock_truelayer_client)


# ---------------------------------------------------------------------------
# _run_consent_checker
# ---------------------------------------------------------------------------


class TestRunConsentChecker:

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.check_consent_expiry", new_callable=AsyncMock)
    async def test_calls_check_consent_expiry(self, mock_check, mock_db):
        """_run_consent_checker should delegate to check_consent_expiry."""
        mock_check.return_value = {"expiring_soon": 1, "expired": 0, "errors": 0}

        await _run_consent_checker(mock_db)

        mock_check.assert_awaited_once_with(mock_db)

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.check_consent_expiry", new_callable=AsyncMock)
    async def test_handles_summary_with_errors(self, mock_check, mock_db):
        """Should handle results with errors without raising."""
        mock_check.return_value = {"expiring_soon": 0, "expired": 2, "errors": 1}

        await _run_consent_checker(mock_db)

    @pytest.mark.asyncio
    @patch("app.jobs.scheduled_sync.check_consent_expiry", new_callable=AsyncMock)
    async def test_catches_unexpected_exceptions(self, mock_check, mock_db):
        """_run_consent_checker should never raise — catches all exceptions."""
        mock_check.side_effect = RuntimeError("Database connection lost")

        # Should not raise despite the exception.
        await _run_consent_checker(mock_db)
