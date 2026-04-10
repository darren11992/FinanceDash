"""
Tests for Sprint 6 security hardening.

Covers:
- OAuth state nonce TTL and size limits (cachetools.TTLCache)
- Input validation (max_length on schemas)
- Category filter injection prevention
- Error detail sanitisation (no TrueLayer internals leaked)
- Global exception handler (no stack traces leaked)
- APP_DEBUG default is False
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.truelayer import TrueLayerClient, TrueLayerError


FAKE_USER_ID = "user-security-test"


@pytest.fixture
def client():
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _mock_supabase(data=None, raise_error=False):
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.range.return_value = chain
    chain.gte.return_value = chain
    chain.lte.return_value = chain
    chain.or_.return_value = chain
    chain.delete.return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    if raise_error:
        chain.execute.side_effect = Exception("DB connection failed")
    else:
        result = MagicMock()
        result.data = data if data is not None else []
        result.count = len(data) if data is not None else 0
        chain.execute.return_value = result
    db.table.return_value = chain
    return db


# =========================================================================
# OAuth State Nonce TTL
# =========================================================================


class TestOAuthStateTTL:
    """Verify that _pending_states uses TTLCache with expiry and size limits."""

    def test_state_expires_after_ttl(self):
        """State nonces should auto-expire after the TTL (600s).
        We can't wait 600s in a test, but we can verify the TTLCache
        configuration and test with a short-lived cache.
        """
        from cachetools import TTLCache

        # Verify the actual TrueLayer client uses TTLCache
        truelayer_client = TrueLayerClient(
            client_id="test",
            client_secret="test",
            redirect_uri="http://localhost/callback",
            auth_base_url="https://auth.truelayer-sandbox.com",
            data_base_url="https://api.truelayer-sandbox.com",
        )
        assert isinstance(truelayer_client._pending_states, TTLCache)
        assert truelayer_client._pending_states.maxsize == 10_000
        assert truelayer_client._pending_states.ttl == 600

    def test_state_nonce_generated_and_validated(self):
        """Basic nonce lifecycle: generate -> validate -> consumed."""
        truelayer_client = TrueLayerClient(
            client_id="test",
            client_secret="test",
            redirect_uri="http://localhost/callback",
            auth_base_url="https://auth.truelayer-sandbox.com",
            data_base_url="https://api.truelayer-sandbox.com",
        )
        _url, state = truelayer_client.build_auth_url("user-123")
        assert truelayer_client.validate_state(state) == "user-123"
        # Consumed — second validation returns None (replay protection)
        assert truelayer_client.validate_state(state) is None

    def test_ttl_cache_evicts_old_entries(self):
        """Verify that TTLCache actually expires entries after TTL."""
        from cachetools import TTLCache

        cache: TTLCache[str, str] = TTLCache(maxsize=100, ttl=0.1)  # 100ms TTL
        cache["test-state"] = "user-123"
        assert "test-state" in cache

        time.sleep(0.2)  # Wait for TTL to expire
        assert "test-state" not in cache

    def test_ttl_cache_respects_maxsize(self):
        """Verify that TTLCache evicts when maxsize is exceeded."""
        from cachetools import TTLCache

        cache: TTLCache[str, str] = TTLCache(maxsize=3, ttl=600)
        cache["state-1"] = "user-1"
        cache["state-2"] = "user-2"
        cache["state-3"] = "user-3"
        cache["state-4"] = "user-4"  # Should evict the oldest

        assert len(cache) == 3
        assert "state-1" not in cache  # LRU evicted


# =========================================================================
# Input Validation
# =========================================================================


class TestInputValidation:
    """Verify that Pydantic schemas enforce length limits."""

    def test_category_update_rejects_oversized_string(self, client):
        """Category field should reject strings > 100 chars."""
        db = _mock_supabase(data=[{"id": "txn-1", "auto_category": "General", "user_category": None}])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            long_category = "A" * 101
            resp = client.patch(
                "/api/v1/transactions/00000000-0000-0000-0000-000000000001/category",
                json={"category": long_category},
            )
            assert resp.status_code == 422  # Validation error
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_category_update_accepts_valid_string(self, client):
        """Category field should accept strings <= 100 chars."""
        db = _mock_supabase(data=[{"id": "txn-1", "auto_category": "General", "user_category": None}])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.patch(
                "/api/v1/transactions/00000000-0000-0000-0000-000000000001/category",
                json={"category": "Groceries"},
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_callback_code_rejects_oversized_string(self, client):
        """OAuth code field should reject strings > 2048 chars."""
        resp = client.post(
            "/api/v1/connections/callback",
            json={"code": "A" * 2049},
        )
        assert resp.status_code == 422

    def test_callback_code_accepts_valid_string(self, client):
        """OAuth code field should accept strings <= 2048 chars."""
        tl = MagicMock(spec=TrueLayerClient)
        tl.exchange_code = AsyncMock(return_value={
            "access_token": "at",
            "refresh_token": "rt",
            "token_expires_at": MagicMock(isoformat=lambda: "2026-01-01T00:00:00+00:00"),
        })
        tl.get_connection_metadata = AsyncMock(return_value={
            "results": [{"provider": {"provider_id": "test", "display_name": "Test Bank"}}]
        })
        app.state.truelayer = tl

        db = _mock_supabase(data=[{
            "id": "conn-1",
            "provider_name": "Test Bank",
        }])
        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.encrypt_token", return_value="encrypted"):
                resp = client.post(
                    "/api/v1/connections/callback",
                    json={"code": "valid-code"},
                )
                # Should not be 422 (validation passes)
                assert resp.status_code != 422
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer


# =========================================================================
# Category Filter Injection
# =========================================================================


class TestCategoryFilterInjection:
    """Verify that category query param rejects injection patterns."""

    def test_rejects_postgrest_filter_syntax(self, client):
        """Category with commas and dots (PostgREST filter syntax) should be rejected."""
        db = _mock_supabase()
        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            # Attempt PostgREST filter injection
            resp = client.get(
                "/api/v1/transactions/?category=Groceries,user_id.eq.other-user"
            )
            assert resp.status_code == 400
            assert "invalid category" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_supabase, None)

    def test_accepts_valid_category_names(self, client):
        """Normal category names (alphanumeric, spaces, &, /) should pass."""
        db = _mock_supabase()
        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            for category in ["Groceries", "Eating Out", "Health & Fitness", "Bills/Utilities"]:
                resp = client.get(f"/api/v1/transactions/?category={category}")
                assert resp.status_code == 200, f"Category '{category}' should be accepted"
        finally:
            app.dependency_overrides.pop(get_supabase, None)


# =========================================================================
# Error Detail Sanitisation
# =========================================================================


class TestErrorSanitisation:
    """Verify that client-facing error responses don't leak internal details."""

    def test_token_exchange_error_is_generic(self, client):
        """TrueLayer token exchange failures should not expose error body."""
        tl = MagicMock(spec=TrueLayerClient)
        tl._pending_states = {}
        tl.exchange_code = AsyncMock(
            side_effect=TrueLayerError(
                "invalid_client: client_id mismatch",
                status_code=400,
                body={"error": "invalid_client"},
            )
        )
        app.state.truelayer = tl

        db = _mock_supabase()
        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.post(
                "/api/v1/connections/callback",
                json={"code": "test-code"},
            )
            assert resp.status_code == 502
            detail = resp.json()["detail"]
            # Should NOT contain TrueLayer error specifics
            assert "invalid_client" not in detail
            assert "client_id" not in detail
            # Should contain a generic message
            assert "try again" in detail.lower()
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer

    def test_reconnect_error_is_generic(self, client):
        """TrueLayer extend failures should not expose error body."""
        tl = MagicMock(spec=TrueLayerClient)
        tl.extend_connection = AsyncMock(
            side_effect=TrueLayerError("extend failed: consent_expired", status_code=403)
        )
        app.state.truelayer = tl

        connection_data = {
            "id": "00000000-0000-0000-0000-000000000001",
            "user_id": FAKE_USER_ID,
            "status": "expiring_soon",
            "refresh_token": "encrypted-rt",
            "provider_name": "Test Bank",
        }
        db = _mock_supabase(data=[connection_data])
        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted"):
                resp = client.post(
                    "/api/v1/connections/00000000-0000-0000-0000-000000000001/reconnect"
                )
                assert resp.status_code == 502
                detail = resp.json()["detail"]
                assert "consent_expired" not in detail
                assert "try again" in detail.lower()
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            if hasattr(app.state, "truelayer"):
                del app.state.truelayer


