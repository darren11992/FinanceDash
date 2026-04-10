"""
Tests for the accounts router.

Uses FastAPI TestClient with mocked dependencies (auth + supabase).
Covers:
- GET /api/v1/accounts — list all accounts for user
- GET /api/v1/accounts/{id} — single account detail
- Auth required (401 without JWT)
- 404 for nonexistent account
- 500 on DB error
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "user-123"
FAKE_ACCOUNT_ID = str(uuid4())
FAKE_CONNECTION_ID = str(uuid4())


def _make_account_row(account_id=None, account_type="current", display_name="Current Account"):
    return {
        "id": account_id or FAKE_ACCOUNT_ID,
        "bank_connection_id": FAKE_CONNECTION_ID,
        "truelayer_account_id": "tl-acct-1",
        "account_type": account_type,
        "display_name": display_name,
        "currency": "GBP",
        "current_balance": 1234.56,
        "available_balance": 1200.00,
        "balance_updated_at": "2026-03-24T10:00:00+00:00",
        "is_included_in_net_worth": True,
    }


def _mock_supabase(data=None, raise_error=False):
    """Return a mock supabase client with chainable query builder."""
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain

    if raise_error:
        chain.execute.side_effect = APIError({"message": "DB connection failed"})
    else:
        result = MagicMock()
        result.data = data if data is not None else []
        chain.execute.return_value = result

    db.table.return_value = chain
    return db


@pytest.fixture
def client():
    """TestClient with auth dependency overridden."""
    from app.dependencies import get_current_user, get_supabase

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/accounts
# ---------------------------------------------------------------------------


class TestListAccounts:

    def test_returns_accounts_list(self, client):
        rows = [_make_account_row(), _make_account_row(account_id=str(uuid4()), display_name="Savings")]
        db = _mock_supabase(data=rows)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/accounts/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["display_name"] == "Current Account"

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_empty_list_when_no_accounts(self, client):
        db = _mock_supabase(data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/accounts/")
        assert resp.status_code == 200
        assert resp.json() == []

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_500_on_db_error(self, client):
        db = _mock_supabase(raise_error=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/accounts/")
        assert resp.status_code == 500
        assert "Failed" in resp.json()["detail"]

        app.dependency_overrides.pop(get_supabase, None)


class TestListAccountsAuth:

    def test_requires_auth(self):
        """Without auth override, requests should get 403 (HTTPBearer returns 403 when missing)."""
        # Clear overrides so auth is enforced.
        app.dependency_overrides.clear()
        c = TestClient(app)
        resp = c.get("/api/v1/accounts/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/accounts/{account_id}
# ---------------------------------------------------------------------------


class TestGetAccount:

    def test_returns_single_account(self, client):
        row = _make_account_row()
        db = _mock_supabase(data=[row])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get(f"/api/v1/accounts/{FAKE_ACCOUNT_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == FAKE_ACCOUNT_ID
        assert data["account_type"] == "current"

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_404_when_not_found(self, client):
        db = _mock_supabase(data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get(f"/api/v1/accounts/{uuid4()}")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_500_on_db_error(self, client):
        db = _mock_supabase(raise_error=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get(f"/api/v1/accounts/{FAKE_ACCOUNT_ID}")
        assert resp.status_code == 500

        app.dependency_overrides.pop(get_supabase, None)

    def test_rejects_invalid_uuid(self, client):
        """Path parameter must be a valid UUID."""
        resp = client.get("/api/v1/accounts/not-a-uuid")
        assert resp.status_code == 422
