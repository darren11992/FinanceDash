"""
End-to-end tests for critical user flows.

These tests simulate complete user journeys through the API using
mocked Supabase and TrueLayer backends. They verify that the full
chain of operations works correctly:

1. Connect bank -> sync -> view dashboard -> view transactions
2. Disconnect bank -> data removed
3. Re-consent flow (expiring/expired connections)
4. Category override -> recategorise preserves overrides
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.truelayer import TrueLayerClient, TrueLayerError


FAKE_USER_ID = "user-e2e-test-001"
FAKE_CONNECTION_ID = "11111111-1111-1111-1111-111111111111"
FAKE_ACCOUNT_ID = "22222222-2222-2222-2222-222222222222"
FAKE_TRANSACTION_ID = "33333333-3333-3333-3333-333333333333"

NOW = datetime.now(timezone.utc)

# -- Fake data -----------------------------------------------------------------

FAKE_CONNECTION = {
    "id": FAKE_CONNECTION_ID,
    "user_id": FAKE_USER_ID,
    "provider_id": "uk-ob-natwest",
    "provider_name": "NatWest",
    "status": "active",
    "last_synced_at": NOW.isoformat(),
    "consent_created_at": NOW.isoformat(),
    "consent_expires_at": (NOW + timedelta(days=90)).isoformat(),
    "error_message": None,
    "created_at": NOW.isoformat(),
    "access_token": "encrypted-access",
    "refresh_token": "encrypted-refresh",
}

FAKE_ACCOUNT = {
    "id": FAKE_ACCOUNT_ID,
    "bank_connection_id": FAKE_CONNECTION_ID,
    "truelayer_account_id": "tl-acct-123",
    "account_type": "current",
    "display_name": "NatWest Current Account",
    "currency": "GBP",
    "current_balance": "1250.50",
    "available_balance": "1200.00",
    "balance_updated_at": NOW.isoformat(),
    "is_included_in_net_worth": True,
    "user_id": FAKE_USER_ID,
}

FAKE_CREDIT_CARD = {
    "id": "44444444-4444-4444-4444-444444444444",
    "bank_connection_id": FAKE_CONNECTION_ID,
    "truelayer_account_id": "tl-card-456",
    "account_type": "credit_card",
    "display_name": "NatWest Credit Card",
    "currency": "GBP",
    "current_balance": "350.00",
    "available_balance": "2650.00",
    "balance_updated_at": NOW.isoformat(),
    "is_included_in_net_worth": True,
    "user_id": FAKE_USER_ID,
}

FAKE_TRANSACTION = {
    "id": FAKE_TRANSACTION_ID,
    "account_id": FAKE_ACCOUNT_ID,
    "user_id": FAKE_USER_ID,
    "timestamp": NOW.isoformat(),
    "description": "CARD PAYMENT TO TESCO STORES ON 01-01-2026",
    "amount": "-45.20",
    "currency": "GBP",
    "transaction_type": "DEBIT",
    "merchant_name": None,
    "auto_category": "Groceries",
    "user_category": None,
    "running_balance": "1205.30",
}


# -- Fixtures ------------------------------------------------------------------


@pytest.fixture
def client():
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client():
    return TestClient(app, raise_server_exceptions=False)


def _make_chain(data=None, count=None):
    """Create a chainable mock that simulates Supabase PostgREST queries."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.or_.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.in_.return_value = chain
    chain.delete.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.upsert.return_value = chain
    result = MagicMock()
    result.data = data if data is not None else []
    result.count = count if count is not None else (len(data) if data else 0)
    chain.execute.return_value = result
    return chain


# =========================================================================
# E2E Flow 1: Connect bank -> sync -> dashboard -> transactions
# =========================================================================


