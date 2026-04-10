"""
Accounts router.

Endpoints for viewing bank account data:
- GET /accounts      — list all accounts across all connections
- GET /accounts/{id} — single account detail

Net worth endpoints live in routers/net_worth.py (Sprint 4).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.dependencies import get_current_user, get_supabase
from app.models.schemas import AccountOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounts", tags=["accounts"])


# ---------------------------------------------------------------------------
# GET /accounts
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[AccountOut])
async def list_accounts(
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    List all bank accounts (current, savings, credit cards) across all
    of the authenticated user's connected banks.

    Accounts are sorted by display_name. Includes current/available
    balances and the last time the balance was updated.
    """
    try:
        result = (
            db.table("accounts")
            .select(
                "id, bank_connection_id, truelayer_account_id, account_type, "
                "display_name, currency, current_balance, available_balance, "
                "balance_updated_at, is_included_in_net_worth"
            )
            .eq("user_id", user_id)
            .order("display_name")
            .execute()
        )
    except APIError as e:
        logger.error("Failed to list accounts for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve accounts",
        )

    return result.data


# ---------------------------------------------------------------------------
# GET /accounts/{account_id}
# ---------------------------------------------------------------------------


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(
    account_id: UUID,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Get details for a single bank account.

    Returns 404 if the account does not exist or belongs to another user.
    """
    try:
        result = (
            db.table("accounts")
            .select(
                "id, bank_connection_id, truelayer_account_id, account_type, "
                "display_name, currency, current_balance, available_balance, "
                "balance_updated_at, is_included_in_net_worth"
            )
            .eq("id", str(account_id))
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as e:
        logger.error("Failed to fetch account %s for user %s: %s", account_id, user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve account",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    return result.data[0]
