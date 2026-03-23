"""
FastAPI application entry point.

Provides:
- /health endpoint for liveness checks
- CORS middleware (restricted in production)
- TrueLayer client placeholder (initialised from config)
- Router mounting point for future endpoint modules
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.dependencies import get_current_user
from app.services.truelayer import TrueLayerClient


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown logic
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on startup before serving requests, and once on shutdown.
    Use this for initialising shared resources (DB pools, HTTP clients, etc.).
    """
    # ── Startup ───────────────────────────────────────────────────────────
    app.state.truelayer = TrueLayerClient(
        client_id=settings.truelayer_client_id,
        client_secret=settings.truelayer_client_secret,
        redirect_uri=settings.truelayer_redirect_uri,
        auth_base_url=settings.truelayer_auth_base_url,
        data_base_url=settings.truelayer_data_base_url,
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    await app.state.truelayer.close()


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Penny API",
    description="UK Personal Finance Aggregator — Backend API",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    # In production, restrict this to your app's domain.
    # For development, allow common local origins.
    # NOTE: allow_credentials=True is incompatible with allow_origins=["*"].
    # The CORS spec requires the server to echo the specific origin when
    # credentials (Authorization header) are included.
    allow_origins=[
        "http://localhost:8080",   # Flutter web dev server
        "http://localhost:3000",   # Alternate dev port
        "http://127.0.0.1:8080",
        "http://127.0.0.1:3000",
    ] if settings.app_debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health_check():
    """
    Liveness probe. Returns 200 if the server is running.

    Used by load balancers, container orchestrators, and CI pipelines
    to verify the backend is up.
    """
    return {
        "status": "healthy",
        "version": app.version,
        "environment": settings.app_env,
        "truelayer_env": settings.truelayer_env,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------
from app.routers import connections

app.include_router(connections.router, prefix="/api/v1")

# Placeholder — wired up in later sprints:
# from app.routers import accounts, transactions, sync
# app.include_router(accounts.router, prefix="/api/v1")
# app.include_router(transactions.router, prefix="/api/v1")
# app.include_router(sync.router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Protected routes
# ---------------------------------------------------------------------------

@app.get("/api/v1/me", tags=["auth"])
async def get_me(user_id: str = Depends(get_current_user)):
    """
    Return the authenticated user's UUID.

    This is a lightweight endpoint for the Flutter app to verify
    that its stored JWT is still valid and to retrieve the user ID
    used for all subsequent API calls.
    """
    return {"user_id": user_id}
