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

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx


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

        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json"},
        )

        # In-memory nonce store: state -> user_id.
        # Keeps track of pending OAuth flows so the callback can verify
        # the state parameter (CSRF protection) and associate the
        # resulting tokens with the correct user.
        # In production with multiple workers, replace with Redis or DB.
        self._pending_states: dict[str, str] = {}

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

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.AIS_SCOPES),
            "state": state,
            # providers_id=uk-ob-all gives access to all UK Open Banking providers
            # in sandbox this maps to the mock provider.
            "providers": "uk-ob-all uk-oauth-all",
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
            raise TrueLayerError(
                message=f"Token exchange failed: {resp.status_code}",
                status_code=resp.status_code,
                body=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {},
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
    # These remain as stubs for Sprint 3.

    async def get_accounts(self, access_token: str) -> list[dict]:
        """
        Fetch all accounts for a connection.
        GET {data_base_url}/data/v1/accounts
        Sprint 3: Implement account fetching.
        """
        raise NotImplementedError("Sprint 3: Fetch accounts")

    async def get_account_balance(self, access_token: str, account_id: str) -> dict:
        """
        Fetch the current balance for a specific account.
        GET {data_base_url}/data/v1/accounts/{account_id}/balance
        Sprint 3: Implement balance fetching.
        """
        raise NotImplementedError("Sprint 3: Fetch balance")

    async def get_transactions(
        self,
        access_token: str,
        account_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """
        Fetch transactions for an account within a date range.
        GET {data_base_url}/data/v1/accounts/{account_id}/transactions
        Sprint 3: Implement transaction fetching.
        """
        raise NotImplementedError("Sprint 3: Fetch transactions")

    async def get_cards(self, access_token: str) -> list[dict]:
        """
        Fetch all credit cards for a connection.
        GET {data_base_url}/data/v1/cards
        Sprint 3: Implement card fetching.
        """
        raise NotImplementedError("Sprint 3: Fetch cards")

    async def get_card_balance(self, access_token: str, card_id: str) -> dict:
        """
        Fetch the current balance for a credit card.
        GET {data_base_url}/data/v1/cards/{card_id}/balance
        Sprint 3: Implement card balance fetching.
        """
        raise NotImplementedError("Sprint 3: Fetch card balance")

    async def get_card_transactions(
        self,
        access_token: str,
        card_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """
        Fetch transactions for a credit card within a date range.
        GET {data_base_url}/data/v1/cards/{card_id}/transactions
        Sprint 3: Implement card transaction fetching.
        """
        raise NotImplementedError("Sprint 3: Fetch card transactions")
