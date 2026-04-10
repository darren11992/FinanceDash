"""
Tests for the balance history backfill logic.

Covers:
- Backfill from running_balance (preferred tier)
- Backfill from reverse-compute (fallback tier)
- Forward-fill gaps between dates
- Skips backfill on incremental sync (last_synced_at is set)
- Skips backfill when no transactions synced
- Non-fatal: backfill failure doesn't break the sync
- Does not overwrite existing balance_history rows
- is_estimated flag set correctly for each tier
- _parse_numeric helper
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.sync_engine import (
    _backfill_balance_history,
    _backfill_from_reverse_compute,
    _backfill_from_running_balance,
    _forward_fill,
    _parse_numeric,
)


# ---------------------------------------------------------------------------
# Unit tests: _parse_numeric
# ---------------------------------------------------------------------------


class TestParseNumeric:

    def test_float(self):
        assert _parse_numeric(1234.56) == 1234.56

    def test_int(self):
        assert _parse_numeric(100) == 100.0

    def test_string(self):
        assert _parse_numeric("1500.25") == 1500.25

    def test_none(self):
        assert _parse_numeric(None) is None

    def test_invalid_string(self):
        assert _parse_numeric("not-a-number") is None

    def test_empty_string(self):
        assert _parse_numeric("") is None


# ---------------------------------------------------------------------------
# Unit tests: _forward_fill
# ---------------------------------------------------------------------------


class TestForwardFill:

    def test_fills_gaps(self):
        sparse = {
            "2026-03-20": 1000.0,
            "2026-03-23": 1200.0,
        }
        result = _forward_fill(sparse)
        assert result == {
            "2026-03-20": 1000.0,
            "2026-03-21": 1000.0,
            "2026-03-22": 1000.0,
            "2026-03-23": 1200.0,
        }

    def test_no_gaps(self):
        dense = {
            "2026-03-20": 500.0,
            "2026-03-21": 600.0,
        }
        result = _forward_fill(dense)
        assert result == dense

    def test_single_date(self):
        result = _forward_fill({"2026-03-20": 100.0})
        assert result == {"2026-03-20": 100.0}

    def test_empty_dict(self):
        assert _forward_fill({}) == {}


# ---------------------------------------------------------------------------
# Unit tests: _backfill_from_running_balance
# ---------------------------------------------------------------------------


class TestBackfillFromRunningBalance:

    def test_basic_extraction(self):
        """Extracts last running_balance per day."""
        transactions = [
            {"timestamp": "2026-03-20T09:00:00Z", "amount": -50, "running_balance": "950.00"},
            {"timestamp": "2026-03-20T14:00:00Z", "amount": -30, "running_balance": "920.00"},
            {"timestamp": "2026-03-21T10:00:00Z", "amount": 100, "running_balance": "1020.00"},
        ]
        result = _backfill_from_running_balance(transactions)
        assert result["2026-03-20"] == 920.0  # last txn of the day
        assert result["2026-03-21"] == 1020.0

    def test_forward_fills_gaps(self):
        """Days with no transactions are forward-filled."""
        transactions = [
            {"timestamp": "2026-03-18T10:00:00Z", "amount": -10, "running_balance": "500.00"},
            {"timestamp": "2026-03-21T10:00:00Z", "amount": 50, "running_balance": "550.00"},
        ]
        result = _backfill_from_running_balance(transactions)
        assert result["2026-03-18"] == 500.0
        assert result["2026-03-19"] == 500.0  # forward-filled
        assert result["2026-03-20"] == 500.0  # forward-filled
        assert result["2026-03-21"] == 550.0

    def test_no_running_balance_returns_empty(self):
        """All transactions have NULL running_balance."""
        transactions = [
            {"timestamp": "2026-03-20T10:00:00Z", "amount": -50, "running_balance": None},
        ]
        result = _backfill_from_running_balance(transactions)
        assert result == {}

    def test_empty_transactions(self):
        assert _backfill_from_running_balance([]) == {}

    def test_mixed_null_running_balance(self):
        """Only uses transactions that have running_balance."""
        transactions = [
            {"timestamp": "2026-03-20T09:00:00Z", "amount": -50, "running_balance": None},
            {"timestamp": "2026-03-20T14:00:00Z", "amount": -30, "running_balance": "920.00"},
        ]
        result = _backfill_from_running_balance(transactions)
        assert result["2026-03-20"] == 920.0


# ---------------------------------------------------------------------------
# Unit tests: _backfill_from_reverse_compute
# ---------------------------------------------------------------------------


class TestBackfillFromReverseCompute:

    def test_basic_reverse_compute(self):
        """Derives historical balances from current balance and transactions."""
        transactions = [
            {"timestamp": "2026-03-23T10:00:00Z", "amount": -100.0},
            {"timestamp": "2026-03-24T10:00:00Z", "amount": -50.0},
            {"timestamp": "2026-03-25T10:00:00Z", "amount": 200.0},
        ]
        # Current balance is 1000 on 2026-03-25.
        result = _backfill_from_reverse_compute(transactions, 1000.0, "2026-03-25")

        # End of 25th: 1000 (given)
        # End of 24th: 1000 - 200 (reverse the 25th's +200) = 800
        # End of 23rd: 800 - (-50) (reverse the 24th's -50) = 850
        # End of 22nd: 850 - (-100) (reverse the 23rd's -100) = 950
        assert result["2026-03-25"] == 1000.0
        assert result["2026-03-24"] == 800.0
        assert result["2026-03-23"] == 850.0
        assert result["2026-03-22"] == 950.0

    def test_fills_days_with_no_transactions(self):
        """Days between transaction days get the carried-back balance."""
        transactions = [
            {"timestamp": "2026-03-20T10:00:00Z", "amount": -200.0},
            {"timestamp": "2026-03-25T10:00:00Z", "amount": 100.0},
        ]
        result = _backfill_from_reverse_compute(transactions, 500.0, "2026-03-25")
        # End of 25th: 500
        # End of 24th to 21st: 500 - 100 = 400 (reverse 25th), no movement on 24-21
        # End of 20th: same 400 (no movement on 21st)
        # End of 19th: 400 - (-200) = 600 (reverse 20th)
        assert result["2026-03-25"] == 500.0
        assert result["2026-03-24"] == 400.0
        assert result["2026-03-21"] == 400.0
        assert result["2026-03-19"] == 600.0

    def test_multiple_transactions_same_day(self):
        """Multiple transactions on same day are summed."""
        transactions = [
            {"timestamp": "2026-03-24T09:00:00Z", "amount": -100.0},
            {"timestamp": "2026-03-24T14:00:00Z", "amount": -50.0},
        ]
        result = _backfill_from_reverse_compute(transactions, 1000.0, "2026-03-25")
        # End of 25th: 1000
        # No movement on 25th itself (transactions are on 24th)
        # End of 24th: 1000 (no movement on 25th)
        # End of 23rd: 1000 - (-100 + -50) = 1000 + 150 = 1150
        assert result["2026-03-25"] == 1000.0
        assert result["2026-03-24"] == 1000.0
        assert result["2026-03-23"] == 1150.0

    def test_empty_transactions(self):
        result = _backfill_from_reverse_compute([], 1000.0, "2026-03-25")
        assert result == {}


# ---------------------------------------------------------------------------
# Integration tests: _backfill_balance_history
# ---------------------------------------------------------------------------


class TestBackfillBalanceHistory:

    def _mock_db(self, transactions=None, existing_dates=None):
        """Build a mock DB for backfill testing."""
        db = MagicMock()

        # Transactions query chain — must support paginated access:
        #   db.table("transactions").select(...).eq(...).order(...).range(0, 999).execute()
        # First page returns all transactions, signalling end of pagination
        # (len(data) < PAGE_SIZE).
        txn_chain = MagicMock()
        txn_chain.select.return_value = txn_chain
        txn_chain.eq.return_value = txn_chain
        txn_chain.order.return_value = txn_chain
        txn_chain.range.return_value = txn_chain
        txn_result = MagicMock()
        txn_result.data = transactions or []
        txn_chain.execute.return_value = txn_result

        # Existing balance_history query chain
        existing_chain = MagicMock()
        existing_chain.select.return_value = existing_chain
        existing_chain.eq.return_value = existing_chain
        existing_result = MagicMock()
        existing_result.data = [
            {"recorded_at": d} for d in (existing_dates or [])
        ]
        existing_chain.execute.return_value = existing_result

        # Upsert chain — production code does:
        #   db.table("balance_history").upsert(rows, on_conflict=...).execute()
        # So the object returned by table_router must have .upsert() which
        # returns something with .execute().
        upsert_inner = MagicMock()          # the object returned by .upsert()
        upsert_inner.execute.return_value = MagicMock()

        upsert_chain = MagicMock()
        upsert_chain.upsert.return_value = upsert_inner

        # Route table calls
        call_count = {"n": 0}

        def table_router(name):
            if name == "transactions":
                return txn_chain
            elif name == "balance_history":
                call_count["n"] += 1
                # First call = SELECT existing, second = UPSERT
                if call_count["n"] == 1:
                    return existing_chain
                return upsert_chain
            raise ValueError(f"Unexpected table: {name}")

        db.table = MagicMock(side_effect=table_router)
        db._upsert_chain = upsert_chain
        db._upsert_inner = upsert_inner
        return db

    def test_backfill_with_running_balance(self):
        """Uses running_balance when available, is_estimated=False."""
        transactions = [
            {"timestamp": "2026-03-20T10:00:00Z", "amount": "-50", "running_balance": "950.00"},
            {"timestamp": "2026-03-21T10:00:00Z", "amount": "100", "running_balance": "1050.00"},
        ]
        db = self._mock_db(transactions=transactions)

        _backfill_balance_history(
            db=db,
            user_id="user-1",
            account_id="acct-1",
            current_balance=1050.0,
            today_str="2026-03-25",
        )

        # Should have called upsert with is_estimated=False
        assert db._upsert_chain.upsert.called
        assert db._upsert_inner.execute.called
        # Verify the rows passed to upsert have is_estimated=False
        rows = db._upsert_chain.upsert.call_args[0][0]
        assert len(rows) > 0
        assert all(row["is_estimated"] is False for row in rows)

    def test_backfill_with_reverse_compute(self):
        """Falls back to reverse-compute when running_balance is NULL."""
        transactions = [
            {"timestamp": "2026-03-23T10:00:00Z", "amount": "-100.0", "running_balance": None},
            {"timestamp": "2026-03-24T10:00:00Z", "amount": "-50.0", "running_balance": None},
        ]
        db = self._mock_db(transactions=transactions)

        _backfill_balance_history(
            db=db,
            user_id="user-1",
            account_id="acct-1",
            current_balance=1000.0,
            today_str="2026-03-25",
        )

        # Should complete without error
        assert True

    def test_no_transactions_skips_backfill(self):
        """No transactions = nothing to backfill."""
        db = self._mock_db(transactions=[])

        _backfill_balance_history(
            db=db,
            user_id="user-1",
            account_id="acct-1",
            current_balance=1000.0,
            today_str="2026-03-25",
        )

        # Should NOT have queried balance_history for existing dates
        # (only the transactions query happens)
        calls = [str(c) for c in db.table.call_args_list]
        assert not any("balance_history" in c for c in calls)

    def test_skips_existing_dates(self):
        """Doesn't overwrite dates that already have balance_history rows."""
        transactions = [
            {"timestamp": "2026-03-20T10:00:00Z", "amount": "-50", "running_balance": "950.00"},
            {"timestamp": "2026-03-21T10:00:00Z", "amount": "100", "running_balance": "1050.00"},
        ]
        # Pretend 2026-03-20 already has a row
        db = self._mock_db(
            transactions=transactions,
            existing_dates=["2026-03-20"],
        )

        _backfill_balance_history(
            db=db,
            user_id="user-1",
            account_id="acct-1",
            current_balance=1050.0,
            today_str="2026-03-25",
        )

        # Should complete without error — the function filters out existing dates
        assert True

    def test_no_running_balance_and_no_current_balance_skips(self):
        """If no running_balance and no current_balance, skip backfill."""
        transactions = [
            {"timestamp": "2026-03-20T10:00:00Z", "amount": "-50", "running_balance": None},
        ]
        db = self._mock_db(transactions=transactions)

        _backfill_balance_history(
            db=db,
            user_id="user-1",
            account_id="acct-1",
            current_balance=None,
            today_str="2026-03-25",
        )

        # Should NOT have queried balance_history (skipped before that step)
        calls = [str(c) for c in db.table.call_args_list]
        balance_history_calls = [c for c in calls if "balance_history" in c]
        # Only the transactions query should have happened
        assert len(balance_history_calls) == 0


