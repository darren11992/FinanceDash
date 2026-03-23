"""
Bank connections router.

Endpoints for managing TrueLayer bank connections:
- POST /connections/initiate  — start OAuth flow, return auth URL
- POST /connections/callback   — exchange auth code for tokens, store connection
- GET  /connections            — list user's connections
- DELETE /connections/{id}     — revoke and delete a connection
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from supabase import Client

from app.dependencies import get_current_user, get_supabase
from app.models.schemas import (
    ConnectionCallbackIn,
    ConnectionCallbackOut,
    ConnectionInitiateOut,
    ConnectionOut,
)
from app.services.encryption import decrypt_token, encrypt_token
from app.services.truelayer import TrueLayerClient, TrueLayerError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_truelayer(request: Request) -> TrueLayerClient:
    """Extract the TrueLayer client from app state."""
    return request.app.state.truelayer


# ---------------------------------------------------------------------------
# POST /connections/initiate
# ---------------------------------------------------------------------------


@router.post("/initiate", response_model=ConnectionInitiateOut)
async def initiate_connection(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """
    Generate a TrueLayer authorization URL for the authenticated user.

    The Flutter app opens this URL in a browser/webview. After the user
    grants consent at their bank, TrueLayer redirects to the configured
    redirect URI with an authorization code.
    """
    tl = _get_truelayer(request)
    auth_url, _state = tl.build_auth_url(user_id)

    return ConnectionInitiateOut(auth_url=auth_url)


# ---------------------------------------------------------------------------
# POST /connections/callback
# ---------------------------------------------------------------------------


@router.post(
    "/callback",
    response_model=ConnectionCallbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def connection_callback(
    body: ConnectionCallbackIn,
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Handle the OAuth callback from TrueLayer.

    The Flutter app extracts the authorization code from the deep-link
    redirect and sends it here. The backend:
      1. Exchanges the code for access + refresh tokens
      2. Fetches connection metadata (provider info, consent dates)
      3. Encrypts the tokens
      4. Stores a new row in bank_connections

    Returns the new connection's metadata.
    """
    tl = _get_truelayer(request)

    # 1. Exchange the authorization code for tokens
    try:
        token_data = await tl.exchange_code(body.code)
    except TrueLayerError as e:
        logger.error("TrueLayer token exchange failed: %s (status=%s)", e, e.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to exchange authorization code with TrueLayer: {e}",
        )

    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    token_expires_at = token_data["token_expires_at"]

    # 2. Fetch connection metadata to get provider info and consent dates
    try:
        metadata = await tl.get_connection_metadata(access_token)
    except TrueLayerError as e:
        logger.error("TrueLayer metadata fetch failed: %s (status=%s)", e, e.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch connection metadata from TrueLayer: {e}",
        )

    # The /data/v1/me response structure:
    # {
    #   "results": [{
    #     "credentials_id": "...",
    #     "client_id": "...",
    #     "provider": { "provider_id": "...", "display_name": "..." },
    #     "consent_created_at": "2026-03-19T...",
    #     "consent_expires_at": "2026-06-17T...",   (may be absent)
    #     ...
    #   }]
    # }
    results = metadata.get("results", [])
    if not results:
        logger.error("TrueLayer /me returned empty results: %s", metadata)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="TrueLayer returned no connection metadata",
        )

    conn_meta = results[0]
    provider = conn_meta.get("provider", {})
    provider_id = provider.get("provider_id", "unknown")
    provider_name = provider.get("display_name", provider_id)

    # Consent dates — TrueLayer may provide these, or we default to 90 days.
    consent_created_str = conn_meta.get("consent_created_at")
    consent_expires_str = conn_meta.get("consent_expires_at")

    now = datetime.now(timezone.utc)

    if consent_created_str:
        consent_created_at = datetime.fromisoformat(consent_created_str.replace("Z", "+00:00"))
    else:
        consent_created_at = now

    if consent_expires_str:
        consent_expires_at = datetime.fromisoformat(consent_expires_str.replace("Z", "+00:00"))
    else:
        # UK Open Banking AIS consent window is 90 days.
        consent_expires_at = consent_created_at + timedelta(days=90)

    # 3. Encrypt tokens before storing
    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token)

    # 4. Insert into bank_connections
    row = {
        "user_id": user_id,
        "provider_id": provider_id,
        "provider_name": provider_name,
        "access_token": encrypted_access,
        "refresh_token": encrypted_refresh,
        "token_expires_at": token_expires_at.isoformat(),
        "consent_created_at": consent_created_at.isoformat(),
        "consent_expires_at": consent_expires_at.isoformat(),
        "status": "active",
    }

    try:
        result = db.table("bank_connections").insert(row).execute()
    except Exception as e:
        logger.error("Failed to insert bank_connection: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store bank connection",
        )

    connection = result.data[0]

    return ConnectionCallbackOut(
        connection_id=connection["id"],
        provider_name=provider_name,
        status="active",
    )


# ---------------------------------------------------------------------------
# GET /connections
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ConnectionOut])
async def list_connections(
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    List all bank connections for the authenticated user.

    Returns metadata only — tokens are never exposed to the client.
    """
    try:
        result = (
            db.table("bank_connections")
            .select(
                "id, provider_id, provider_name, status, last_synced_at, "
                "consent_created_at, consent_expires_at, error_message, created_at"
            )
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as e:
        logger.error("Failed to list bank_connections for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve bank connections",
        )

    return result.data


# ---------------------------------------------------------------------------
# DELETE /connections/{connection_id}
# ---------------------------------------------------------------------------


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Disconnect a bank connection.

    1. Verify the connection belongs to the authenticated user
    2. Attempt to revoke the TrueLayer access token (best-effort)
    3. Delete the connection row (CASCADE deletes child accounts/transactions)
    """
    # Fetch the connection, including encrypted tokens for revocation
    result = (
        db.table("bank_connections")
        .select("id, user_id, access_token")
        .eq("id", str(connection_id))
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found",
        )

    connection = result.data[0]

    # Best-effort: revoke the access token at TrueLayer.
    # If this fails (e.g., token already expired), we still delete locally.
    try:
        tl = _get_truelayer(request)
        access_token = decrypt_token(connection["access_token"])
        await tl._http.delete(
            f"{tl.data_base_url}/data/v1/tokens/revoke",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        # Log but don't fail — the user wants to disconnect regardless.
        logger.warning("Failed to revoke TrueLayer token for connection %s: %s", connection_id, e)

    # Delete the connection (CASCADE removes child accounts & transactions)
    db.table("bank_connections").delete().eq("id", str(connection_id)).execute()

    return None
