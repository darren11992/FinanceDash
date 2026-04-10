"""
TrueLayer API client.

Handles all communication with TrueLayer's Auth and Data APIs:
- OAuth URL construction (auth link)
- Code-for-token exchange
- Token refresh
- Account, balance, and transaction fetching (Sprint 3)

The client is initialised once at app startup via the lifespan handler
in main.py and stored on app.state.truelayer.
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)


class TrueLayerError(Exception):
    """Base exception for TrueLayer API errors."""

    def __init__(self, message: str, status_code: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


class TrueLayerClient:
    """
    Async HTTP client for TrueLayer's API.

    Initialised once at app startup via the lifespan handler in main.py
    and stored on app.state.truelayer. All router/service code accesses
    it from there -- no global singletons.
    """

    # Scopes required for AIS (Account Information Services).
    # accounts + balance + transactions + cards covers all Data API v1 endpoints.
    AIS_SCOPES = ["info", "accounts", "balance", "transactions", "cards", "offline_access"]

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        auth_base_url: str,
        data_base_url: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.auth_base_url = auth_base_url.rstrip("/")
        self.data_base_url = data_base_url.rstrip("/")
        self.is_sandbox = "sandbox" in self.auth_base_url

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json"},
        )

        # In-memory nonce store: state -> user_id.
        # Keeps track of pending OAuth flows so the callback can verify
        # the state parameter (CSRF protection) and associate the
        # resulting tokens with the correct user.
        # TTL of 600s (10 min) auto-expires abandoned flows.
        # Max 10 000 entries prevents memory exhaustion from repeated calls.
        # In production with multiple workers, replace with Redis or DB.
        self._pending_states: TTLCache[str, str] = TTLCache(
            maxsize=10_000, ttl=600,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client. Called on app shutdown."""
        await self._http.aclose()

    # -- OAuth ----------------------------------------------------------------

    def build_auth_url(self, user_id: str) -> tuple[str, str]:
        """
        Build the TrueLayer authorization URL that the user is redirected to.

        Generates a cryptographic nonce for the `state` parameter and stores
        the mapping state -> user_id so the callback can verify it.

        Returns:
            (auth_url, state) tuple.
        """
        state = secrets.token_urlsafe(32)
        self._pending_states[state] = user_id

        # Sandbox only supports the Mock Bank provider (uk-cs-mock).
        # Live supports all UK Open Banking + OAuth providers.
        providers = "uk-cs-mock" if self.is_sandbox else "uk-ob-all uk-oauth-all"

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.AIS_SCOPES),
            "state": state,
            "providers": providers,
        }

        auth_url = f"{self.auth_base_url}/?{urlencode(params)}"
        return auth_url, state

    def validate_state(self, state: str) -> str | None:
        """
        Validate and consume a state nonce from a callback.

        Returns the user_id if valid, None if the state is unknown or
        already consumed (replay protection).
        """
        return self._pending_states.pop(state, None)

    async def exchange_code(self, code: str) -> dict:
        """
        Exchange an authorization code for access + refresh tokens.

        POST {auth_base_url}/connect/token
        Content-Type: application/x-www-form-urlencoded

        Returns dict with keys:
            access_token, refresh_token, expires_in, token_type, scope

        Raises TrueLayerError on failure.
        """
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }

        resp = await self._http.post(
            f"{self.auth_base_url}/connect/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            error_body = {}
            try:
                error_body = resp.json()
            except (ValueError, UnicodeDecodeError):
                pass
            # Log only the error type and description, not the full body
            # which could contain echoed tokens or other sensitive data.
            logger.error(
                "Token exchange returned %s: error=%s, description=%s",
                resp.status_code,
                error_body.get("error", "unknown"),
                error_body.get("error_description", ""),
            )
            raise TrueLayerError(
                message=f"Token exchange failed: {resp.status_code} — {error_body}",
                status_code=resp.status_code,
                body=error_body,
            )

        data = resp.json()

        # Compute absolute expiry time from the relative expires_in.
        expires_in = data.get("expires_in", 3600)
        data["token_expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        return data

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Refresh an expired access token using a refresh token.

        POST {auth_base_url}/connect/token  (grant_type=refresh_token)

        Returns dict with keys:
            access_token, refresh_token, expires_in, token_type, scope

        Raises TrueLayerError on failure.
        """
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }

        resp = await self._http.post(
            f"{self.auth_base_url}/connect/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            raise TrueLayerError(
                message=f"Token refresh failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
            )

        data = resp.json()

        expires_in = data.get("expires_in", 3600)
        data["token_expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        return data

    # -- Connection management -------------------------------------------------

    async def extend_connection(self, refresh_token: str) -> dict:
        """
        Extend (renew) an expiring or expired Open Banking connection.

        POST {auth_base_url}/api/connections/extend

        Uses the refresh_token to request a consent extension. TrueLayer
        returns one of two outcomes:
          - action_needed: "no_action_needed" — tokens refreshed silently,
            new access_token + refresh_token returned.
          - action_needed: "authentication_needed" — user must visit the
            provided auth_url to re-authenticate at their bank.

        Returns dict with keys:
            action_needed: str  ("no_action_needed" | "authentication_needed")
            access_token: str | None  (present if no_action_needed)
            refresh_token: str | None  (present if no_action_needed)
            expires_in: int | None  (present if no_action_needed)
            token_expires_at: datetime | None  (computed, present if no_action_needed)
            auth_url: str | None  (present if authentication_needed)

        Raises TrueLayerError on failure.
        """
        payload = {
            "refresh_token": refresh_token,
        }

        resp = await self._http.post(
            f"{self.auth_base_url}/api/connections/extend",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        if resp.status_code != 200:
            raise TrueLayerError(
                message=f"Connection extend failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
            )

        data = resp.json()

        # If tokens were refreshed, compute absolute expiry time.
        if data.get("access_token") and data.get("expires_in"):
            expires_in = data["expires_in"]
            data["token_expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        return data

    # -- Data API (Connection metadata) ----------------------------------------

    async def get_connection_metadata(self, access_token: str) -> dict:
        """
        Fetch metadata about the connection (provider info, consent dates).

        GET {data_base_url}/data/v1/me

        Used after initial token exchange to populate provider_id,
        provider_name, consent_created_at, consent_expires_at.

        Raises TrueLayerError on failure.
        """
        resp = await self._http.get(
            f"{self.data_base_url}/data/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if resp.status_code != 200:
            raise TrueLayerError(
                message=f"Connection metadata fetch failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
            )

        return resp.json()

    # -- Data API (Accounts, Balances, Transactions) ---------------------------

    # Retry configuration per ARCH.md §5.5.
    MAX_RETRIES = 3
    BACKOFF_BASE_SECONDS = 1  # 1s, 4s, 16s  (base * 4^attempt)
    BACKOFF_MULTIPLIER = 4
    # HTTP status codes that are safe to retry (transient failures).
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    async def _get_data(
        self, access_token: str, path: str, params: dict | None = None,
    ) -> dict:
        """
        Internal helper — GET a TrueLayer Data API endpoint with retry logic.

        Retries up to MAX_RETRIES times for transient failures (timeouts,
        5xx errors, 429 rate limits). Uses exponential backoff and respects
        the Retry-After header on 429 responses.

        Returns the parsed JSON response body.
        Raises TrueLayerError on persistent failures.
        """
        last_exception: Exception | None = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                resp = await self._http.get(
                    f"{self.data_base_url}{path}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if resp.status_code == 200:
                    return resp.json()

                # 429 — rate limited. Respect Retry-After if present.
                if resp.status_code == 429:
                    retry_after = self._parse_retry_after(resp)
                    if attempt < self.MAX_RETRIES:
                        wait = retry_after if retry_after > 0 else self._backoff_delay(attempt)
                        logger.warning(
                            "TrueLayer 429 on %s (attempt %d/%d), retrying in %.1fs",
                            path, attempt + 1, self.MAX_RETRIES + 1, wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                # Other retryable status codes (5xx).
                if resp.status_code in self.RETRYABLE_STATUS_CODES and attempt < self.MAX_RETRIES:
                    wait = self._backoff_delay(attempt)
                    logger.warning(
                        "TrueLayer %d on %s (attempt %d/%d), retrying in %.1fs",
                        resp.status_code, path, attempt + 1, self.MAX_RETRIES + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Non-retryable error or retries exhausted — raise immediately.
                raise TrueLayerError(
                    message=f"Data API request failed: {resp.status_code} {path}",
                    status_code=resp.status_code,
                    body=(
                        resp.json()
                        if resp.headers.get("content-type", "").startswith("application/json")
                        else {}
                    ),
                )

            except httpx.TimeoutException as exc:
                last_exception = exc
                if attempt < self.MAX_RETRIES:
                    wait = self._backoff_delay(attempt)
                    logger.warning(
                        "TrueLayer timeout on %s (attempt %d/%d), retrying in %.1fs",
                        path, attempt + 1, self.MAX_RETRIES + 1, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Retries exhausted on timeout.
                raise TrueLayerError(
                    message=f"Data API request timed out after {self.MAX_RETRIES + 1} attempts: {path}",
                    status_code=None,
                ) from exc

        # Should not reach here, but guard against it.
        raise TrueLayerError(
            message=f"Data API request failed after all retries: {path}",
            status_code=None,
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay: 1s, 4s, 16s."""
        return self.BACKOFF_BASE_SECONDS * (self.BACKOFF_MULTIPLIER ** attempt)

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float:
        """
        Parse the Retry-After header from a 429 response.

        Returns the number of seconds to wait, or 0 if the header is
        missing or unparseable.
        """
        retry_after = resp.headers.get("retry-after")
        if retry_after is None:
            return 0
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            return 0

    # -- Accounts --------------------------------------------------------------

    async def get_accounts(self, access_token: str) -> list[dict]:
        """
        Fetch all bank accounts for a connection.

        GET /data/v1/accounts

        Returns a list of account dicts, each containing:
            account_id, account_type, display_name, currency, etc.
        """
        data = await self._get_data(access_token, "/data/v1/accounts")
        return data.get("results", [])

    async def get_account_balance(self, access_token: str, account_id: str) -> dict:
        """
        Fetch the current balance for a specific account.

        GET /data/v1/accounts/{account_id}/balance

        Returns a dict with: current, available, currency.
        """
        data = await self._get_data(
            access_token, f"/data/v1/accounts/{account_id}/balance",
        )
        results = data.get("results", [])
        return results[0] if results else {}

    async def get_transactions(
        self,
        access_token: str,
        account_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """
        Fetch transactions for an account within a date range.

        GET /data/v1/accounts/{account_id}/transactions?from=...&to=...

        from_date / to_date are ISO date strings (YYYY-MM-DD).
        Returns a list of transaction dicts.
        """
        data = await self._get_data(
            access_token,
            f"/data/v1/accounts/{account_id}/transactions",
            params={"from": from_date, "to": to_date},
        )
        return data.get("results", [])

    # -- Credit Cards ----------------------------------------------------------

    async def get_cards(self, access_token: str) -> list[dict]:
        """
        Fetch all credit cards for a connection.

        GET /data/v1/cards

        Returns a list of card dicts (same shape as accounts but for cards).
        """
        data = await self._get_data(access_token, "/data/v1/cards")
        return data.get("results", [])

    async def get_card_balance(self, access_token: str, card_id: str) -> dict:
        """
        Fetch the current balance for a credit card.

        GET /data/v1/cards/{card_id}/balance

        Returns a dict with: current, available, currency.
        """
        data = await self._get_data(
            access_token, f"/data/v1/cards/{card_id}/balance",
        )
        results = data.get("results", [])
        return results[0] if results else {}

    async def get_card_transactions(
        self,
        access_token: str,
        card_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """
        Fetch transactions for a credit card within a date range.

        GET /data/v1/cards/{card_id}/transactions?from=...&to=...

        from_date / to_date are ISO date strings (YYYY-MM-DD).
        Returns a list of transaction dicts.
        """
        data = await self._get_data(
            access_token,
            f"/data/v1/cards/{card_id}/transactions",
            params={"from": from_date, "to": to_date},
        )
        return data.get("results", [])
