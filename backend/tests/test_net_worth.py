"""
Tests for the net worth router.

Uses FastAPI TestClient with mocked dependencies (auth + supabase).
Covers:
- GET /api/v1/net-worth — current net worth with per-account breakdown
- GET /api/v1/net-worth/history — daily net worth trend (7d, 30d, 90d)
- Credit cards subtracted from total
- is_included_in_net_worth=False accounts excluded
- Empty states (no accounts, no history)
- Auth required
- Invalid period parameter
- DB errors
"""

from datetime import date, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "user-nw-123"

ACCT_CURRENT = str(uuid4())
ACCT_SAVINGS = str(uuid4())
ACCT_CREDIT = str(uuid4())
ACCT_EXCLUDED = str(uuid4())


def _make_account(
    account_id, account_type="current", balance="1000.00",
    display_name="Account", included=True,
):
    return {
        "id": account_id,
        "account_type": account_type,
        "display_name": display_name,
        "currency": "GBP",
        "current_balance": balance,
        "balance_updated_at": "2026-03-25T10:00:00+00:00",
        "is_included_in_net_worth": included,
    }


def _make_history_row(account_id, balance, recorded_at):
    return {
        "account_id": account_id,
        "balance": str(balance),
        "recorded_at": recorded_at,
    }


def _mock_supabase_net_worth(accounts_data=None, raise_error=False):
    """Mock supabase client for GET /net-worth (single table query)."""
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain

    if raise_error:
        chain.execute.side_effect = APIError({"message": "DB connection failed"})
    else:
        result = MagicMock()
        result.data = accounts_data if accounts_data is not None else []
        chain.execute.return_value = result

    db.table.return_value = chain
    return db


def _mock_supabase_history(accounts_data=None, history_data=None, raise_accounts=False, raise_history=False):
    """
    Mock supabase client for GET /net-worth/history (two table queries).

    The router calls db.table("accounts") first, then db.table("balance_history").
    We use side_effect to return different chains for each call.
    """
    db = MagicMock()

    # Accounts chain
    acct_chain = MagicMock()
    acct_chain.select.return_value = acct_chain
    acct_chain.eq.return_value = acct_chain
    if raise_accounts:
        acct_chain.execute.side_effect = APIError({"message": "DB error"})
    else:
        acct_result = MagicMock()
        acct_result.data = accounts_data if accounts_data is not None else []
        acct_chain.execute.return_value = acct_result

    # History chain
    hist_chain = MagicMock()
    hist_chain.select.return_value = hist_chain
    hist_chain.eq.return_value = hist_chain
    hist_chain.gte.return_value = hist_chain
    hist_chain.order.return_value = hist_chain
    if raise_history:
        hist_chain.execute.side_effect = APIError({"message": "DB error"})
    else:
        hist_result = MagicMock()
        hist_result.data = history_data if history_data is not None else []
        hist_chain.execute.return_value = hist_result

    # Route table calls to the right chain.
    def table_router(name):
        if name == "accounts":
            return acct_chain
        elif name == "balance_history":
            return hist_chain
        raise ValueError(f"Unexpected table: {name}")

    db.table.side_effect = table_router
    return db


@pytest.fixture
def client():
    """TestClient with auth dependency overridden."""
    from app.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/net-worth
# ---------------------------------------------------------------------------


