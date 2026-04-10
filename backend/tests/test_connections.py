"""
Tests for the connections router.

Uses FastAPI TestClient with mocked dependencies.
Covers:
- GET  /api/v1/connections/callback — browser redirect from TrueLayer
- POST /api/v1/connections/callback — mobile app sends code
- POST /api/v1/connections/initiate — generate auth URL
- GET  /api/v1/connections          — list connections
- DELETE /api/v1/connections/{id}   — delete connection
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.main import app
from app.services.truelayer import TrueLayerClient, TrueLayerError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "user-conn-123"
FAKE_CONNECTION_ID = str(uuid4())

# Minimal mock token exchange response
FAKE_TOKEN_DATA = {
    "access_token": "at-test-123",
    "refresh_token": "rt-test-456",
    "expires_in": 3600,
    "token_type": "Bearer",
    "token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
}

# Minimal mock /data/v1/me response
FAKE_METADATA = {
    "results": [{
        "credentials_id": "cred-123",
        "provider": {
            "provider_id": "ob-mock",
            "display_name": "Mock Bank",
        },
        "consent_created_at": "2026-03-19T10:00:00Z",
        "consent_expires_at": "2026-06-17T10:00:00Z",
    }],
}

# Minimal mock DB row returned by insert
FAKE_CONNECTION_ROW = {
    "id": FAKE_CONNECTION_ID,
    "user_id": FAKE_USER_ID,
    "provider_id": "ob-mock",
    "provider_name": "Mock Bank",
    "status": "active",
    "last_synced_at": None,
    "consent_created_at": "2026-03-19T10:00:00+00:00",
    "consent_expires_at": "2026-06-17T10:00:00+00:00",
    "error_message": None,
    "created_at": "2026-03-24T10:00:00+00:00",
}


def _mock_supabase(data=None, raise_error=False):
    """Return a mock supabase client with chainable query builder."""
    db = MagicMock()
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.insert.return_value = chain
    chain.delete.return_value = chain

    if raise_error:
        chain.execute.side_effect = APIError({"message": "DB connection failed"})
    else:
        result = MagicMock()
        result.data = data if data is not None else []
        chain.execute.return_value = result

    db.table.return_value = chain
    return db


def _mock_truelayer_client(
    exchange_code_result=None,
    metadata_result=None,
    exchange_code_error=None,
    metadata_error=None,
):
    """Return a mock TrueLayerClient with configurable behavior."""
    tl = MagicMock(spec=TrueLayerClient)
    tl._pending_states = {}

    if exchange_code_error:
        tl.exchange_code = AsyncMock(side_effect=exchange_code_error)
    else:
        tl.exchange_code = AsyncMock(
            return_value=exchange_code_result or FAKE_TOKEN_DATA
        )

    if metadata_error:
        tl.get_connection_metadata = AsyncMock(side_effect=metadata_error)
    else:
        tl.get_connection_metadata = AsyncMock(
            return_value=metadata_result or FAKE_METADATA
        )

    return tl


@pytest.fixture
def client():
    """TestClient with auth dependency overridden."""
    from app.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: FAKE_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client():
    """TestClient without auth override (no Bearer token)."""
    return TestClient(app)


def _set_truelayer(tl):
    """Set app.state.truelayer directly (lifespan doesn't run in TestClient)."""
    app.state.truelayer = tl


def _clear_truelayer():
    """Remove app.state.truelayer after test."""
    if hasattr(app.state, "truelayer"):
        del app.state.truelayer


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/connections/callback (browser redirect)
# ---------------------------------------------------------------------------


class TestGetCallback:
    """Tests for the browser-based OAuth callback (GET)."""

    def test_success_returns_html_with_provider_name(self, unauth_client):
        tl = _mock_truelayer_client()
        tl.validate_state = MagicMock(return_value=FAKE_USER_ID)
        db = _mock_supabase(data=[FAKE_CONNECTION_ROW])
        _set_truelayer(tl)

        try:
            with (
                patch("app.routers.connections.get_supabase", return_value=db),
                patch("app.routers.connections.encrypt_token", return_value="encrypted"),
            ):
                resp = unauth_client.get(
                    "/api/v1/connections/callback",
                    params={"code": "auth-code-123", "state": "valid-state"},
                )

            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "Mock Bank" in resp.text
            assert "Connected" in resp.text
        finally:
            _clear_truelayer()

    def test_invalid_state_returns_400(self, unauth_client):
        tl = _mock_truelayer_client()
        tl.validate_state = MagicMock(return_value=None)
        _set_truelayer(tl)

        try:
            resp = unauth_client.get(
                "/api/v1/connections/callback",
                params={"code": "auth-code-123", "state": "bad-state"},
            )
            assert resp.status_code == 400
            assert "Invalid or expired session" in resp.text
        finally:
            _clear_truelayer()

    def test_empty_state_returns_400(self, unauth_client):
        tl = _mock_truelayer_client()
        tl.validate_state = MagicMock(return_value=None)
        _set_truelayer(tl)

        try:
            resp = unauth_client.get(
                "/api/v1/connections/callback",
                params={"code": "auth-code-123"},
            )
            assert resp.status_code == 400
        finally:
            _clear_truelayer()

    def test_missing_code_returns_422(self, unauth_client):
        """code is a required query parameter."""
        tl = _mock_truelayer_client()
        _set_truelayer(tl)

        try:
            resp = unauth_client.get("/api/v1/connections/callback")
            assert resp.status_code == 422
        finally:
            _clear_truelayer()

    def test_token_exchange_failure_returns_error_html(self, unauth_client):
        tl = _mock_truelayer_client(
            exchange_code_error=TrueLayerError("exchange failed", status_code=400),
        )
        tl.validate_state = MagicMock(return_value=FAKE_USER_ID)
        _set_truelayer(tl)

        try:
            with (
                patch("app.routers.connections.get_supabase", return_value=_mock_supabase()),
            ):
                resp = unauth_client.get(
                    "/api/v1/connections/callback",
                    params={"code": "bad-code", "state": "valid-state"},
                )

            assert resp.status_code == 502
            assert "Connection Failed" in resp.text
        finally:
            _clear_truelayer()

    def test_metadata_failure_returns_error_html(self, unauth_client):
        tl = _mock_truelayer_client(
            metadata_error=TrueLayerError("metadata failed", status_code=500),
        )
        tl.validate_state = MagicMock(return_value=FAKE_USER_ID)
        _set_truelayer(tl)

        try:
            with (
                patch("app.routers.connections.get_supabase", return_value=_mock_supabase()),
            ):
                resp = unauth_client.get(
                    "/api/v1/connections/callback",
                    params={"code": "auth-code", "state": "valid-state"},
                )

            assert resp.status_code == 502
            assert "Connection Failed" in resp.text
        finally:
            _clear_truelayer()

    def test_db_insert_failure_returns_error_html(self, unauth_client):
        tl = _mock_truelayer_client()
        tl.validate_state = MagicMock(return_value=FAKE_USER_ID)
        db = _mock_supabase(raise_error=True)
        _set_truelayer(tl)

        try:
            with (
                patch("app.routers.connections.get_supabase", return_value=db),
                patch("app.routers.connections.encrypt_token", return_value="encrypted"),
            ):
                resp = unauth_client.get(
                    "/api/v1/connections/callback",
                    params={"code": "auth-code", "state": "valid-state"},
                )

            assert resp.status_code == 500
            assert "Connection Failed" in resp.text
        finally:
            _clear_truelayer()

    def test_no_auth_required(self, unauth_client):
        """GET callback should NOT require a Bearer token."""
        tl = _mock_truelayer_client()
        tl.validate_state = MagicMock(return_value=FAKE_USER_ID)
        db = _mock_supabase(data=[FAKE_CONNECTION_ROW])
        _set_truelayer(tl)

        try:
            with (
                patch("app.routers.connections.get_supabase", return_value=db),
                patch("app.routers.connections.encrypt_token", return_value="encrypted"),
            ):
                # No Authorization header — should still work
                resp = unauth_client.get(
                    "/api/v1/connections/callback",
                    params={"code": "auth-code", "state": "valid-state"},
                )

            # Should NOT be 401/403
            assert resp.status_code == 200
        finally:
            _clear_truelayer()


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/connections/callback (mobile app)
# ---------------------------------------------------------------------------


class TestPostCallback:
    """Tests for the mobile app OAuth callback (POST)."""

    def test_success_returns_connection(self, client):
        tl = _mock_truelayer_client()
        db = _mock_supabase(data=[FAKE_CONNECTION_ROW])
        _set_truelayer(tl)

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.encrypt_token", return_value="encrypted"):
                resp = client.post(
                    "/api/v1/connections/callback",
                    json={"code": "auth-code-123"},
                )

            assert resp.status_code == 201
            data = resp.json()
            assert data["connection_id"] == FAKE_CONNECTION_ID
            assert data["provider_name"] == "Mock Bank"
            assert data["status"] == "active"
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_requires_auth(self, unauth_client):
        """POST callback requires Bearer token."""
        resp = unauth_client.post(
            "/api/v1/connections/callback",
            json={"code": "auth-code-123"},
        )
        # HTTPBearer returns 403 when header is missing
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/connections/initiate
# ---------------------------------------------------------------------------


class TestInitiateConnection:
    """Tests for auth URL generation."""

    def test_returns_auth_url(self, client):
        tl = MagicMock(spec=TrueLayerClient)
        tl.build_auth_url.return_value = (
            "https://auth.truelayer-sandbox.com/?response_type=code&client_id=test",
            "state-nonce-123",
        )
        _set_truelayer(tl)

        try:
            resp = client.post("/api/v1/connections/initiate")

            assert resp.status_code == 200
            data = resp.json()
            assert "auth_url" in data
            assert data["auth_url"].startswith("https://auth.truelayer-sandbox.com/")
        finally:
            _clear_truelayer()

    def test_requires_auth(self, unauth_client):
        resp = unauth_client.post("/api/v1/connections/initiate")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: POST /api/v1/connections/{id}/reconnect
# ---------------------------------------------------------------------------


FAKE_CONNECTION_EXPIRING = {
    "id": FAKE_CONNECTION_ID,
    "user_id": FAKE_USER_ID,
    "status": "expiring_soon",
    "refresh_token": "encrypted-refresh-token",
    "provider_name": "Mock Bank",
}

FAKE_CONNECTION_EXPIRED = {
    "id": FAKE_CONNECTION_ID,
    "user_id": FAKE_USER_ID,
    "status": "expired",
    "refresh_token": "encrypted-refresh-token",
    "provider_name": "Mock Bank",
}

FAKE_CONNECTION_ACTIVE = {
    "id": FAKE_CONNECTION_ID,
    "user_id": FAKE_USER_ID,
    "status": "active",
    "refresh_token": "encrypted-refresh-token",
    "provider_name": "Mock Bank",
}


class TestReconnectConnection:
    """Tests for POST /api/v1/connections/{id}/reconnect."""

    def test_no_action_needed_resets_to_active(self, client):
        """Extend returns no_action_needed — tokens updated, status reset."""
        tl = _mock_truelayer_client()
        tl.extend_connection = AsyncMock(return_value={
            "action_needed": "no_action_needed",
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": 3600,
            "token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        })
        # get_connection_metadata already mocked in _mock_truelayer_client
        _set_truelayer(tl)

        # Mock DB: first call returns the connection, second call is update
        db = _mock_supabase(data=[FAKE_CONNECTION_EXPIRING])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with (
                patch("app.routers.connections.decrypt_token", return_value="decrypted-rt"),
                patch("app.routers.connections.encrypt_token", return_value="encrypted"),
            ):
                resp = client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")

            assert resp.status_code == 200
            data = resp.json()
            assert data["action"] == "no_action_needed"
            assert data["auth_url"] is None
            assert "renewed successfully" in data["message"]
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_authentication_needed_returns_auth_url(self, client):
        """Extend returns authentication_needed — auth URL returned."""
        tl = _mock_truelayer_client()
        tl.extend_connection = AsyncMock(return_value={
            "action_needed": "authentication_needed",
            "auth_url": "https://auth.truelayer-sandbox.com/reauth?token=abc",
        })
        _set_truelayer(tl)

        db = _mock_supabase(data=[FAKE_CONNECTION_EXPIRING])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted-rt"):
                resp = client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")

            assert resp.status_code == 200
            data = resp.json()
            assert data["action"] == "authentication_needed"
            assert data["auth_url"] == "https://auth.truelayer-sandbox.com/reauth?token=abc"
            assert "re-authenticate" in data["message"]
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_expired_connection_allowed(self, client):
        """Expired connections should also be reconnectable."""
        tl = _mock_truelayer_client()
        tl.extend_connection = AsyncMock(return_value={
            "action_needed": "authentication_needed",
            "auth_url": "https://auth.truelayer-sandbox.com/reauth",
        })
        _set_truelayer(tl)

        db = _mock_supabase(data=[FAKE_CONNECTION_EXPIRED])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted-rt"):
                resp = client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")

            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_active_connection_rejected(self, client):
        """Active connections don't need reconnection — 400."""
        tl = _mock_truelayer_client()
        _set_truelayer(tl)

        db = _mock_supabase(data=[FAKE_CONNECTION_ACTIVE])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")

            assert resp.status_code == 400
            assert "active" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_connection_not_found(self, client):
        """Non-existent connection → 404."""
        tl = _mock_truelayer_client()
        _set_truelayer(tl)

        db = _mock_supabase(data=[])  # Empty result

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            resp = client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_truelayer_extend_failure_returns_502(self, client):
        """TrueLayer extend fails → 502."""
        tl = _mock_truelayer_client()
        tl.extend_connection = AsyncMock(
            side_effect=TrueLayerError("extend failed", status_code=400)
        )
        _set_truelayer(tl)

        db = _mock_supabase(data=[FAKE_CONNECTION_EXPIRING])

        from app.dependencies import get_supabase
        app.dependency_overrides[get_supabase] = lambda: db

        try:
            with patch("app.routers.connections.decrypt_token", return_value="decrypted-rt"):
                resp = client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")

            assert resp.status_code == 502
            assert "renew" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_supabase, None)
            _clear_truelayer()

    def test_requires_auth(self, unauth_client):
        """Reconnect requires Bearer token."""
        resp = unauth_client.post(f"/api/v1/connections/{FAKE_CONNECTION_ID}/reconnect")
        assert resp.status_code == 403