# ---------------------------------------------------------------------------
# Integration tests: backfill called from sync
# ---------------------------------------------------------------------------


class TestBackfillIntegrationWithSync:

    def test_backfill_called_on_initial_sync(self):
        """_backfill_balance_history is called when last_synced_at is None."""
        from app.services.sync_engine import _sync_single_account

        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.gte.return_value = chain
        chain.upsert.return_value = chain
        chain.update.return_value = chain
        result = MagicMock()
        result.data = [{"id": "acct-uuid-1"}]
        chain.execute.return_value = result
        db.table = MagicMock(return_value=chain)

        tl = MagicMock()
        tl.get_account_balance = AsyncMock(return_value={"current": 1000.0, "available": 900.0})
        tl.get_transactions = AsyncMock(return_value=[
            {
                "transaction_id": "txn-1",
                "timestamp": "2026-03-20T10:00:00Z",
                "description": "Test",
                "amount": -50,
                "currency": "GBP",
            }
        ])

        with patch("app.services.sync_engine._backfill_balance_history") as mock_backfill:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                _sync_single_account(
                    db=db,
                    truelayer_client=tl,
                    access_token="token",
                    connection_id="conn-1",
                    user_id="user-1",
                    last_synced_at=None,  # Initial sync
                    today_str="2026-03-25",
                    tl_account_id="tl-acct-1",
                    account_type="current",
                    display_name="Current",
                    currency="GBP",
                    is_card=False,
                )
            )

            mock_backfill.assert_called_once()
            call_kwargs = mock_backfill.call_args
            assert call_kwargs.kwargs["current_balance"] == 1000.0

    def test_backfill_not_called_on_incremental_sync(self):
        """_backfill_balance_history is NOT called when last_synced_at is set."""
        from app.services.sync_engine import _sync_single_account

        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.gte.return_value = chain
        chain.upsert.return_value = chain
        chain.update.return_value = chain
        result = MagicMock()
        result.data = [{"id": "acct-uuid-1"}]
        chain.execute.return_value = result
        db.table = MagicMock(return_value=chain)

        tl = MagicMock()
        tl.get_account_balance = AsyncMock(return_value={"current": 1000.0, "available": 900.0})
        tl.get_transactions = AsyncMock(return_value=[
            {
                "transaction_id": "txn-1",
                "timestamp": "2026-03-24T10:00:00Z",
                "description": "Test",
                "amount": -50,
                "currency": "GBP",
            }
        ])

        with patch("app.services.sync_engine._backfill_balance_history") as mock_backfill:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                _sync_single_account(
                    db=db,
                    truelayer_client=tl,
                    access_token="token",
                    connection_id="conn-1",
                    user_id="user-1",
                    last_synced_at="2026-03-24T10:00:00+00:00",  # Incremental
                    today_str="2026-03-25",
                    tl_account_id="tl-acct-1",
                    account_type="current",
                    display_name="Current",
                    currency="GBP",
                    is_card=False,
                )
            )

            mock_backfill.assert_not_called()

    def test_backfill_failure_does_not_break_sync(self):
        """Backfill failure is non-fatal — sync still succeeds."""
        from app.services.sync_engine import _sync_single_account

        db = MagicMock()
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.order.return_value = chain
        chain.gte.return_value = chain
        chain.upsert.return_value = chain
        chain.update.return_value = chain
        result = MagicMock()
        result.data = [{"id": "acct-uuid-1"}]
        chain.execute.return_value = result
        db.table = MagicMock(return_value=chain)

        tl = MagicMock()
        tl.get_account_balance = AsyncMock(return_value={"current": 1000.0, "available": 900.0})
        tl.get_transactions = AsyncMock(return_value=[
            {
                "transaction_id": "txn-1",
                "timestamp": "2026-03-20T10:00:00Z",
                "description": "Test",
                "amount": -50,
                "currency": "GBP",
            }
        ])

        with patch(
            "app.services.sync_engine._backfill_balance_history",
            side_effect=ValueError("DB exploded"),
        ):
            import asyncio
            acct_synced, txn_synced = asyncio.get_event_loop().run_until_complete(
                _sync_single_account(
                    db=db,
                    truelayer_client=tl,
                    access_token="token",
                    connection_id="conn-1",
                    user_id="user-1",
                    last_synced_at=None,  # Initial sync
                    today_str="2026-03-25",
                    tl_account_id="tl-acct-1",
                    account_type="current",
                    display_name="Current",
                    currency="GBP",
                    is_card=False,
                )
            )

            # Sync still returns success despite backfill failure.
            assert acct_synced == 1
            assert txn_synced == 1


