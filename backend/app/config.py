"""
Application settings loaded from environment variables.

Uses pydantic-settings to validate and type-check all configuration
at startup. If a required variable is missing, the app fails fast
with a clear error message rather than crashing mid-request.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the backend, sourced from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # silently ignore env vars not declared here
    )

    # ── Supabase ──────────────────────────────────────────────────────────
    # Uses the new API key format (June 2025+).
    # See: https://github.com/orgs/supabase/discussions/29260
    supabase_url: str
    supabase_publishable_key: str    # sb_publishable_... (replaces anon key)
    supabase_secret_key: str         # sb_secret_...      (replaces service_role key)
    # JWT verification now uses the JWKS endpoint (asymmetric signing key).
    # No shared secret needed — public key is fetched from:
    #   {supabase_url}/auth/v1/.well-known/jwks.json
    # See: https://supabase.com/docs/guides/auth/signing-keys

    # ── TrueLayer ─────────────────────────────────────────────────────────
    truelayer_client_id: str
    truelayer_client_secret: str
    truelayer_redirect_uri: str = "http://localhost:8000/api/v1/connections/callback"
    truelayer_env: str = "sandbox"  # "sandbox" or "live"
    truelayer_auth_base_url: str = "https://auth.truelayer-sandbox.com"
    truelayer_data_base_url: str = "https://api.truelayer-sandbox.com"

    # ── Token Encryption ──────────────────────────────────────────────────
    truelayer_token_encryption_key: str

    # ── Application ───────────────────────────────────────────────────────
    app_env: str = "development"
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ── CORS ──────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins for production.
    # Example: "https://penny.example.com,https://app.penny.finance"
    # When empty AND app_debug is False, no origins are allowed (secure default).
    # When app_debug is True, localhost origins are added automatically.
    cors_origins: str = ""

    # ── Sentry ────────────────────────────────────────────────────────────
    # Leave empty to disable Sentry error tracking (e.g. in local dev).
    # Set to your Sentry DSN in production.
    sentry_dsn: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list, merging dev origins when debugging."""
        origins: list[str] = []
        if self.cors_origins:
            origins.extend(
                o.strip() for o in self.cors_origins.split(",") if o.strip()
            )
        if self.app_debug:
            origins.extend([
                "http://localhost:8080",
                "http://localhost:3000",
                "http://127.0.0.1:8080",
                "http://127.0.0.1:3000",
            ])
        return origins


settings = Settings()
