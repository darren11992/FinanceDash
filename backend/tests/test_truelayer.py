"""
Tests for the TrueLayer API client (OAuth methods).

All HTTP calls are mocked — no real TrueLayer traffic.

Verifies:
- build_auth_url() constructs correct URL with all required params
- State nonce generation and validation (CSRF protection)
- exchange_code() sends correct payload and handles success/failure
- refresh_access_token() sends correct payload and handles success/failure
- get_connection_metadata() calls /data/v1/me correctly
- Error handling for non-200 responses
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

from app.services.truelayer import TrueLayerClient, TrueLayerError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tl_client():
    """Create a TrueLayerClient pointed at sandbox URLs."""
    client = TrueLayerClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="pennyapp://callback",
        auth_base_url="https://auth.truelayer-sandbox.com",
        data_base_url="https://api.truelayer-sandbox.com",
    )
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# build_auth_url
# ---------------------------------------------------------------------------


class TestBuildAuthUrl:
    """Tests for OAuth URL construction."""

    def test_returns_url_and_state(self, tl_client: TrueLayerClient):
        auth_url, state = tl_client.build_auth_url("user-123")
        assert isinstance(auth_url, str)
        assert isinstance(state, str)
        assert len(state) > 0

    def test_url_contains_required_params(self, tl_client: TrueLayerClient):
        auth_url, _ = tl_client.build_auth_url("user-123")
        assert "response_type=code" in auth_url
        assert "client_id=test-client-id" in auth_url
        assert "redirect_uri=" in auth_url
        assert "scope=" in auth_url
        assert "state=" in auth_url

    def test_url_contains_required_scopes(self, tl_client: TrueLayerClient):
        auth_url, _ = tl_client.build_auth_url("user-123")
        for scope in ["accounts", "balance", "transactions", "cards", "offline_access"]:
            assert scope in auth_url, f"Missing scope: {scope}"

    def test_url_starts_with_auth_base(self, tl_client: TrueLayerClient):
        auth_url, _ = tl_client.build_auth_url("user-123")
        assert auth_url.startswith("https://auth.truelayer-sandbox.com/")

    def test_state_is_unique_per_call(self, tl_client: TrueLayerClient):
        _, state1 = tl_client.build_auth_url("user-123")
        _, state2 = tl_client.build_auth_url("user-123")
        assert state1 != state2

    def test_state_stored_in_pending(self, tl_client: TrueLayerClient):
        _, state = tl_client.build_auth_url("user-123")
        assert state in tl_client._pending_states
        assert tl_client._pending_states[state] == "user-123"


# ---------------------------------------------------------------------------
# validate_state
# ---------------------------------------------------------------------------


class TestValidateState:
    """Tests for state nonce validation (CSRF protection)."""

    def test_valid_state_returns_user_id(self, tl_client: TrueLayerClient):
        _, state = tl_client.build_auth_url("user-abc")
        user_id = tl_client.validate_state(state)
        assert user_id == "user-abc"

    def test_state_consumed_after_validation(self, tl_client: TrueLayerClient):
        """State should be single-use (replay protection)."""
        _, state = tl_client.build_auth_url("user-abc")
        tl_client.validate_state(state)
        # Second call should return None
        assert tl_client.validate_state(state) is None

    def test_unknown_state_returns_none(self, tl_client: TrueLayerClient):
        assert tl_client.validate_state("unknown-state") is None


# ---------------------------------------------------------------------------
# exchange_code
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_data: dict) -> httpx.Response:
    """Build a mock httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "https://mock"),
    )


class TestExchangeCode:
    """Tests for authorization code exchange."""

    @pytest.mark.asyncio
    async def test_success(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(200, {
            "access_token": "at-123",
            "refresh_token": "rt-456",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "accounts balance transactions cards offline_access",
        })

        tl_client._http.post = AsyncMock(return_value=mock_resp)

        result = await tl_client.exchange_code("auth-code-xyz")

        assert result["access_token"] == "at-123"
        assert result["refresh_token"] == "rt-456"
        assert "token_expires_at" in result
        assert isinstance(result["token_expires_at"], datetime)
        assert result["token_expires_at"].tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(200, {
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600,
        })
        tl_client._http.post = AsyncMock(return_value=mock_resp)

        await tl_client.exchange_code("my-code")

        call_kwargs = tl_client._http.post.call_args
        assert call_kwargs[0][0] == "https://auth.truelayer-sandbox.com/connect/token"
        payload = call_kwargs[1]["data"]
        assert payload["grant_type"] == "authorization_code"
        assert payload["client_id"] == "test-client-id"
        assert payload["client_secret"] == "test-client-secret"
        assert payload["code"] == "my-code"
        assert payload["redirect_uri"] == "pennyapp://callback"

    @pytest.mark.asyncio
    async def test_failure_raises_truelayer_error(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(400, {"error": "invalid_grant"})
        tl_client._http.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(TrueLayerError) as exc_info:
            await tl_client.exchange_code("bad-code")

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------


class TestRefreshAccessToken:
    """Tests for token refresh."""

    @pytest.mark.asyncio
    async def test_success(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(200, {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "expires_in": 3600,
        })
        tl_client._http.post = AsyncMock(return_value=mock_resp)

        result = await tl_client.refresh_access_token("old-rt")

        assert result["access_token"] == "new-at"
        assert result["refresh_token"] == "new-rt"
        assert isinstance(result["token_expires_at"], datetime)

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(200, {
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600,
        })
        tl_client._http.post = AsyncMock(return_value=mock_resp)

        await tl_client.refresh_access_token("my-refresh-token")

        call_kwargs = tl_client._http.post.call_args
        payload = call_kwargs[1]["data"]
        assert payload["grant_type"] == "refresh_token"
        assert payload["refresh_token"] == "my-refresh-token"
        assert payload["client_id"] == "test-client-id"
        assert payload["client_secret"] == "test-client-secret"

    @pytest.mark.asyncio
    async def test_failure_raises_truelayer_error(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(401, {"error": "invalid_token"})
        tl_client._http.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(TrueLayerError) as exc_info:
            await tl_client.refresh_access_token("expired-rt")

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_connection_metadata
# ---------------------------------------------------------------------------


class TestGetConnectionMetadata:
    """Tests for /data/v1/me fetching."""

    @pytest.mark.asyncio
    async def test_success(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(200, {
            "results": [{
                "credentials_id": "cred-123",
                "provider": {
                    "provider_id": "ob-mock",
                    "display_name": "Mock Bank",
                },
                "consent_created_at": "2026-03-19T10:00:00Z",
                "consent_expires_at": "2026-06-17T10:00:00Z",
            }],
        })
        tl_client._http.get = AsyncMock(return_value=mock_resp)

        result = await tl_client.get_connection_metadata("at-123")

        assert result["results"][0]["provider"]["provider_id"] == "ob-mock"
        # Verify auth header was sent
        call_kwargs = tl_client._http.get.call_args
        assert call_kwargs[1]["headers"]["Authorization"] == "Bearer at-123"

    @pytest.mark.asyncio
    async def test_failure_raises_truelayer_error(self, tl_client: TrueLayerClient):
        mock_resp = _mock_response(401, {"error": "unauthorized"})
        tl_client._http.get = AsyncMock(return_value=mock_resp)

        with pytest.raises(TrueLayerError) as exc_info:
            await tl_client.get_connection_metadata("bad-token")

        assert exc_info.value.status_code == 401
