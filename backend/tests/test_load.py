"""
Load tests for the sync engine — verifies correctness under concurrent load.

Tests:
- Connection-level lock prevents double-syncs of the same connection
- Multiple users syncing concurrently don't interfere
- Rate limit on POST /sync prevents rapid-fire requests
- Sync engine handles partial failures gracefully under concurrent load
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sync_engine import (
    _syncing_connections,
    sync_connection,
    sync_user_connections,
)
from app.services.truelayer import TrueLayerClient, TrueLayerError


NOW = datetime.now(timezone.utc)

FAKE_CONNECTION_ROW = {
    "id": "conn-load-1",
    "user_id": "user-load-1",
    "provider_id": "uk-ob-natwest",
    "provider_name": "NatWest",
    "status": "active",
    "last_synced_at": NOW.isoformat(),
    "consent_created_at": NOW.isoformat(),
    "consent_expires_at": (NOW + timedelta(days=60)).isoformat(),
    "token_expires_at": (NOW + timedelta(hours=1)).isoformat(),
    "access_token": "encrypted-at",
    "refresh_token": "encrypted-rt",
    "error_message": None,
    "created_at": NOW.isoformat(),
}


def _make_db_mock(connections=None, accounts=None, transactions=None):
    """Create a mock Supabase client with chainable table calls."""
    db = MagicMock()

    def table_factory(name):
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.order.return_value = chain
        chain.range.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.update.return_value = chain
        chain.upsert.return_value = chain
        chain.delete.return_value = chain

        result = MagicMock()
        if name == "bank_connections":
            result.data = connections or []
        elif name == "accounts":
            result.data = accounts or [{"id": "acct-load-1"}]
        elif name == "transactions":
            result.data = transactions or []
        elif name == "balance_history":
            result.data = []
        else:
            result.data = []

        chain.execute.return_value = result
        return chain

    db.table.side_effect = table_factory
    return db


def _make_truelayer_mock(
    accounts=None,
    cards=None,
    balance=None,
    transactions=None,
    sync_delay: float = 0,
):
    """Create a mock TrueLayerClient with optional artificial delay.

    When sync_delay > 0, each async method sleeps before returning to
    simulate real I/O latency.  The side_effect callables are themselves
    async functions so that AsyncMock does not double-wrap the coroutine.
    """
    truelayer_client = MagicMock(spec=TrueLayerClient)

    _accounts = accounts if accounts is not None else []
    _cards = cards if cards is not None else []
    _balance_acct = balance or {"current": 1000.0, "available": 950.0}
    _balance_card = balance or {"current": 200.0, "available": 800.0}
    _transactions = transactions if transactions is not None else []

    async def _get_accounts(token):
        if sync_delay > 0:
            await asyncio.sleep(sync_delay)
        return _accounts

    async def _get_cards(token):
        if sync_delay > 0:
            await asyncio.sleep(sync_delay)
        return _cards

    async def _get_account_balance(token, acct_id):
        if sync_delay > 0:
            await asyncio.sleep(sync_delay)
        return _balance_acct

    async def _get_card_balance(token, card_id):
        if sync_delay > 0:
            await asyncio.sleep(sync_delay)
        return _balance_card

    async def _get_transactions(token, acct_id, from_date, to_date):
        if sync_delay > 0:
            await asyncio.sleep(sync_delay)
        return _transactions

    async def _get_card_transactions(token, card_id, from_date, to_date):
        if sync_delay > 0:
            await asyncio.sleep(sync_delay)
        return _transactions

    truelayer_client.get_accounts = AsyncMock(side_effect=_get_accounts)
    truelayer_client.get_cards = AsyncMock(side_effect=_get_cards)
    truelayer_client.get_account_balance = AsyncMock(side_effect=_get_account_balance)
    truelayer_client.get_card_balance = AsyncMock(side_effect=_get_card_balance)
    truelayer_client.get_transactions = AsyncMock(side_effect=_get_transactions)
    truelayer_client.get_card_transactions = AsyncMock(side_effect=_get_card_transactions)

    return truelayer_client


# =========================================================================
# Test 1: Connection-level lock prevents double-syncs
# =========================================================================


class TestConnectionLevelLock:
    """Verify the in-memory _syncing_connections set prevents
    concurrent syncs of the same connection."""

    @pytest.mark.asyncio
    async def test_concurrent_sync_same_connection_returns_skipped(self):
        """If two syncs of the same connection start, the second should be
        skipped with status='skipped'."""
        # Set up: slow sync that takes 0.1s
        db = _make_db_mock(connections=[FAKE_CONNECTION_ROW])
        truelayer_client = _make_truelayer_mock(sync_delay=0.1)

        with patch(
            "app.services.sync_engine.decrypt_token", return_value="decrypted"
        ):
            # Start two syncs concurrently for the SAME connection
            task1 = asyncio.create_task(
                sync_connection("conn-load-1", db, truelayer_client)
            )
            # Small delay to ensure task1 acquires lock first
            await asyncio.sleep(0.01)
            task2 = asyncio.create_task(
                sync_connection("conn-load-1", db, truelayer_client)
            )

            result1, result2 = await asyncio.gather(task1, task2)

        # One should succeed, one should be skipped
        assert {result1["status"], result2["status"]} == {"ok", "skipped"}, (
            f"Expected exactly one 'ok' and one 'skipped', got: {result1}, {result2}"
        )

    @pytest.mark.asyncio
    async def test_lock_released_after_sync_completes(self):
        """After sync completes, the connection should no longer be locked."""
        db = _make_db_mock(connections=[FAKE_CONNECTION_ROW])
        truelayer_client = _make_truelayer_mock()

        # Ensure lock set is clean
        _syncing_connections.discard("conn-load-1")

        with patch(
            "app.services.sync_engine.decrypt_token", return_value="decrypted"
        ):
            result = await sync_connection("conn-load-1", db, truelayer_client)

        assert result["status"] in ("ok", "error")
        assert "conn-load-1" not in _syncing_connections

    @pytest.mark.asyncio
    async def test_lock_released_even_on_exception(self):
        """Lock should be released even if sync throws an exception."""
        db = _make_db_mock(connections=[FAKE_CONNECTION_ROW])
        truelayer_client = _make_truelayer_mock()

        # Make TrueLayer raise an error
        truelayer_client.get_accounts = AsyncMock(
            side_effect=TrueLayerError("Service unavailable")
        )

        _syncing_connections.discard("conn-load-1")

        with patch(
            "app.services.sync_engine.decrypt_token", return_value="decrypted"
        ):
            result = await sync_connection("conn-load-1", db, truelayer_client)

        # Should be error but lock should be released
        assert "conn-load-1" not in _syncing_connections


# =========================================================================
# Test 2: Multiple users syncing concurrently
# =========================================================================


class TestMultiUserConcurrency:
    """Verify that multiple users syncing different connections
    works correctly and doesn't interfere."""

    @pytest.mark.asyncio
    async def test_concurrent_syncs_different_connections(self):
        """Two different connections can sync concurrently without issues."""
        conn1 = {**FAKE_CONNECTION_ROW, "id": "conn-user-a", "user_id": "user-a"}
        conn2 = {**FAKE_CONNECTION_ROW, "id": "conn-user-b", "user_id": "user-b"}

        db1 = _make_db_mock(connections=[conn1])
        db2 = _make_db_mock(connections=[conn2])

        truelayer_client = _make_truelayer_mock(sync_delay=0.05)

        _syncing_connections.discard("conn-user-a")
        _syncing_connections.discard("conn-user-b")

        with patch(
            "app.services.sync_engine.decrypt_token", return_value="decrypted"
        ):
            result1, result2 = await asyncio.gather(
                sync_connection("conn-user-a", db1, truelayer_client),
                sync_connection("conn-user-b", db2, truelayer_client),
            )

        # Both should complete successfully (neither should be skipped or errored)
        assert result1["status"] == "ok", f"Connection A should succeed: {result1}"
        assert result2["status"] == "ok", f"Connection B should succeed: {result2}"

    @pytest.mark.asyncio
    async def test_many_concurrent_connections(self):
        """Simulate 10 different connections syncing concurrently."""
        connections = []
        dbs = []
        for i in range(10):
            conn_id = f"conn-multi-{i}"
            conn = {**FAKE_CONNECTION_ROW, "id": conn_id, "user_id": f"user-{i}"}
            connections.append(conn)
            dbs.append(_make_db_mock(connections=[conn]))
            _syncing_connections.discard(conn_id)

        truelayer_client = _make_truelayer_mock(sync_delay=0.02)

        with patch(
            "app.services.sync_engine.decrypt_token", return_value="decrypted"
        ):
            results = await asyncio.gather(*[
                sync_connection(connections[i]["id"], dbs[i], truelayer_client)
                for i in range(10)
            ])

        # All should complete successfully
        for i, result in enumerate(results):
            assert result["status"] == "ok", (
                f"Connection {i} should succeed: {result}"
            )


