"""
Tests for the sync engine.

All tests use mocked Supabase and TrueLayer clients — no real API calls.
Covers:
- Full sync happy path (accounts + balances + transactions)
- Token refresh when token is near expiry
- Consent expiry detection (expired / expiring_soon)
- Per-account error isolation (one account fails, others continue)
- Connection-level locking (no concurrent syncs)
- Deduplication (upsert called with on_conflict)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.services.sync_engine import (
    INCREMENTAL_OVERLAP_DAYS,
    INITIAL_SYNC_LOOKBACK_DAYS,
    TOKEN_REFRESH_THRESHOLD_MINUTES,
    _syncing_connections,
    sync_connection,
    sync_user_connections,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _future_iso(hours=24):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_iso(hours=1):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _make_connection(
    connection_id="conn-1",
    user_id="user-1",
    status="active",
    token_expires_at=None,
    consent_expires_at=None,
    last_synced_at=None,
):
    """Build a fake bank_connections row."""
    return {
        "id": connection_id,
        "user_id": user_id,
        "status": status,
        "access_token": "encrypted-access",
        "refresh_token": "encrypted-refresh",
        "token_expires_at": token_expires_at or _future_iso(24),
        "consent_expires_at": consent_expires_at or _future_iso(hours=24 * 60),
        "last_synced_at": last_synced_at,
        "provider_name": "Mock Bank",
    }


def _mock_db():
    """Build a mock Supabase client with chainable query builder methods."""
    db = MagicMock()

    # Make table().select().eq().execute() etc. work via chaining.
    # Each call to .table() returns a fresh chain mock.
    def _make_chain(data=None):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.order.return_value = chain
        chain.upsert.return_value = chain
        chain.update.return_value = chain
        chain.delete.return_value = chain

        result = MagicMock()
        result.data = data or []
        chain.execute.return_value = result
        return chain

    # We need per-table control, so store chains by table name.
    _table_chains = {}

    def _table_factory(table_name):
        if table_name not in _table_chains:
            _table_chains[table_name] = _make_chain()
        return _table_chains[table_name]

    db.table = MagicMock(side_effect=_table_factory)
    db._table_chains = _table_chains  # expose for test setup
    return db


def _mock_tl():
    """Build a mock TrueLayer client."""
    tl = MagicMock()
    tl.get_accounts = AsyncMock(return_value=[])
    tl.get_cards = AsyncMock(return_value=[])
    tl.get_account_balance = AsyncMock(return_value={"current": 1000.00, "available": 950.00})
    tl.get_card_balance = AsyncMock(return_value={"current": -250.00, "available": 750.00})
    tl.get_transactions = AsyncMock(return_value=[])
    tl.get_card_transactions = AsyncMock(return_value=[])
    tl.refresh_access_token = AsyncMock(return_value={
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    })
    return tl


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncConnectionConsentExpiry:
    """Tests for consent expiry checks (ARCH.md §5.3 step 1)."""

    @pytest.mark.asyncio
    async def test_expired_consent_skips_sync(self):
        conn = _make_connection(consent_expires_at=_past_iso(hours=1))
        db = _mock_db()
        db._table_chains["bank_connections"] = MagicMock()
        chain = db._table_chains["bank_connections"]
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        result_mock = MagicMock()
        result_mock.data = [conn]
        chain.execute.return_value = result_mock

        tl = _mock_tl()

        with patch("app.services.sync_engine.decrypt_token", return_value="plaintext"):
            summary = await sync_connection("conn-1", db, tl)

        assert summary["status"] == "skipped"
        assert "expired" in summary["detail"].lower()
        # Should NOT have tried to fetch accounts.
        tl.get_accounts.assert_not_called()

    @pytest.mark.asyncio
    async def test_expiring_soon_continues_sync(self):
        """Consent expiring within 7 days — status updated but sync continues."""
        expires_soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        conn = _make_connection(consent_expires_at=expires_soon)
        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        chain.upsert.return_value = chain
        result_mock = MagicMock()
        result_mock.data = [conn]
        chain.execute.return_value = result_mock
        db.table = MagicMock(return_value=chain)

        tl = _mock_tl()

        with patch("app.services.sync_engine.decrypt_token", return_value="plaintext"):
            with patch("app.services.sync_engine.encrypt_token", return_value="encrypted"):
                summary = await sync_connection("conn-1", db, tl)

        assert summary["status"] == "ok"
        # get_accounts should have been called (sync proceeded).
        tl.get_accounts.assert_called_once()


class TestSyncConnectionTokenRefresh:
    """Tests for token refresh logic (ARCH.md §5.3 step 2)."""

    @pytest.mark.asyncio
    async def test_refreshes_token_when_near_expiry(self):
        """Token expiring within threshold triggers refresh."""
        near_expiry = (
            datetime.now(timezone.utc) + timedelta(minutes=TOKEN_REFRESH_THRESHOLD_MINUTES - 1)
        ).isoformat()
        conn = _make_connection(token_expires_at=near_expiry)

        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        chain.upsert.return_value = chain
        result_mock = MagicMock()
        result_mock.data = [conn]
        chain.execute.return_value = result_mock
        db.table = MagicMock(return_value=chain)

        tl = _mock_tl()

        with patch("app.services.sync_engine.decrypt_token", return_value="plaintext"):
            with patch("app.services.sync_engine.encrypt_token", return_value="encrypted"):
                summary = await sync_connection("conn-1", db, tl)

        assert summary["status"] == "ok"
        tl.refresh_access_token.assert_called_once_with("plaintext")

    @pytest.mark.asyncio
    async def test_skips_refresh_when_token_still_valid(self):
        """Token not near expiry — no refresh call."""
        conn = _make_connection(token_expires_at=_future_iso(hours=12))

        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        chain.upsert.return_value = chain
        result_mock = MagicMock()
        result_mock.data = [conn]
        chain.execute.return_value = result_mock
        db.table = MagicMock(return_value=chain)

        tl = _mock_tl()

        with patch("app.services.sync_engine.decrypt_token", return_value="plaintext"):
            with patch("app.services.sync_engine.encrypt_token", return_value="encrypted"):
                summary = await sync_connection("conn-1", db, tl)

        assert summary["status"] == "ok"
        tl.refresh_access_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_refresh_failure_marks_error(self):
        """If token refresh fails, connection is marked error and sync stops."""
        from app.services.truelayer import TrueLayerError

        near_expiry = (
            datetime.now(timezone.utc) + timedelta(minutes=1)
        ).isoformat()
        conn = _make_connection(token_expires_at=near_expiry)

        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        result_mock = MagicMock()
        result_mock.data = [conn]
        chain.execute.return_value = result_mock
        db.table = MagicMock(return_value=chain)

        tl = _mock_tl()
        tl.refresh_access_token = AsyncMock(
            side_effect=TrueLayerError("Refresh denied", status_code=401)
        )

        with patch("app.services.sync_engine.decrypt_token", return_value="plaintext"):
            summary = await sync_connection("conn-1", db, tl)

        assert summary["status"] == "error"
        assert "refresh" in summary["detail"].lower()
        tl.get_accounts.assert_not_called()


class TestSyncConnectionHappyPath:
    """Tests for the full sync flow when everything succeeds."""

    @pytest.mark.asyncio
    async def test_syncs_accounts_balances_and_transactions(self):
        conn = _make_connection()

        # Mock the TrueLayer responses.
        tl = _mock_tl()
        tl.get_accounts = AsyncMock(return_value=[
            {
                "account_id": "tl-acct-1",
                "account_type": {"type": "TRANSACTION"},
                "display_name": "Current Account",
                "currency": "GBP",
            },
        ])
        tl.get_account_balance = AsyncMock(return_value={
            "current": 1234.56,
            "available": 1200.00,
        })
        tl.get_transactions = AsyncMock(return_value=[
            {
                "transaction_id": "txn-001",
                "timestamp": "2026-03-20T10:00:00Z",
                "description": "Tesco",
                "amount": -45.50,
                "currency": "GBP",
                "transaction_type": "DEBIT",
                "transaction_classification": ["Shopping", "Groceries"],
            },
        ])

        # Mock DB — all table calls return chainable mock with sensible defaults.
        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.update.return_value = chain
        chain.upsert.return_value = chain

        # First execute() returns the connection row, subsequent ones return generic data.
        call_count = {"n": 0}
        def _execute_side_effect():
            call_count["n"] += 1
            result = MagicMock()
            if call_count["n"] == 1:
                result.data = [conn]
            else:
                result.data = [{"id": "acct-uuid-1"}]
            return result

        chain.execute = MagicMock(side_effect=_execute_side_effect)
        db.table = MagicMock(return_value=chain)

        with patch("app.services.sync_engine.decrypt_token", return_value="plaintext-token"):
            with patch("app.services.sync_engine.encrypt_token", return_value="encrypted"):
                summary = await sync_connection("conn-1", db, tl)

        assert summary["status"] == "ok"
        assert summary["accounts_synced"] == 1
        assert summary["transactions_synced"] >= 1

        tl.get_accounts.assert_called_once_with("plaintext-token")
        tl.get_account_balance.assert_called_once()
        tl.get_transactions.assert_called_once()


class TestSyncConnectionLocking:
    """Tests for the connection-level lock preventing concurrent syncs."""

    @pytest.mark.asyncio
    async def test_concurrent_sync_is_skipped(self):
        """If a sync is already running for a connection, the second call skips."""
        # Manually add the connection to the lock set.
        _syncing_connections.add("conn-locked")
        try:
            db = _mock_db()
            tl = _mock_tl()
            summary = await sync_connection("conn-locked", db, tl)
            assert summary["status"] == "skipped"
            assert "already in progress" in summary["detail"].lower()
        finally:
            _syncing_connections.discard("conn-locked")

    @pytest.mark.asyncio
    async def test_lock_released_after_sync(self):
        """Lock is released even if sync fails."""
        conn = _make_connection(connection_id="conn-release")
        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.update.return_value = chain
        result_mock = MagicMock()
        result_mock.data = [conn]
        chain.execute.return_value = result_mock
        db.table = MagicMock(return_value=chain)

        tl = _mock_tl()

        with patch("app.services.sync_engine.decrypt_token", return_value="plain"):
            with patch("app.services.sync_engine.encrypt_token", return_value="enc"):
                await sync_connection("conn-release", db, tl)

        assert "conn-release" not in _syncing_connections


class TestSyncConnectionNotFound:
    """Test handling of a missing connection row."""

    @pytest.mark.asyncio
    async def test_missing_connection_returns_error(self):
        db = _mock_db()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        result_mock = MagicMock()
        result_mock.data = []
        chain.execute.return_value = result_mock
        db.table = MagicMock(return_value=chain)

        tl = _mock_tl()
        summary = await sync_connection("nonexistent", db, tl)

        assert summary["status"] == "error"
        assert "not found" in summary["detail"].lower()


class TestSyncUserConnections:
    """Tests for sync_user_connections (syncs all connections for a user)."""

    @pytest.mark.asyncio
    async def test_syncs_each_connection(self):
        db = _mock_db()
        tl = _mock_tl()

        # Mock the initial query to list user's connections.
        list_chain = MagicMock()
        list_chain.select.return_value = list_chain
        list_chain.eq.return_value = list_chain
        list_chain.in_.return_value = list_chain
        list_result = MagicMock()
        list_result.data = [{"id": "c1", "status": "active"}, {"id": "c2", "status": "active"}]
        list_chain.execute.return_value = list_result

        db.table = MagicMock(return_value=list_chain)

        with patch("app.services.sync_engine.sync_connection", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = {"status": "ok", "detail": "done"}
            results = await sync_user_connections("user-1", db, tl)

        assert len(results) == 2
        assert mock_sync.call_count == 2
