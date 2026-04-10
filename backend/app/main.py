"""
FastAPI application entry point.

Provides:
- /health endpoint for liveness checks
- CORS middleware (restricted in production)
- Rate limiting on sensitive endpoints (slowapi)
- TrueLayer client initialised from config
- APScheduler for periodic data sync (every 4 hours)
- Router mounting for all API modules
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sentry_sdk
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.dependencies import get_current_user, get_supabase
from app.jobs.scheduled_sync import start_scheduler, stop_scheduler
from app.rate_limit import limiter
from app.services.truelayer import TrueLayerClient

# Configure the root logger so that all app.* loggers output to the console.
# Without this, logger.info() / logger.warning() calls throughout the app
# are silently dropped because no handler is attached.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentry — error tracking for production
# ---------------------------------------------------------------------------
# Initialise only when a DSN is configured. In local dev (no SENTRY_DSN),
# this is a no-op and adds zero overhead.

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=0.1,  # 10% of requests get performance traces
        send_default_pii=False,  # Don't send user IP/email to Sentry
    )
    logger.info("Sentry error tracking enabled (env=%s)", settings.app_env)


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

    # Start the scheduled sync job (every 4 hours).
    db = get_supabase()
    app.state.scheduler = start_scheduler(db, app.state.truelayer)
    logger.info("Application startup complete")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    stop_scheduler()
    await app.state.truelayer.close()
    logger.info("Application shutdown complete")


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
# Rate Limiting (slowapi)
# ---------------------------------------------------------------------------

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Global exception handler — prevents leaking internal details in production
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    # Origins are configured via CORS_ORIGINS env var (comma-separated).
    # In debug mode, localhost origins are added automatically.
    # See config.py for details.
    allow_origins=settings.cors_origin_list,
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
from app.routers import accounts, connections, net_worth, sync, transactions

app.include_router(connections.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(net_worth.router, prefix="/api/v1")


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