class TestGetNetWorth:

    def test_basic_net_worth_calculation(self, client):
        """Current + savings balances summed correctly."""
        accounts = [
            _make_account(ACCT_CURRENT, "current", "1500.50", "Current"),
            _make_account(ACCT_SAVINGS, "savings", "3000.00", "Savings"),
        ]
        db = _mock_supabase_net_worth(accounts_data=accounts)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 200
        data = resp.json()
        # 1500.50 + 3000.00 = 4500.50
        assert float(data["total_net_worth"]) == pytest.approx(4500.50)
        assert len(data["accounts"]) == 2
        assert data["currency"] == "GBP"

        app.dependency_overrides.pop(get_supabase, None)

    def test_credit_card_subtracted(self, client):
        """Credit card balance is subtracted from net worth."""
        accounts = [
            _make_account(ACCT_CURRENT, "current", "5000.00", "Current"),
            _make_account(ACCT_CREDIT, "credit_card", "1200.00", "Credit Card"),
        ]
        db = _mock_supabase_net_worth(accounts_data=accounts)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 200
        data = resp.json()
        # 5000 - 1200 = 3800
        assert float(data["total_net_worth"]) == pytest.approx(3800.00)

        # Check breakdown flags.
        cc = next(a for a in data["accounts"] if a["account_type"] == "credit_card")
        assert cc["is_liability"] is True
        current = next(a for a in data["accounts"] if a["account_type"] == "current")
        assert current["is_liability"] is False

        app.dependency_overrides.pop(get_supabase, None)

    def test_excluded_accounts_not_in_total(self, client):
        """Accounts with is_included_in_net_worth=False excluded from total but in breakdown."""
        accounts = [
            _make_account(ACCT_CURRENT, "current", "2000.00", "Current"),
            _make_account(ACCT_EXCLUDED, "savings", "8000.00", "Excluded Savings", included=False),
        ]
        db = _mock_supabase_net_worth(accounts_data=accounts)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 200
        data = resp.json()
        # Only the current account contributes.
        assert float(data["total_net_worth"]) == pytest.approx(2000.00)
        # But both accounts appear in the breakdown.
        assert len(data["accounts"]) == 2

        app.dependency_overrides.pop(get_supabase, None)

    def test_null_balances_treated_as_zero(self, client):
        """Accounts with no balance yet don't break the calculation."""
        accounts = [
            _make_account(ACCT_CURRENT, "current", None, "Current (no balance)"),
            _make_account(ACCT_SAVINGS, "savings", "500.00", "Savings"),
        ]
        db = _mock_supabase_net_worth(accounts_data=accounts)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["total_net_worth"]) == pytest.approx(500.00)

        app.dependency_overrides.pop(get_supabase, None)

    def test_no_accounts_returns_zero(self, client):
        """User with no accounts gets zero net worth."""
        db = _mock_supabase_net_worth(accounts_data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["total_net_worth"]) == 0
        assert data["accounts"] == []
        assert data["last_updated"] is None

        app.dependency_overrides.pop(get_supabase, None)

    def test_last_updated_is_most_recent(self, client):
        """last_updated reflects the most recent balance_updated_at."""
        accounts = [
            {
                **_make_account(ACCT_CURRENT, "current", "100.00", "Current"),
                "balance_updated_at": "2026-03-24T08:00:00+00:00",
            },
            {
                **_make_account(ACCT_SAVINGS, "savings", "200.00", "Savings"),
                "balance_updated_at": "2026-03-25T14:30:00+00:00",
            },
        ]
        db = _mock_supabase_net_worth(accounts_data=accounts)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 200
        data = resp.json()
        assert "2026-03-25T14:30:00" in data["last_updated"]

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_500_on_db_error(self, client):
        db = _mock_supabase_net_worth(raise_error=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/")
        assert resp.status_code == 500
        assert "Failed" in resp.json()["detail"]

        app.dependency_overrides.pop(get_supabase, None)


class TestGetNetWorthAuth:

    def test_requires_auth(self):
        app.dependency_overrides.clear()
        c = TestClient(app)
        resp = c.get("/api/v1/net-worth/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/net-worth/history
# ---------------------------------------------------------------------------


class TestGetNetWorthHistory:

    def test_returns_history_for_default_period(self, client):
        """Default period is 30d, returns aggregated daily data points."""
        today = date.today()
        accounts = [
            _make_account(ACCT_CURRENT, "current", "1000.00", "Current"),
        ]
        history = [
            _make_history_row(ACCT_CURRENT, 900, (today - timedelta(days=2)).isoformat()),
            _make_history_row(ACCT_CURRENT, 950, (today - timedelta(days=1)).isoformat()),
            _make_history_row(ACCT_CURRENT, 1000, today.isoformat()),
        ]
        db = _mock_supabase_history(accounts_data=accounts, history_data=history)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "30d"
        assert len(data["data_points"]) == 3
        assert data["currency"] == "GBP"
        # Points should be sorted by date.
        dates = [dp["date"] for dp in data["data_points"]]
        assert dates == sorted(dates)

        app.dependency_overrides.pop(get_supabase, None)

    def test_credit_card_subtracted_in_history(self, client):
        """Credit card balances are subtracted from daily totals."""
        today = date.today()
        accounts = [
            _make_account(ACCT_CURRENT, "current", "5000.00", "Current"),
            _make_account(ACCT_CREDIT, "credit_card", "1000.00", "CC"),
        ]
        day_str = today.isoformat()
        history = [
            _make_history_row(ACCT_CURRENT, 5000, day_str),
            _make_history_row(ACCT_CREDIT, 1000, day_str),
        ]
        db = _mock_supabase_history(accounts_data=accounts, history_data=history)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        # 5000 - 1000 = 4000
        assert float(data["data_points"][0]["net_worth"]) == pytest.approx(4000.00)
        assert data["period"] == "7d"

        app.dependency_overrides.pop(get_supabase, None)

    def test_excluded_accounts_omitted_from_history(self, client):
        """Accounts with is_included_in_net_worth=False are excluded from history totals."""
        today = date.today()
        accounts = [
            _make_account(ACCT_CURRENT, "current", "1000.00", "Current"),
            _make_account(ACCT_EXCLUDED, "savings", "9999.00", "Excluded", included=False),
        ]
        day_str = today.isoformat()
        history = [
            _make_history_row(ACCT_CURRENT, 1000, day_str),
            _make_history_row(ACCT_EXCLUDED, 9999, day_str),
        ]
        db = _mock_supabase_history(accounts_data=accounts, history_data=history)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=30d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        # Only the current account contributes.
        assert float(data["data_points"][0]["net_worth"]) == pytest.approx(1000.00)

        app.dependency_overrides.pop(get_supabase, None)

    def test_multiple_accounts_aggregated_per_day(self, client):
        """Multiple accounts on the same day are summed together."""
        today = date.today()
        accounts = [
            _make_account(ACCT_CURRENT, "current", "2000.00", "Current"),
            _make_account(ACCT_SAVINGS, "savings", "3000.00", "Savings"),
        ]
        day_str = today.isoformat()
        history = [
            _make_history_row(ACCT_CURRENT, 2000, day_str),
            _make_history_row(ACCT_SAVINGS, 3000, day_str),
        ]
        db = _mock_supabase_history(accounts_data=accounts, history_data=history)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=90d")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data_points"]) == 1
        assert float(data["data_points"][0]["net_worth"]) == pytest.approx(5000.00)
        assert data["period"] == "90d"

        app.dependency_overrides.pop(get_supabase, None)

    def test_empty_history_returns_no_data_points(self, client):
        """No balance_history rows returns an empty list."""
        accounts = [
            _make_account(ACCT_CURRENT, "current", "1000.00", "Current"),
        ]
        db = _mock_supabase_history(accounts_data=accounts, history_data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_points"] == []

        app.dependency_overrides.pop(get_supabase, None)

    def test_no_accounts_returns_empty(self, client):
        """User with no accounts returns empty history."""
        db = _mock_supabase_history(accounts_data=[], history_data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=30d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data_points"] == []

        app.dependency_overrides.pop(get_supabase, None)

    def test_invalid_period_returns_400(self, client):
        resp = client.get("/api/v1/net-worth/history?period=1y")
        assert resp.status_code == 400
        assert "Invalid period" in resp.json()["detail"]

    def test_supports_7d_period(self, client):
        db = _mock_supabase_history(accounts_data=[], history_data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=7d")
        assert resp.status_code == 200
        assert resp.json()["period"] == "7d"

        app.dependency_overrides.pop(get_supabase, None)

    def test_supports_90d_period(self, client):
        db = _mock_supabase_history(accounts_data=[], history_data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=90d")
        assert resp.status_code == 200
        assert resp.json()["period"] == "90d"

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_500_on_accounts_db_error(self, client):
        db = _mock_supabase_history(raise_accounts=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=30d")
        assert resp.status_code == 500

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_500_on_history_db_error(self, client):
        accounts = [_make_account(ACCT_CURRENT, "current", "1000.00", "Current")]
        db = _mock_supabase_history(accounts_data=accounts, raise_history=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/net-worth/history?period=30d")
        assert resp.status_code == 500

        app.dependency_overrides.pop(get_supabase, None)


class TestGetNetWorthHistoryAuth:

    def test_requires_auth(self):
        app.dependency_overrides.clear()
        c = TestClient(app)
        resp = c.get("/api/v1/net-worth/history")
        assert resp.status_code == 403