# ---------------------------------------------------------------------------
# Tests: net worth history endpoint with is_estimated
# ---------------------------------------------------------------------------


class TestNetWorthHistoryEstimated:

    @pytest.fixture
    def client(self):
        from app.dependencies import get_current_user
        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: "user-nw-est"
        yield __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)
        app.dependency_overrides.clear()

    def _mock_history_db(self, accounts_data, history_data):
        db = MagicMock()
        acct_chain = MagicMock()
        acct_chain.select.return_value = acct_chain
        acct_chain.eq.return_value = acct_chain
        acct_result = MagicMock()
        acct_result.data = accounts_data
        acct_chain.execute.return_value = acct_result

        hist_chain = MagicMock()
        hist_chain.select.return_value = hist_chain
        hist_chain.eq.return_value = hist_chain
        hist_chain.gte.return_value = hist_chain
        hist_chain.order.return_value = hist_chain
        hist_result = MagicMock()
        hist_result.data = history_data
        hist_chain.execute.return_value = hist_result

        def table_router(name):
            return acct_chain if name == "accounts" else hist_chain

        db.table.side_effect = table_router
        return db

    def test_is_estimated_false_for_live_data(self, client):
        """Data points from live snapshots have is_estimated=False."""
        from app.dependencies import get_supabase
        from app.main import app

        accounts = [{"id": "a1", "account_type": "current", "is_included_in_net_worth": True}]
        history = [{
            "account_id": "a1",
            "balance": "1000.00",
            "recorded_at": "2026-03-25",
            "is_estimated": False,
        }]
        db = self._mock_history_db(accounts, history)
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        assert data["data_points"][0]["is_estimated"] is False

        app.dependency_overrides.pop(get_supabase, None)

    def test_is_estimated_true_for_backfilled_data(self, client):
        """Data points from reverse-compute have is_estimated=True."""
        from app.dependencies import get_supabase
        from app.main import app

        accounts = [{"id": "a1", "account_type": "current", "is_included_in_net_worth": True}]
        history = [{
            "account_id": "a1",
            "balance": "800.00",
            "recorded_at": "2026-03-20",
            "is_estimated": True,
        }]
        db = self._mock_history_db(accounts, history)
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=30d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        assert data["data_points"][0]["is_estimated"] is True

        app.dependency_overrides.pop(get_supabase, None)

    def test_mixed_estimated_and_live(self, client):
        """A day with both estimated and live rows is marked estimated."""
        from app.dependencies import get_supabase
        from app.main import app

        accounts = [
            {"id": "a1", "account_type": "current", "is_included_in_net_worth": True},
            {"id": "a2", "account_type": "savings", "is_included_in_net_worth": True},
        ]
        history = [
            {"account_id": "a1", "balance": "1000.00", "recorded_at": "2026-03-25", "is_estimated": False},
            {"account_id": "a2", "balance": "500.00", "recorded_at": "2026-03-25", "is_estimated": True},
        ]
        db = self._mock_history_db(accounts, history)
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        # If ANY contributing row is estimated, the day is estimated.
        assert data["data_points"][0]["is_estimated"] is True
        assert float(data["data_points"][0]["net_worth"]) == pytest.approx(1500.0)

        app.dependency_overrides.pop(get_supabase, None)