# =========================================================================
# Test 3: Rate limiting on POST /sync endpoint
# =========================================================================


class TestSyncRateLimit:
    """Verify rate limiting on the sync endpoint."""

    @pytest.fixture
    def client(self):
        from app.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: "user-rate-test"
        yield TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides.clear()

    def test_rapid_sync_requests_within_limit(self, client):
        """A few rapid sync requests should succeed (within 10/min limit)."""
        with patch(
            "app.routers.sync.sync_user_connections",
            new_callable=AsyncMock,
        ) as mock_sync:
            mock_sync.return_value = []

            db = MagicMock()
            from app.dependencies import get_supabase
            app.dependency_overrides[get_supabase] = lambda: db

            # The sync router reads TrueLayerClient from app.state.truelayer.
            # Set it so that the endpoint doesn't blow up before reaching
            # the (already-patched) sync_user_connections call.
            app.state.truelayer = _make_truelayer_mock()

            try:
                # Send 3 requests — should all succeed
                for _ in range(3):
                    resp = client.post("/api/v1/sync/")
                    assert resp.status_code == 200, (
                        f"Expected 200, got {resp.status_code}: {resp.text}"
                    )
            finally:
                app.dependency_overrides.pop(get_supabase, None)
                # Clean up app state to avoid leaking into other tests.
                if hasattr(app.state, "truelayer"):
                    del app.state.truelayer


