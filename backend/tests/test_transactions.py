"""
Tests for the transactions router.

Uses FastAPI TestClient with mocked dependencies (auth + supabase).
Covers:
- GET /api/v1/transactions — pagination, filtering by account/category/date
- PATCH /api/v1/transactions/{id}/category — set and clear manual override
- Auth required (403 without JWT)
- 404 for nonexistent transaction
- Edge cases: empty results, invalid inputs
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "user-456"
FAKE_ACCOUNT_ID = str(uuid4())
FAKE_TXN_ID = str(uuid4())


def _make_txn_row(
    txn_id=None,
    account_id=None,
    amount=-25.50,
    description="Tesco Express",
    auto_category="Groceries",
    user_category=None,
):
    return {
        "id": txn_id or FAKE_TXN_ID,
        "user_id": FAKE_USER_ID,
        "account_id": account_id or FAKE_ACCOUNT_ID,
        "truelayer_transaction_id": f"tl-txn-{txn_id or FAKE_TXN_ID}",
        "timestamp": "2026-03-20T14:30:00+00:00",
        "description": description,
        "amount": amount,
        "currency": "GBP",
        "transaction_type": "DEBIT",
        "merchant_name": "Tesco",
        "auto_category": auto_category,
        "user_category": user_category,
        "running_balance": 1000.00,
        "metadata": {},
    }


def _mock_supabase_transactions(data=None, count=None, raise_error=False):
    """
    Return a mock supabase client that handles both count and data queries.

    The transactions router makes two separate queries:
    1. count_query: .select("id", count="exact") -> result.count
    2. data_query: .select("*") -> result.data

    We use side_effect to return different results for sequential execute() calls.
    """
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.or_.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain

    if raise_error:
        chain.execute.side_effect = APIError({"message": "DB connection failed"})
    else:
        # First execute() call = count query, second = data query.
        count_result = MagicMock()
        count_result.count = count if count is not None else (len(data) if data else 0)
        count_result.data = []

        data_result = MagicMock()
        data_result.data = data if data is not None else []

        chain.execute.side_effect = [count_result, data_result]

    db.table.return_value = chain
    return db


def _mock_supabase_simple(data=None, raise_error=False):
    """Simple mock for single-query endpoints (PATCH category)."""
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.update.return_value = chain

    if raise_error:
        chain.execute.side_effect = APIError({"message": "DB error"})
    else:
        result = MagicMock()
        result.data = data if data is not None else []
        chain.execute.return_value = result

    db.table.return_value = chain
    return db


@pytest.fixture
def client():
    """TestClient with auth dependency overridden."""
    from app.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/transactions
# ---------------------------------------------------------------------------


class TestListTransactions:

    def test_returns_paginated_transactions(self, client):
        rows = [_make_txn_row(txn_id=str(uuid4())) for _ in range(3)]
        db = _mock_supabase_transactions(data=rows, count=3)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/transactions/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["has_more"] is False
        assert len(body["transactions"]) == 3

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_empty_when_no_transactions(self, client):
        db = _mock_supabase_transactions(data=[], count=0)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/transactions/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["transactions"] == []

        app.dependency_overrides.pop(get_supabase, None)

    def test_has_more_when_more_pages_exist(self, client):
        rows = [_make_txn_row(txn_id=str(uuid4())) for _ in range(2)]
        db = _mock_supabase_transactions(data=rows, count=100)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/transactions/?page=1&page_size=2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["total"] == 100

        app.dependency_overrides.pop(get_supabase, None)

    def test_effective_category_uses_user_override(self, client):
        """user_category takes precedence over auto_category in response."""
        row = _make_txn_row(auto_category="Shopping", user_category="Groceries")
        db = _mock_supabase_transactions(data=[row], count=1)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/transactions/")
        assert resp.status_code == 200
        txn = resp.json()["transactions"][0]
        assert txn["category"] == "Groceries"

        app.dependency_overrides.pop(get_supabase, None)

    def test_effective_category_falls_back_to_auto(self, client):
        """When user_category is null, auto_category is used."""
        row = _make_txn_row(auto_category="Transport", user_category=None)
        db = _mock_supabase_transactions(data=[row], count=1)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/transactions/")
        assert resp.status_code == 200
        txn = resp.json()["transactions"][0]
        assert txn["category"] == "Transport"

        app.dependency_overrides.pop(get_supabase, None)

    def test_rejects_page_size_over_200(self, client):
        resp = client.get("/api/v1/transactions/?page_size=201")
        assert resp.status_code == 422

    def test_rejects_page_below_1(self, client):
        resp = client.get("/api/v1/transactions/?page=0")
        assert resp.status_code == 422

    def test_returns_500_on_db_error(self, client):
        db = _mock_supabase_transactions(raise_error=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.get("/api/v1/transactions/")
        assert resp.status_code == 500

        app.dependency_overrides.pop(get_supabase, None)


class TestListTransactionsAuth:

    def test_requires_auth(self):
        app.dependency_overrides.clear()
        c = TestClient(app)
        resp = c.get("/api/v1/transactions/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: PATCH /api/v1/transactions/{id}/category
# ---------------------------------------------------------------------------


class TestUpdateCategory:

    def test_sets_user_category(self, client):
        existing = _make_txn_row(auto_category="Shopping")
        db = _mock_supabase_simple(data=[existing])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.patch(
            f"/api/v1/transactions/{FAKE_TXN_ID}/category",
            json={"category": "Groceries"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["category"] == "Groceries"
        assert body["is_user_override"] is True
        assert body["transaction_id"] == FAKE_TXN_ID

        app.dependency_overrides.pop(get_supabase, None)

    def test_clears_user_category(self, client):
        """Sending null reverts to auto_category."""
        existing = _make_txn_row(auto_category="Transport", user_category="Shopping")
        db = _mock_supabase_simple(data=[existing])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.patch(
            f"/api/v1/transactions/{FAKE_TXN_ID}/category",
            json={"category": None},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["category"] == "Transport"
        assert body["is_user_override"] is False

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_404_when_not_found(self, client):
        db = _mock_supabase_simple(data=[])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.patch(
            f"/api/v1/transactions/{uuid4()}/category",
            json={"category": "Food"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_422_for_invalid_uuid(self, client):
        resp = client.patch(
            "/api/v1/transactions/not-a-uuid/category",
            json={"category": "Food"},
        )
        assert resp.status_code == 422

    def test_returns_500_on_db_error(self, client):
        db = _mock_supabase_simple(raise_error=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.patch(
            f"/api/v1/transactions/{FAKE_TXN_ID}/category",
            json={"category": "Food"},
        )
        assert resp.status_code == 500

        app.dependency_overrides.pop(get_supabase, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/transactions/recategorise
# ---------------------------------------------------------------------------


def _mock_supabase_recategorise(rows, raise_error=False):
    """
    Mock supabase for the recategorise endpoint.

    The endpoint calls db.table("transactions") multiple times:
      - SELECT queries (paginated): first returns `rows`, second returns []
      - UPDATE queries: one per row that changed category

    We use a single chain mock with execute() returning different results
    based on call order.
    """
    db = MagicMock()
    chain = MagicMock()

    # Make all chainable methods return chain itself.
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.update.return_value = chain

    db.table.return_value = chain

    if raise_error:
        chain.execute.side_effect = APIError({"message": "DB error"})
    else:
        # Build the sequence of execute() results:
        # 1. First SELECT returns rows (page 1)
        # 2. Second SELECT returns [] (page 2 = end)
        # 3+. UPDATE calls return a simple result
        results = []

        # Page 1 of select
        page1 = MagicMock()
        page1.data = rows
        results.append(page1)

        # Page 2 of select (empty = stop pagination)
        page2 = MagicMock()
        page2.data = []
        results.append(page2)

        # One result per potential update (generous — more than needed)
        for _ in rows:
            update_result = MagicMock()
            update_result.data = [{}]
            results.append(update_result)

        chain.execute.side_effect = results

    return db


class TestRecategoriseTransactions:

    def test_recategorises_general_to_proper_category(self, client):
        """Transactions with 'General' auto_category get recategorised based on description."""
        rows = [
            {
                "id": str(uuid4()),
                "description": "TESCO STORES 1234",
                "merchant_name": None,
                "auto_category": "General",
                "user_category": None,
            },
            {
                "id": str(uuid4()),
                "description": "NETFLIX.COM",
                "merchant_name": None,
                "auto_category": "General",
                "user_category": None,
            },
        ]
        db = _mock_supabase_recategorise(rows)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.post("/api/v1/transactions/recategorise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_reviewed"] == 2
        assert body["updated"] == 2
        assert body["skipped_user_override"] == 0

        app.dependency_overrides.pop(get_supabase, None)

    def test_skips_user_overrides(self, client):
        """Transactions with user_category set are skipped."""
        rows = [
            {
                "id": str(uuid4()),
                "description": "TESCO STORES",
                "merchant_name": None,
                "auto_category": "General",
                "user_category": "Food",  # manual override — skip
            },
        ]
        db = _mock_supabase_recategorise(rows)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.post("/api/v1/transactions/recategorise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_reviewed"] == 1
        assert body["updated"] == 0
        assert body["skipped_user_override"] == 1

        app.dependency_overrides.pop(get_supabase, None)

    def test_no_update_when_category_unchanged(self, client):
        """If the category is already correct, no DB update is made."""
        rows = [
            {
                "id": str(uuid4()),
                "description": "TESCO STORES",
                "merchant_name": None,
                "auto_category": "Groceries",  # already correct
                "user_category": None,
            },
        ]
        db = _mock_supabase_recategorise(rows)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.post("/api/v1/transactions/recategorise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_reviewed"] == 1
        assert body["updated"] == 0
        assert body["skipped_user_override"] == 0

        app.dependency_overrides.pop(get_supabase, None)

    def test_empty_transactions(self, client):
        """No transactions to recategorise returns zero counts."""
        db = _mock_supabase_recategorise([])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.post("/api/v1/transactions/recategorise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_reviewed"] == 0
        assert body["updated"] == 0
        assert body["skipped_user_override"] == 0

        app.dependency_overrides.pop(get_supabase, None)

    def test_returns_500_on_db_error(self, client):
        db = _mock_supabase_recategorise([], raise_error=True)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        resp = client.post("/api/v1/transactions/recategorise")
        assert resp.status_code == 500

        app.dependency_overrides.pop(get_supabase, None)

    def test_requires_auth(self):
        app.dependency_overrides.clear()
        c = TestClient(app)
        resp = c.post("/api/v1/transactions/recategorise")
        assert resp.status_code == 403
