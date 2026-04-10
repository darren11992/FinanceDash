"""
Tests for the TrueLayer Data API methods added in Sprint 3.

Covers:
- get_accounts, get_account_balance, get_transactions
- get_cards, get_card_balance, get_card_transactions
- _get_data helper (error handling, retry/backoff logic)
- All methods raise TrueLayerError on non-200 responses

Uses httpx mock transport to avoid real HTTP calls.
asyncio.sleep is patched to zero in tests that trigger retries.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.truelayer import TrueLayerClient, TrueLayerError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_client(handler):
    """
    Create a TrueLayerClient with a custom httpx transport handler.

    The handler receives (request) and should return an httpx.Response.
    """
    transport = httpx.MockTransport(handler)
    client = TrueLayerClient(
        client_id="test-id",
        client_secret="test-secret",
        redirect_uri="http://localhost/callback",
        auth_base_url="https://auth.truelayer-sandbox.com",
        data_base_url="https://api.truelayer-sandbox.com",
    )
    # Replace the internal httpx client with one using mock transport.
    client._http = httpx.AsyncClient(transport=transport)
    return client


# ---------------------------------------------------------------------------
# get_accounts
# ---------------------------------------------------------------------------


class TestGetAccounts:

    @pytest.mark.asyncio
    async def test_returns_accounts_list(self):
        accounts_data = [
            {"account_id": "acct-1", "display_name": "Current", "currency": "GBP"},
            {"account_id": "acct-2", "display_name": "Savings", "currency": "GBP"},
        ]

        def handler(request: httpx.Request):
            assert "/data/v1/accounts" in str(request.url)
            assert "Bearer" in request.headers["authorization"]
            return httpx.Response(200, json={"results": accounts_data})

        client = _make_client(handler)
        result = await client.get_accounts("test-token")

        assert len(result) == 2
        assert result[0]["account_id"] == "acct-1"
        assert result[1]["display_name"] == "Savings"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"results": []})

        client = _make_client(handler)
        result = await client.get_accounts("test-token")
        assert result == []

    @pytest.mark.asyncio
    async def test_error_raises_truelayer_error(self):
        def handler(request: httpx.Request):
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError) as exc_info:
            await client.get_accounts("bad-token")
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_account_balance
# ---------------------------------------------------------------------------


class TestGetAccountBalance:

    @pytest.mark.asyncio
    async def test_returns_balance_dict(self):
        balance = {"current": 1500.00, "available": 1450.00, "currency": "GBP"}

        def handler(request: httpx.Request):
            assert "/data/v1/accounts/acct-1/balance" in str(request.url)
            return httpx.Response(200, json={"results": [balance]})

        client = _make_client(handler)
        result = await client.get_account_balance("test-token", "acct-1")

        assert result["current"] == 1500.00
        assert result["available"] == 1450.00

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_dict(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"results": []})

        client = _make_client(handler)
        result = await client.get_account_balance("test-token", "acct-1")
        assert result == {}

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_error_raises_truelayer_error(self, mock_sleep):
        """500 is retryable — retries exhaust, then raises."""
        def handler(request: httpx.Request):
            return httpx.Response(500, json={"error": "internal"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError) as exc_info:
            await client.get_account_balance("token", "acct-1")
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get_transactions
# ---------------------------------------------------------------------------


class TestGetTransactions:

    @pytest.mark.asyncio
    async def test_returns_transactions_list(self):
        txns = [
            {"transaction_id": "txn-1", "amount": -10.00, "description": "Coffee"},
            {"transaction_id": "txn-2", "amount": -25.00, "description": "Lunch"},
        ]

        def handler(request: httpx.Request):
            assert "/data/v1/accounts/acct-1/transactions" in str(request.url)
            assert "from=2026-01-01" in str(request.url)
            assert "to=2026-03-24" in str(request.url)
            return httpx.Response(200, json={"results": txns})

        client = _make_client(handler)
        result = await client.get_transactions("test-token", "acct-1", "2026-01-01", "2026-03-24")

        assert len(result) == 2
        assert result[0]["transaction_id"] == "txn-1"

    @pytest.mark.asyncio
    async def test_empty_results(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"results": []})

        client = _make_client(handler)
        result = await client.get_transactions("token", "acct-1", "2026-01-01", "2026-03-24")
        assert result == []

    @pytest.mark.asyncio
    async def test_error_raises_truelayer_error(self):
        def handler(request: httpx.Request):
            return httpx.Response(403, json={"error": "forbidden"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError):
            await client.get_transactions("token", "acct-1", "2026-01-01", "2026-03-24")


# ---------------------------------------------------------------------------
# get_cards
# ---------------------------------------------------------------------------


class TestGetCards:

    @pytest.mark.asyncio
    async def test_returns_cards_list(self):
        cards = [{"account_id": "card-1", "display_name": "Amex Platinum", "currency": "GBP"}]

        def handler(request: httpx.Request):
            assert "/data/v1/cards" in str(request.url)
            return httpx.Response(200, json={"results": cards})

        client = _make_client(handler)
        result = await client.get_cards("test-token")

        assert len(result) == 1
        assert result[0]["display_name"] == "Amex Platinum"

    @pytest.mark.asyncio
    async def test_error_raises_truelayer_error(self):
        def handler(request: httpx.Request):
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError):
            await client.get_cards("bad-token")


# ---------------------------------------------------------------------------
# get_card_balance
# ---------------------------------------------------------------------------


class TestGetCardBalance:

    @pytest.mark.asyncio
    async def test_returns_balance_dict(self):
        balance = {"current": -350.00, "available": 4650.00, "currency": "GBP"}

        def handler(request: httpx.Request):
            assert "/data/v1/cards/card-1/balance" in str(request.url)
            return httpx.Response(200, json={"results": [balance]})

        client = _make_client(handler)
        result = await client.get_card_balance("test-token", "card-1")

        assert result["current"] == -350.00

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_dict(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"results": []})

        client = _make_client(handler)
        result = await client.get_card_balance("token", "card-1")
        assert result == {}


# ---------------------------------------------------------------------------
# get_card_transactions
# ---------------------------------------------------------------------------


class TestGetCardTransactions:

    @pytest.mark.asyncio
    async def test_returns_transactions_list(self):
        txns = [{"transaction_id": "ctxn-1", "amount": -99.99, "description": "Amazon"}]

        def handler(request: httpx.Request):
            assert "/data/v1/cards/card-1/transactions" in str(request.url)
            return httpx.Response(200, json={"results": txns})

        client = _make_client(handler)
        result = await client.get_card_transactions("token", "card-1", "2026-01-01", "2026-03-24")

        assert len(result) == 1
        assert result[0]["amount"] == -99.99

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_error_raises_truelayer_error(self, mock_sleep):
        """429 is retryable — retries exhaust, then raises."""
        def handler(request: httpx.Request):
            return httpx.Response(429, json={"error": "rate limited"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError) as exc_info:
            await client.get_card_transactions("token", "card-1", "2026-01-01", "2026-03-24")
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# _get_data helper (error handling edge cases)
# ---------------------------------------------------------------------------


class TestGetDataHelper:

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_non_json_error_response(self, mock_sleep):
        """Non-JSON error body should not crash the error handler."""
        def handler(request: httpx.Request):
            return httpx.Response(
                502,
                content=b"Bad Gateway",
                headers={"content-type": "text/plain"},
            )

        client = _make_client(handler)
        with pytest.raises(TrueLayerError) as exc_info:
            await client._get_data("token", "/data/v1/accounts")
        assert exc_info.value.status_code == 502
        assert exc_info.value.body == {}


# ---------------------------------------------------------------------------
# Retry / Backoff Logic
# ---------------------------------------------------------------------------


class TestRetryBackoff:
    """Tests for the retry + exponential backoff in _get_data()."""

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_500_then_succeeds(self, mock_sleep):
        """Should retry on 500 and return data when a subsequent attempt succeeds."""
        call_count = 0

        def handler(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(500, json={"error": "internal"})
            return httpx.Response(200, json={"results": [{"id": "ok"}]})

        client = _make_client(handler)
        result = await client._get_data("token", "/data/v1/accounts")

        assert result == {"results": [{"id": "ok"}]}
        assert call_count == 3  # 2 failures + 1 success
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_429_with_retry_after(self, mock_sleep):
        """Should respect Retry-After header on 429 responses."""
        call_count = 0

        def handler(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    429,
                    json={"error": "rate limited"},
                    headers={"Retry-After": "5"},
                )
            return httpx.Response(200, json={"results": []})

        client = _make_client(handler)
        result = await client._get_data("token", "/data/v1/accounts")

        assert result == {"results": []}
        assert call_count == 2
        # First retry should use Retry-After value of 5.
        mock_sleep.assert_awaited_once_with(5.0)

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_429_without_retry_after_uses_backoff(self, mock_sleep):
        """429 without Retry-After header should use exponential backoff."""
        call_count = 0

        def handler(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={"results": []})

        client = _make_client(handler)
        await client._get_data("token", "/data/v1/accounts")

        # Backoff for attempt 0 = 1 * 4^0 = 1.0s
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff_delays(self, mock_sleep):
        """Verify backoff delays: 1s, 4s, 16s across attempts."""
        def handler(request: httpx.Request):
            return httpx.Response(503, json={"error": "unavailable"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError):
            await client._get_data("token", "/data/v1/accounts")

        # MAX_RETRIES=3, so 4 total attempts, 3 sleeps.
        assert mock_sleep.call_count == 3
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 4.0, 16.0]

    @pytest.mark.asyncio
    async def test_non_retryable_status_raises_immediately(self):
        """Non-retryable errors (4xx except 429) should raise without retrying."""
        call_count = 0

        def handler(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(403, json={"error": "forbidden"})

        client = _make_client(handler)
        with pytest.raises(TrueLayerError) as exc_info:
            await client._get_data("token", "/data/v1/accounts")

        assert exc_info.value.status_code == 403
        assert call_count == 1  # No retries

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_timeout_exception(self, mock_sleep):
        """httpx.TimeoutException should trigger retry with backoff."""
        call_count = 0

        def handler(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise httpx.TimeoutException("Connection timed out")
            return httpx.Response(200, json={"results": [{"id": "ok"}]})

        client = _make_client(handler)
        result = await client._get_data("token", "/data/v1/accounts")

        assert result == {"results": [{"id": "ok"}]}
        assert call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_timeout_exhausts_retries(self, mock_sleep):
        """All timeouts should raise TrueLayerError after retries exhausted."""
        def handler(request: httpx.Request):
            raise httpx.TimeoutException("Connection timed out")

        client = _make_client(handler)
        with pytest.raises(TrueLayerError) as exc_info:
            await client._get_data("token", "/data/v1/accounts")

        assert exc_info.value.status_code is None
        assert "timed out" in str(exc_info.value)
        assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retryable_status_codes_all_retry(self, mock_sleep):
        """All status codes in RETRYABLE_STATUS_CODES should trigger retries."""
        for status in [500, 502, 503, 504]:
            mock_sleep.reset_mock()
            call_count = 0

            def handler(request: httpx.Request, _status=status):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return httpx.Response(_status, json={"error": "err"})
                return httpx.Response(200, json={"results": []})

            client = _make_client(handler)
            result = await client._get_data("token", "/data/v1/accounts")

            assert result == {"results": []}, f"Failed for status {status}"
            assert call_count == 2, f"Expected 2 attempts for {status}"

    def test_backoff_delay_formula(self):
        """_backoff_delay should return base * multiplier^attempt."""
        client = _make_client(lambda r: httpx.Response(200))
        assert client._backoff_delay(0) == 1.0   # 1 * 4^0
        assert client._backoff_delay(1) == 4.0   # 1 * 4^1
        assert client._backoff_delay(2) == 16.0  # 1 * 4^2

    def test_parse_retry_after_valid(self):
        """_parse_retry_after should parse integer Retry-After header."""
        client = _make_client(lambda r: httpx.Response(200))
        resp = httpx.Response(429, headers={"Retry-After": "7"})
        assert client._parse_retry_after(resp) == 7.0

    def test_parse_retry_after_missing(self):
        """Missing Retry-After header should return 0."""
        client = _make_client(lambda r: httpx.Response(200))
        resp = httpx.Response(429)
        assert client._parse_retry_after(resp) == 0

    def test_parse_retry_after_invalid(self):
        """Non-numeric Retry-After should return 0."""
        client = _make_client(lambda r: httpx.Response(200))
        resp = httpx.Response(429, headers={"Retry-After": "not-a-number"})
        assert client._parse_retry_after(resp) == 0