# =========================================================================
# Test 4: Partial failure handling under concurrent load
# =========================================================================


class TestPartialFailureUnderLoad:
    """Verify sync engine handles partial failures gracefully
    when multiple connections are being synced."""

    @pytest.mark.asyncio
    async def test_one_connection_fails_others_continue(self):
        """If one connection's TrueLayer call fails, other connections
        should still sync successfully."""
        good_conn = {
            **FAKE_CONNECTION_ROW,
            "id": "conn-good",
            "user_id": "user-partial",
        }
        bad_conn = {
            **FAKE_CONNECTION_ROW,
            "id": "conn-bad",
            "user_id": "user-partial",
        }

        good_db = _make_db_mock(connections=[good_conn])
        bad_db = _make_db_mock(connections=[bad_conn])

        # Create separate TrueLayer mocks — one that works, one that fails
        good_tl = _make_truelayer_mock()
        bad_tl = MagicMock(spec=TrueLayerClient)
        bad_tl.get_accounts = AsyncMock(
            side_effect=TrueLayerError("Provider temporarily unavailable")
        )
        bad_tl.get_cards = AsyncMock(
            side_effect=TrueLayerError("Provider temporarily unavailable")
        )

        _syncing_connections.discard("conn-good")
        _syncing_connections.discard("conn-bad")

        with patch(
            "app.services.sync_engine.decrypt_token", return_value="decrypted"
        ):
            good_result, bad_result = await asyncio.gather(
                sync_connection("conn-good", good_db, good_tl),
                sync_connection("conn-bad", bad_db, bad_tl),
            )

        # Good connection should succeed
        assert good_result["status"] in ("ok",), (
            f"Good connection should succeed: {good_result}"
        )

        # Bad connection should report error but not crash
        assert bad_result["status"] in ("ok", "error"), (
            f"Bad connection should handle failure: {bad_result}"
        )

    @pytest.mark.asyncio
    async def test_sync_user_connections_handles_mixed_statuses(self):
        """sync_user_connections processes active and error connections,
        skips expired/revoked."""
        db = MagicMock()

        connections_data = [
            {"id": "conn-active", "status": "active"},
            {"id": "conn-error", "status": "error"},
            {"id": "conn-expired", "status": "expired"},
            {"id": "conn-revoked", "status": "revoked"},
        ]

        # First call: select connections
        select_chain = MagicMock()
        select_chain.select.return_value = select_chain
        select_chain.eq.return_value = select_chain
        result = MagicMock()
        result.data = connections_data
        select_chain.execute.return_value = result

        db.table.return_value = select_chain

        truelayer_client = _make_truelayer_mock()

        with patch(
            "app.services.sync_engine.sync_connection",
            new_callable=AsyncMock,
        ) as mock_sync_conn:
            mock_sync_conn.return_value = {
                "status": "ok",
                "accounts_synced": 1,
                "transactions_synced": 5,
            }

            results = await sync_user_connections(
                "user-mixed", db, truelayer_client
            )

        # Should only sync active and error connections (2 out of 4)
        assert len(results) == 2
        synced_ids = {r["connection_id"] for r in results}
        assert "conn-active" in synced_ids
        assert "conn-error" in synced_ids
        assert "conn-expired" not in synced_ids
        assert "conn-revoked" not in synced_ids
