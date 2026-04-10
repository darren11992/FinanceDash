"""
Net worth router.

Endpoints for net worth calculation and history:
- GET /net-worth          — current net worth with per-account breakdown
- GET /net-worth/history  — daily net worth trend (7d, 30d, 90d)

Net worth = sum of (current + savings balances) - credit card balances.
Only accounts with is_included_in_net_worth=True are included.
Credit card balances are stored as positive numbers but treated as
liabilities (subtracted from total).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from postgrest.exceptions import APIError
from supabase import Client

from app.dependencies import get_current_user, get_supabase
from app.models.schemas import (
    NetWorthAccountBreakdown,
    NetWorthHistoryOut,
    NetWorthHistoryPoint,
    NetWorthOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/net-worth", tags=["net-worth"])

# Supported period values and their day counts.
VALID_PERIODS = {"7d": 7, "30d": 30, "90d": 90}


# ---------------------------------------------------------------------------
# GET /net-worth
# ---------------------------------------------------------------------------


@router.get("/", response_model=NetWorthOut)
async def get_net_worth(
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Calculate and return the user's current net worth.

    Net worth = sum of current/savings account balances
              - sum of credit card balances.

    Only accounts with `is_included_in_net_worth = True` are considered.
    Returns a per-account breakdown showing each account's contribution.
    """
    try:
        result = (
            db.table("accounts")
            .select(
                "id, account_type, display_name, currency, "
                "current_balance, balance_updated_at, is_included_in_net_worth"
            )
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as e:
        logger.error("Failed to fetch accounts for net worth (user %s): %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate net worth",
        )

    accounts = result.data
    total = Decimal("0")
    breakdown: list[NetWorthAccountBreakdown] = []
    latest_updated: datetime | None = None

    for acct in accounts:
        is_liability = acct["account_type"] == "credit_card"
        balance = _parse_balance(acct.get("current_balance"))

        breakdown.append(
            NetWorthAccountBreakdown(
                account_id=acct["id"],
                display_name=acct["display_name"],
                account_type=acct["account_type"],
                current_balance=balance,
                currency=acct.get("currency", "GBP"),
                is_liability=is_liability,
            )
        )

        # Only include in the total if the flag is set.
        if acct.get("is_included_in_net_worth", True) and balance is not None:
            if is_liability:
                total -= balance
            else:
                total += balance

        # Track the most recent balance update.
        updated_at_str = acct.get("balance_updated_at")
        if updated_at_str:
            updated_at = datetime.fromisoformat(updated_at_str)
            if latest_updated is None or updated_at > latest_updated:
                latest_updated = updated_at

    return NetWorthOut(
        total_net_worth=total,
        currency="GBP",
        accounts=breakdown,
        last_updated=latest_updated,
    )


# ---------------------------------------------------------------------------
# GET /net-worth/history
# ---------------------------------------------------------------------------


@router.get("/history", response_model=NetWorthHistoryOut)
async def get_net_worth_history(
    period: str = Query(
        "30d",
        description="Time period for history: 7d, 30d, or 90d",
    ),
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Return the user's daily net worth trend from balance_history.

    Each data point is the sum of all included account balances for that
    day, with credit card balances subtracted. Days with no snapshot for
    a given account are excluded from that account's contribution (the
    sync records one snapshot per account per day).

    Supports periods: 7d, 30d, 90d.
    """
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(VALID_PERIODS)}",
        )

    days = VALID_PERIODS[period]
    start_date = (date.today() - timedelta(days=days)).isoformat()

    # First, get the user's accounts so we know which are liabilities
    # and which are included in net worth.
    try:
        acct_result = (
            db.table("accounts")
            .select("id, account_type, is_included_in_net_worth")
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as e:
        logger.error("Failed to fetch accounts for history (user %s): %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve net worth history",
        )

    # Build lookup: account_id -> {is_liability, included}
    account_info: dict[str, dict] = {}
    for acct in acct_result.data:
        account_info[acct["id"]] = {
            "is_liability": acct["account_type"] == "credit_card",
            "included": acct.get("is_included_in_net_worth", True),
        }

    # Fetch balance_history rows for the period.
    try:
        history_result = (
            db.table("balance_history")
            .select("account_id, balance, recorded_at, is_estimated")
            .eq("user_id", user_id)
            .gte("recorded_at", start_date)
            .order("recorded_at")
            .execute()
        )
    except APIError as e:
        logger.error("Failed to fetch balance history (user %s): %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve net worth history",
        )

    # Aggregate: sum balances per day, treating credit cards as negative.
    # Track whether any contributing row on a given day is estimated.
    daily_totals: dict[str, Decimal] = {}
    daily_estimated: dict[str, bool] = {}

    for row in history_result.data:
        acct_id = row["account_id"]
        info = account_info.get(acct_id)

        # Skip accounts not included in net worth or no longer in our lookup
        # (could happen if account was deleted but history remains).
        if info is None or not info["included"]:
            continue

        recorded_at = row["recorded_at"]
        balance = _parse_balance(row.get("balance"))
        if balance is None:
            continue

        contribution = -balance if info["is_liability"] else balance

        if recorded_at in daily_totals:
            daily_totals[recorded_at] += contribution
        else:
            daily_totals[recorded_at] = contribution

        # A day is estimated if ANY contributing row is estimated.
        row_estimated = row.get("is_estimated", False)
        if recorded_at in daily_estimated:
            daily_estimated[recorded_at] = daily_estimated[recorded_at] or row_estimated
        else:
            daily_estimated[recorded_at] = row_estimated

    # Convert to sorted list of data points.
    data_points = [
        NetWorthHistoryPoint(
            date=date.fromisoformat(d),
            net_worth=total,
            is_estimated=daily_estimated.get(d, False),
        )
        for d, total in sorted(daily_totals.items())
    ]

    return NetWorthHistoryOut(
        period=period,
        data_points=data_points,
        currency="GBP",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_balance(value: object) -> Decimal | None:
    """
    Parse a balance value that may arrive as str, int, float, Decimal, or None.

    Supabase PostgREST returns NUMERIC columns as strings to preserve
    precision.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
