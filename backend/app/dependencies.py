"""
Dependency injection for FastAPI route handlers.

Provides shared resources (DB clients, auth) to endpoint functions
via FastAPI's Depends() mechanism.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.auth.jwt import get_current_user  # noqa: F401 — re-exported for convenience
from app.config import settings


@lru_cache(maxsize=1)
def _create_supabase_client() -> Client:
    """
    Create and cache a single Supabase client instance.

    Uses the secret key (service_role) so the backend bypasses RLS.
    This is intentional — the backend enforces authorisation via
    the user_id extracted from the JWT, not via Postgres RLS.

    Cached via lru_cache so we don't create a new client per request.
    """
    return create_client(settings.supabase_url, settings.supabase_secret_key)


def get_supabase() -> Client:
    """
    FastAPI dependency that provides the Supabase client.

    Usage:
        @router.get("/example")
        async def example(db: Client = Depends(get_supabase)):
            result = db.table("accounts").select("*").execute()
    """
    return _create_supabase_client()
