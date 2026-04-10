"""
Bank connections router.

Endpoints for managing TrueLayer bank connections:
- POST /connections/initiate  — start OAuth flow, return auth URL
- GET  /connections/callback   — browser redirect from TrueLayer (returns HTML)
- POST /connections/callback   — mobile app sends code from deep link (returns JSON)
- GET  /connections            — list user's connections
- DELETE /connections/{id}     — revoke and delete a connection
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

from app.dependencies import get_current_user, get_supabase
from app.models.schemas import (
    ConnectionCallbackIn,
    ConnectionCallbackOut,
    ConnectionInitiateOut,
    ConnectionOut,
    ReconnectOut,
)
from app.rate_limit import limiter
from cryptography.fernet import InvalidToken
from postgrest.exceptions import APIError

from app.services.encryption import decrypt_token, encrypt_token
from app.services.sync_engine import sync_user_connections
from app.services.truelayer import TrueLayerClient, TrueLayerError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connections"])

# Jinja2 templates for the browser-based GET callback HTML responses.
# Auto-escaping is enabled by default, which prevents XSS from
# provider_name or error detail values injected into the template.
_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_truelayer(request: Request) -> TrueLayerClient:
    """Extract the TrueLayer client from app state."""
    return request.app.state.truelayer


async def _create_connection(
    truelayer_client: TrueLayerClient,
    db: Client,
    user_id: str,
    code: str,
) -> dict:
    """
    Shared logic for creating a bank connection from an auth code.

    1. Exchanges the code for access + refresh tokens
    2. Fetches connection metadata (provider info, consent dates)
    3. Encrypts the tokens
    4. Stores a new row in bank_connections

    Returns the inserted connection row dict.
    Raises HTTPException on failure.
    """
    # 1. Exchange the authorization code for tokens
    try:
        token_data = await truelayer_client.exchange_code(code)
    except TrueLayerError as e:
        logger.error("TrueLayer token exchange failed: %s (status=%s)", e, e.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to connect to your bank. Please try again.",
        )

    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]
    token_expires_at = token_data["token_expires_at"]

    # 2. Fetch connection metadata to get provider info and consent dates
    try:
        metadata = await truelayer_client.get_connection_metadata(access_token)
    except TrueLayerError as e:
        logger.error("TrueLayer metadata fetch failed: %s (status=%s)", e, e.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve bank connection details. Please try again.",
        )

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

    # Consent dates
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
    except APIError as e:
        logger.error("Failed to insert bank_connection: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store bank connection",
        )

    return result.data[0]


# ---------------------------------------------------------------------------
# POST /connections/initiate
# ---------------------------------------------------------------------------


@router.post("/initiate", response_model=ConnectionInitiateOut)
@limiter.limit("10/minute")
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
    truelayer_client = _get_truelayer(request)
    auth_url, _state = truelayer_client.build_auth_url(user_id)

    return ConnectionInitiateOut(auth_url=auth_url)


# GET /connections/callback  (browser redirect from TrueLayer)
# Note: scope is just to prevent FastAPI from rejecting the redirect
@router.get("/callback", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def callback_browser_redirect(
    request: Request,
    code: str = Query(..., description="Authorization code from TrueLayer"),
    state: str = Query(default="", description="State nonce for CSRF protection"),
    scope: str = Query(default="", description="Granted scopes (echoed back by TrueLayer)"),
):
    """
    Handle the OAuth callback as a browser redirect from TrueLayer.

    TrueLayer redirects the user's browser to:
        {redirect_uri}?code=...&state=...&scope=...

    This endpoint:
      1. Validates the state nonce to find the user_id
      2. Exchanges the code for tokens
      3. Stores the connection
      4. Returns an HTML success/error page

    No Bearer token is required — user identity comes from the state nonce
    that was generated in build_auth_url() and mapped to user_id.
    """
    truelayer_client = _get_truelayer(request)

    # Validate state to get user_id
    user_id = truelayer_client.validate_state(state)
    if not user_id:
        logger.warning("GET callback received invalid or expired state: %s", state[:20] if state else "(empty)")
        return templates.TemplateResponse(
            "callback_error.html",
            {
                "request": request,
                "detail": "Invalid or expired session. Please try connecting again from the app.",
            },
            status_code=400,
        )

    db = get_supabase()

    try:
        connection = await _create_connection(truelayer_client, db, user_id, code)
        provider_name = connection.get("provider_name", "Your bank")

        # Trigger an immediate sync so accounts/transactions/balance_history
        # are populated (including the backfill for historical balances).
        # This runs in the same request — the HTML response is returned after.
        try:
            logger.info("GET callback: triggering post-connection sync for user %s", user_id)
            await sync_user_connections(user_id, db, truelayer_client)
            logger.info("GET callback: post-connection sync complete for user %s", user_id)
        except Exception as sync_err:
            # Non-fatal — the scheduled sync will pick it up later.
            logger.warning("GET callback: post-connection sync failed: %s", sync_err)

        return templates.TemplateResponse(
            "callback_success.html",
            {"request": request, "provider_name": provider_name},
            status_code=200,
        )
    except HTTPException as e:
        logger.error("GET callback failed for user %s: %s", user_id, e.detail)
        return templates.TemplateResponse(
            "callback_error.html",
            {"request": request, "detail": str(e.detail)},
            status_code=e.status_code,
        )


# ---------------------------------------------------------------------------
# POST /connections/callback  (mobile app sends code from deep link)
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
    Handle the OAuth callback from the mobile app.

    The Flutter app extracts the authorization code from the deep-link
    redirect and sends it here with a Bearer token. The backend:
      1. Exchanges the code for access + refresh tokens
      2. Fetches connection metadata (provider info, consent dates)
      3. Encrypts the tokens
      4. Stores a new row in bank_connections

    Returns the new connection's metadata.
    """
    truelayer_client = _get_truelayer(request)

    connection = await _create_connection(truelayer_client, db, user_id, body.code)

    return ConnectionCallbackOut(
        connection_id=connection["id"],
        provider_name=connection.get("provider_name", "unknown"),
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
    except APIError as e:
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
        truelayer_client = _get_truelayer(request)
        access_token = decrypt_token(connection["access_token"])
        await truelayer_client._http.delete(
            f"{truelayer_client.data_base_url}/data/v1/tokens/revoke",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:  # noqa: BLE001 — intentionally broad: best-effort revocation
        # Log but don't fail — the user wants to disconnect regardless.
        logger.warning("Failed to revoke TrueLayer token for connection %s: %s", connection_id, e)

    # Delete the connection (CASCADE removes child accounts & transactions)
    db.table("bank_connections").delete().eq("id", str(connection_id)).execute()

    return None


# ---------------------------------------------------------------------------
# POST /connections/{connection_id}/reconnect
# ---------------------------------------------------------------------------


@router.post("/{connection_id}/reconnect", response_model=ReconnectOut)
@limiter.limit("5/minute")
async def reconnect_connection(
    connection_id: UUID,
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Reconnect an expiring or expired bank connection.

    Uses TrueLayer's POST /connections/extend endpoint to renew consent
    without creating a new connection (avoids double billing).

    Two outcomes:
      - no_action_needed: consent extended silently, tokens refreshed.
      - authentication_needed: returns an auth URL for the user to
        re-authenticate at their bank.

    See: https://docs.truelayer.com/docs/extend-a-connection
    """
    # 1. Fetch the connection (verify ownership + get refresh token)
    result = (
        db.table("bank_connections")
        .select("id, user_id, status, refresh_token, provider_name")
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
    conn_status = connection.get("status")
    provider_name = connection.get("provider_name", "Unknown")

    # Only allow reconnect for expiring_soon or expired connections.
    # Active connections don't need reconnection, and error/revoked
    # connections require a fresh OAuth flow.
    if conn_status not in ("expiring_soon", "expired"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection status is '{conn_status}' — reconnect is only "
                   f"available for 'expiring_soon' or 'expired' connections",
        )

    # 2. Decrypt the refresh token
    try:
        refresh_token = decrypt_token(connection["refresh_token"])
    except InvalidToken as e:
        logger.error(
            "Failed to decrypt refresh token for connection %s: %s",
            connection_id, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt stored credentials",
        )

    # 3. Call TrueLayer's extend endpoint
    truelayer_client = _get_truelayer(request)
    try:
        extend_data = await truelayer_client.extend_connection(refresh_token)
    except TrueLayerError as e:
        logger.error(
            "TrueLayer extend failed for connection %s: %s (status=%s)",
            connection_id, e, e.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to renew bank connection. Please try again.",
        )

    action = extend_data.get("action_needed", "authentication_needed")

    # 4. Handle the outcome
    if action == "no_action_needed":
        # Consent extended silently — store new tokens and reset dates.
        new_access = extend_data.get("access_token", "")
        new_refresh = extend_data.get("refresh_token", refresh_token)
        token_expires_at = extend_data.get("token_expires_at")

        # Fetch updated metadata to get new consent dates.
        try:
            metadata = await truelayer_client.get_connection_metadata(new_access)
            meta_results = metadata.get("results", [])
            if meta_results:
                conn_meta = meta_results[0]
                consent_created_str = conn_meta.get("consent_created_at")
                consent_expires_str = conn_meta.get("consent_expires_at")
            else:
                consent_created_str = None
                consent_expires_str = None
        except TrueLayerError:
            # Non-fatal — we'll just use defaults.
            logger.warning(
                "Failed to fetch metadata after extend for connection %s",
                connection_id,
            )
            consent_created_str = None
            consent_expires_str = None

        now = datetime.now(timezone.utc)

        update_data: dict = {
            "access_token": encrypt_token(new_access),
            "refresh_token": encrypt_token(new_refresh),
            "status": "active",
            "error_message": None,
        }

        if token_expires_at:
            update_data["token_expires_at"] = token_expires_at.isoformat()

        if consent_created_str:
            update_data["consent_created_at"] = datetime.fromisoformat(
                consent_created_str.replace("Z", "+00:00")
            ).isoformat()
        else:
            update_data["consent_created_at"] = now.isoformat()

        if consent_expires_str:
            update_data["consent_expires_at"] = datetime.fromisoformat(
                consent_expires_str.replace("Z", "+00:00")
            ).isoformat()
        else:
            update_data["consent_expires_at"] = (now + timedelta(days=90)).isoformat()

        db.table("bank_connections").update(update_data).eq(
            "id", str(connection_id)
        ).execute()

        logger.info(
            "Connection %s (%s) extended silently — status reset to active",
            connection_id, provider_name,
        )

        return ReconnectOut(
            action="no_action_needed",
            auth_url=None,
            message=f"{provider_name} connection renewed successfully",
        )

    else:
        # authentication_needed — return the auth URL for the client.
        auth_url = extend_data.get("auth_url", "")

        logger.info(
            "Connection %s (%s) requires bank re-authentication",
            connection_id, provider_name,
        )

        return ReconnectOut(
            action="authentication_needed",
            auth_url=auth_url,
            message=f"Please re-authenticate with {provider_name} to renew your connection",
        )