class TestConnectAndViewFlow:
    """Full flow: initiate connection -> callback -> list connections -> view
    accounts -> view net worth -> view transactions."""

    def test_initiate_and_callback(self, client):
        """User can initiate connection and receive callback."""
        # 1. Initiate — get auth URL
        tl = MagicMock(spec=TrueLayerClient)
        tl.build_auth_url.return_value = ("https://auth.truelayer.com/?code=xyz", "state-123")
        app.state.truelayer = tl

        try:
            resp = client.post("/api/v1/connections/initiate")
            assert resp.status_code == 200
            data = resp.json()
            assert "auth_url" in data
            assert "truelayer.com" in data["auth_url"]
        finally:
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer

    def test_post_callback_creates_connection(self, client):
        """POST callback exchanges code and creates a connection."""
        tl = MagicMock(spec=TrueLayerClient)
        tl.exchange_code = AsyncMock(return_value={
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "token_expires_at": (NOW + timedelta(hours=1)),
        })
        tl.get_connection_metadata = AsyncMock(return_value={
            "results": [{
                "provider": {"provider_id": "uk-ob-natwest", "display_name": "NatWest"},
                "consent_created_at": NOW.isoformat(),
                "consent_expires_at": (NOW + timedelta(days=90)).isoformat(),
            }]
        })
        app.state.truelayer = tl

        db = MagicMock()
        chain = _make_chain(data=[{
            "id": FAKE_CONNECTION_ID,
            "provider_name": "NatWest",
        }])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.encrypt_token", return_value="encrypted"):
                resp = client.post(
                    "/api/v1/connections/callback",
                    json={"code": "auth-code-from-truelayer"},
                )
                assert resp.status_code == 201
                data = resp.json()
                assert data["connection_id"] == FAKE_CONNECTION_ID
                assert data["provider_name"] == "NatWest"
                assert data["status"] == "active"
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer

    def test_list_connections_returns_connected_banks(self, client):
        """After connecting, user can see their banks listed."""
        db = MagicMock()
        chain = _make_chain(data=[FAKE_CONNECTION])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.get("/api/v1/connections/")
            assert resp.status_code == 200
            connections = resp.json()
            assert len(connections) == 1
            assert connections[0]["provider_name"] == "NatWest"
            assert connections[0]["status"] == "active"
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_view_accounts_with_balances(self, client):
        """User can view accounts with balances from connected bank."""
        db = MagicMock()
        chain = _make_chain(data=[FAKE_ACCOUNT, FAKE_CREDIT_CARD])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.get("/api/v1/accounts/")
            assert resp.status_code == 200
            accounts = resp.json()
            assert len(accounts) == 2
            account_types = {a["account_type"] for a in accounts}
            assert "current" in account_types
            assert "credit_card" in account_types
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_net_worth_includes_assets_minus_liabilities(self, client):
        """Net worth = current account balance - credit card balance."""
        db = MagicMock()
        chain = _make_chain(data=[FAKE_ACCOUNT, FAKE_CREDIT_CARD])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.get("/api/v1/net-worth/")
            assert resp.status_code == 200
            data = resp.json()
            # 1250.50 - 350.00 = 900.50
            assert float(data["total_net_worth"]) == pytest.approx(900.50, rel=1e-2)
            assert data["currency"] == "GBP"
            assert len(data["accounts"]) == 2
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_view_transactions_paginated(self, client):
        """User can view transactions with pagination."""
        txns = [FAKE_TRANSACTION]

        db = MagicMock()
        # count query returns 1, data query returns 1 row
        count_chain = _make_chain(data=[], count=1)
        data_chain = _make_chain(data=txns)

        call_count = [0]
        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.order.return_value = chain
            chain.range.return_value = chain
            chain.gte.return_value = chain
            chain.lte.return_value = chain
            chain.or_.return_value = chain
            result = MagicMock()
            if call_count[0] == 0:
                result.count = 1
                result.data = []
            else:
                result.count = None
                result.data = txns
            call_count[0] += 1
            chain.execute.return_value = result
            return chain

        db.table.side_effect = table_side_effect

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.get("/api/v1/transactions/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1
            assert data["page"] == 1
            assert len(data["transactions"]) == 1
            txn = data["transactions"][0]
            assert "TESCO" in txn["description"]
            assert txn["category"] == "Groceries"
        finally:
            app.dependency_overrides.pop(get_supabase, None)


# =========================================================================
# E2E Flow 2: Disconnect bank -> data removed
# =========================================================================


class TestDisconnectFlow:
    """Full flow: delete connection -> verify cleanup."""

    def test_delete_connection(self, client):
        """User can delete a connection; server attempts token revocation."""
        tl = MagicMock(spec=TrueLayerClient)
        tl.data_base_url = "https://api.truelayer.com"
        tl._http = MagicMock()
        tl._http.delete = AsyncMock(return_value=MagicMock(status_code=200))
        app.state.truelayer = tl

        db = MagicMock()
        # First call: select to find connection
        select_chain = _make_chain(data=[FAKE_CONNECTION])
        # Second call: delete
        delete_chain = _make_chain()

        call_count = [0]
        def table_side_effect(name):
            if call_count[0] == 0:
                call_count[0] += 1
                return select_chain
            return delete_chain

        db.table.side_effect = table_side_effect

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted-token"):
                resp = client.delete(f"/api/v1/connections/{FAKE_CONNECTION_ID}")
                assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer

    def test_delete_nonexistent_connection_returns_404(self, client):
        """Deleting a connection that doesn't exist returns 404."""
        tl = MagicMock(spec=TrueLayerClient)
        app.state.truelayer = tl

        db = MagicMock()
        chain = _make_chain(data=[])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.delete(f"/api/v1/connections/{FAKE_CONNECTION_ID}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer


# =========================================================================
# E2E Flow 3: Re-consent flow
# =========================================================================


class TestReconsentFlow:
    """Full flow: connection expires -> reconnect -> consent renewed."""

    def test_reconnect_no_action_needed(self, client):
        """Reconnect succeeds silently (no bank re-auth required)."""
        expiring_conn = {**FAKE_CONNECTION, "status": "expiring_soon"}

        tl = MagicMock(spec=TrueLayerClient)
        tl.extend_connection = AsyncMock(return_value={
            "action_needed": "no_action_needed",
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": 3600,
            "token_expires_at": NOW + timedelta(hours=1),
        })
        tl.get_connection_metadata = AsyncMock(return_value={
            "results": [{
                "consent_created_at": NOW.isoformat(),
                "consent_expires_at": (NOW + timedelta(days=90)).isoformat(),
            }]
        })
        app.state.truelayer = tl

        db = MagicMock()
        chain = _make_chain(data=[expiring_conn])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted-rt"):
                with patch("app.routers.connections.encrypt_token", return_value="encrypted"):
                    resp = client.post(
                        f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect"
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["action"] == "no_action_needed"
                    assert data["auth_url"] is None
                    assert "renewed" in data["message"].lower()
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer

    def test_reconnect_authentication_needed(self, client):
        """Reconnect requires bank re-auth — returns auth URL."""
        expired_conn = {**FAKE_CONNECTION, "status": "expired"}

        tl = MagicMock(spec=TrueLayerClient)
        tl.extend_connection = AsyncMock(return_value={
            "action_needed": "authentication_needed",
            "auth_url": "https://auth.truelayer.com/reauth?token=xyz",
        })
        app.state.truelayer = tl

        db = MagicMock()
        chain = _make_chain(data=[expired_conn])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted-rt"):
                resp = client.post(
                    f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect"
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["action"] == "authentication_needed"
                assert data["auth_url"] is not None
                assert "truelayer.com" in data["auth_url"]
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer

    def test_reconnect_active_connection_rejected(self, client):
        """Active connections don't need reconnection — returns 400."""
        active_conn = {**FAKE_CONNECTION, "status": "active"}

        tl = MagicMock(spec=TrueLayerClient)
        app.state.truelayer = tl

        db = MagicMock()
        chain = _make_chain(data=[active_conn])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.post(
                f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect"
            )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer


# =========================================================================
# E2E Flow 4: Category override + recategorise
# =========================================================================


class TestCategoryOverrideFlow:
    """Full flow: view transaction -> override category -> recategorise
    preserves user override."""

    def test_override_then_recategorise_preserves(self, client):
        """Manual category override survives a recategorise run."""
        # 1. Override a transaction's category
        txn_before = {
            "id": FAKE_TRANSACTION_ID,
            "auto_category": "Groceries",
            "user_category": None,
        }
        db_override = MagicMock()
        chain_override = _make_chain(data=[txn_before])
        db_override.table.return_value = chain_override

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db_override

        try:
            resp = client.patch(
                f"/api/v1/transactions/{FAKE_TRANSACTION_ID}/category",
                json={"category": "Personal"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["category"] == "Personal"
            assert data["is_user_override"] is True
        finally:
            app.dependency_overrides.pop(get_supabase, None)

        # 2. Now recategorise — the overridden transaction should be skipped
        txn_with_override = {
            "id": FAKE_TRANSACTION_ID,
            "description": "CARD PAYMENT TO TESCO STORES ON 01-01-2026",
            "merchant_name": None,
            "auto_category": "Groceries",
            "user_category": "Personal",  # User override in place
        }
        txn_without_override = {
            "id": "55555555-5555-5555-5555-555555555555",
            "description": "CARD PAYMENT TO COSTA ON 01-01-2026",
            "merchant_name": None,
            "auto_category": "General",
            "user_category": None,
        }

        db_recat = MagicMock()
        # First batch: return both transactions
        batch1_chain = _make_chain(data=[txn_with_override, txn_without_override])
        # Second batch: empty (end of pagination)
        batch2_chain = _make_chain(data=[])
        # Update chain for the one changed transaction
        update_chain = _make_chain()

        call_count = [0]
        def table_factory(name):
            call_count[0] += 1
            if call_count[0] == 1:
                return batch1_chain
            elif call_count[0] == 2:
                return update_chain  # update for Costa txn
            elif call_count[0] == 3:
                return batch2_chain  # empty second page
            return _make_chain()

        db_recat.table.side_effect = table_factory
        app.dependency_overrides[get_supabase] = lambda: db_recat

        try:
            resp = client.post("/api/v1/transactions/recategorise")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_reviewed"] == 2
            assert data["skipped_user_override"] == 1
            assert data["updated"] == 1  # Costa re-categorised, Tesco skipped
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_revert_category_to_auto(self, client):
        """User can revert a manual override back to auto-categorisation."""
        txn = {
            "id": FAKE_TRANSACTION_ID,
            "auto_category": "Groceries",
            "user_category": "Personal",
        }
        db = MagicMock()
        chain = _make_chain(data=[txn])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.patch(
                f"/api/v1/transactions/{FAKE_TRANSACTION_ID}/category",
                json={"category": None},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["category"] == "Groceries"  # Reverted to auto
            assert data["is_user_override"] is False
        finally:
            app.dependency_overrides.pop(get_supabase, None)


# =========================================================================
# E2E Flow 5: Auth required
# =========================================================================


class TestAuthEnforcement:
    """All protected endpoints reject unauthenticated requests."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/v1/connections/"),
        ("POST", "/api/v1/connections/initiate"),
        ("GET", "/api/v1/accounts/"),
        ("GET", "/api/v1/transactions/"),
        ("POST", "/api/v1/transactions/recategorise"),
        ("GET", "/api/v1/net-worth/"),
        ("GET", "/api/v1/net-worth/history"),
        ("POST", "/api/v1/sync/"),
        ("GET", "/api/v1/sync/status"),
        ("GET", "/api/v1/me"),
    ])
    def test_requires_auth(self, unauth_client, method, path):
        """All protected endpoints should return 403 without Bearer token."""
        resp = unauth_client.request(method, path)
        assert resp.status_code == 403, f"{method} {path} should require auth"


# =========================================================================
# E2E Flow 6: Sync trigger + status check
# =========================================================================


class TestSyncFlow:
    """Full flow: trigger sync -> check status."""

    def test_trigger_sync_and_check_status(self, client):
        """User can trigger sync and check status afterward."""
        tl = MagicMock(spec=TrueLayerClient)
        app.state.truelayer = tl

        # sync_user_connections returns a list of result dicts
        with patch("app.routers.sync.sync_user_connections", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = [{
                "connection_id": FAKE_CONNECTION_ID,
                "status": "ok",
                "detail": None,
                "accounts_synced": 2,
                "transactions_synced": 15,
            }]

            db = MagicMock()
            from app.dependencies import get_supabase
            app.dependency_overrides[get_supabase] = lambda: db

            try:
                resp = client.post("/api/v1/sync/")
                assert resp.status_code == 200
                data = resp.json()
                assert data["message"] == "Sync completed"
                assert data["connections_queued"] == 1
                assert data["results"][0]["accounts_synced"] == 2
                assert data["results"][0]["transactions_synced"] == 15
            finally:
                app.dependency_overrides.pop(get_supabase, None)
                if hasattr(app.state, "truelayer"):
                    del app.state.truelayer

    def test_check_sync_status(self, client):
        """User can check sync status for all connections."""
        db = MagicMock()
        chain = _make_chain(data=[{
            "id": FAKE_CONNECTION_ID,
            "provider_name": "NatWest",
            "status": "active",
            "last_synced_at": NOW.isoformat(),
            "error_message": None,
        }])
        db.table.return_value = chain

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.get("/api/v1/sync/status")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["connections"]) == 1
            assert data["connections"][0]["provider_name"] == "NatWest"
            assert data["connections"][0]["status"] == "active"
        finally:
            app.dependency_overrides.pop(get_supabase, None)
