"""
Sync router.

Endpoints for triggering and monitoring data syncs:
- POST /sync        — trigger a sync for all the user's active connections
- GET  /sync/status — get last sync timestamps and errors per connection
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from postgrest.exceptions import APIError
from supabase import Client

from app.dependencies import get_current_user, get_supabase
from app.models.schemas import (
    ConnectionSyncStatus,
    SyncConnectionResult,
    SyncStatusOut,
    SyncTriggerOut,
)
from app.rate_limit import limiter
from app.services.sync_engine import sync_user_connections
from app.services.truelayer import TrueLayerClient, TrueLayerError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])


def _get_truelayer(request: Request) -> TrueLayerClient:
    """Extract the TrueLayer client from app state."""
    return request.app.state.truelayer


# ---------------------------------------------------------------------------
# POST /sync
# ---------------------------------------------------------------------------


@router.post("/", response_model=SyncTriggerOut)
@limiter.limit("10/minute")
async def trigger_sync(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Trigger a manual sync for all of the authenticated user's active
    bank connections.

    This is called when the user pulls-to-refresh in the Flutter app.
    Syncs run sequentially per connection to respect TrueLayer rate limits.
    """
    truelayer_client = _get_truelayer(request)

    try:
        results = await sync_user_connections(user_id, db, truelayer_client)
    except (TrueLayerError, APIError) as e:
        logger.exception("Sync failed for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sync failed unexpectedly",
        )

    return SyncTriggerOut(
        message="Sync completed",
        connections_queued=len(results),
        results=[
            SyncConnectionResult(
                connection_id=r.get("connection_id", ""),
                status=r.get("status", "unknown"),
                detail=r.get("detail"),
                accounts_synced=r.get("accounts_synced", 0),
                transactions_synced=r.get("transactions_synced", 0),
            )
            for r in results
        ],
    )


# ---------------------------------------------------------------------------
# GET /sync/status
# ---------------------------------------------------------------------------


@router.get("/status", response_model=SyncStatusOut)
async def get_sync_status(
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Return the last sync timestamp and error status for each of the
    user's bank connections.
    """
    try:
        result = (
            db.table("bank_connections")
            .select("id, provider_name, status, last_synced_at, error_message")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except APIError as e:
        logger.error("Failed to fetch sync status for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sync status",
        )

    connections = [
        ConnectionSyncStatus(
            connection_id=row["id"],
            provider_name=row["provider_name"],
            status=row["status"],
            last_synced_at=row.get("last_synced_at"),
            error_message=row.get("error_message"),
        )
        for row in result.data
    ]

    return SyncStatusOut(connections=connections)