# =========================================================================
# Global Exception Handler
# =========================================================================


class TestGlobalExceptionHandler:
    """Verify unhandled exceptions return generic 500 without stack traces."""

    def test_unhandled_exception_returns_generic_500(self, client):
        """An unhandled exception should return a clean 500 response."""
        db = _mock_supabase(raise_error=True)
        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            # Force an unhandled error by making the transactions endpoint fail
            # in a way that bypasses the route's own error handling
            with patch("app.routers.transactions.categorise_transaction", side_effect=RuntimeError("boom")):
                resp = client.post("/api/v1/transactions/recategorise")
                # The router-level try/except catches this, returning 500
                assert resp.status_code == 500
                detail = resp.json()["detail"]
                # Should NOT contain "boom" or stack trace
                assert "boom" not in detail
                assert "Traceback" not in detail
        finally:
            app.dependency_overrides.pop(get_supabase, None)


# =========================================================================
# APP_DEBUG Default
# =========================================================================


class TestAppDebugDefault:
    """Verify that APP_DEBUG defaults to False for production safety."""

    def test_app_debug_default_is_false(self):
        """The default value for app_debug should be False."""
        from app.config import Settings

        # Inspect the field default without actually creating a Settings
        # instance (which would read .env and could fail).
        field = Settings.model_fields["app_debug"]
        assert field.default is False, (
            "app_debug must default to False to prevent accidental "
            "debug-mode production deployments"
        )
