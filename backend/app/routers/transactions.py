"""
Transactions router.

Endpoints for viewing and managing transactions:
- GET   /transactions              — paginated, filterable transaction list
- PATCH /transactions/{id}/category — manual category override
"""

import logging
import re
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from postgrest.exceptions import APIError
from supabase import Client

from app.dependencies import get_current_user, get_supabase
from app.models.schemas import (
    CategoryUpdateIn,
    CategoryUpdateOut,
    RecategoriseOut,
    TransactionListOut,
    TransactionOut,
)
from app.rate_limit import limiter
from app.services.categorisation import categorise_transaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ---------------------------------------------------------------------------
# GET /transactions
# ---------------------------------------------------------------------------


@router.get("/", response_model=TransactionListOut)
async def list_transactions(
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
    account_id: UUID | None = Query(None, description="Filter by account ID"),
    category: str | None = Query(None, description="Filter by category (matches user_category or auto_category)"),
    from_date: date | None = Query(None, alias="from", description="Start date (inclusive, YYYY-MM-DD)"),
    to_date: date | None = Query(None, alias="to", description="End date (inclusive, YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page (max 200)"),
):
    """
    List transactions for the authenticated user with optional filters.

    Supports filtering by:
    - account_id: restrict to a single account
    - category: match against COALESCE(user_category, auto_category)
    - from/to: date range (inclusive)

    Results are paginated and sorted by timestamp descending (newest first).
    """
    # Validate category before any DB operations — prevent PostgREST
    # filter injection via crafted query params.
    if category is not None and not re.match(r'^[\w &/-]+$', category):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid category name",
        )

    try:
        # Build the base query for counting total matches.
        count_query = (
            db.table("transactions")
            .select("id", count="exact")
            .eq("user_id", user_id)
        )

        # Build the data query.
        data_query = (
            db.table("transactions")
            .select("*")
            .eq("user_id", user_id)
        )

        # Apply filters to both queries.
        if account_id is not None:
            count_query = count_query.eq("account_id", str(account_id))
            data_query = data_query.eq("account_id", str(account_id))

        if from_date is not None:
            # Transactions on or after from_date (start of day).
            from_iso = f"{from_date.isoformat()}T00:00:00+00:00"
            count_query = count_query.gte("timestamp", from_iso)
            data_query = data_query.gte("timestamp", from_iso)

        if to_date is not None:
            # Transactions on or before to_date (end of day).
            to_iso = f"{to_date.isoformat()}T23:59:59.999999+00:00"
            count_query = count_query.lte("timestamp", to_iso)
            data_query = data_query.lte("timestamp", to_iso)

        # Category filter — PostgREST doesn't support COALESCE in filters,
        # so we filter by both columns with an OR condition.
        if category is not None:
            count_query = count_query.or_(
                f"user_category.eq.{category},auto_category.eq.{category}"
            )
            data_query = data_query.or_(
                f"user_category.eq.{category},auto_category.eq.{category}"
            )

        # Execute count query.
        count_result = count_query.execute()
        total = count_result.count if count_result.count is not None else 0

        # Apply pagination and ordering to data query.
        offset = (page - 1) * page_size
        data_query = (
            data_query
            .order("timestamp", desc=True)
            .range(offset, offset + page_size - 1)
        )

        data_result = data_query.execute()

    except APIError as e:
        logger.error("Failed to list transactions for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transactions",
        )

    # Map rows to response schema, computing the effective category.
    transactions = [
        TransactionOut(
            id=row["id"],
            account_id=row["account_id"],
            timestamp=row["timestamp"],
            description=row["description"],
            amount=row["amount"],
            currency=row.get("currency", "GBP"),
            transaction_type=row.get("transaction_type"),
            merchant_name=row.get("merchant_name"),
            category=row.get("user_category") or row.get("auto_category"),
            running_balance=row.get("running_balance"),
        )
        for row in data_result.data
    ]

    return TransactionListOut(
        transactions=transactions,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + page_size) < total,
    )


# ---------------------------------------------------------------------------
# POST /transactions/recategorise
# ---------------------------------------------------------------------------

PAGE_SIZE = 1000


@router.post("/recategorise", response_model=RecategoriseOut)
@limiter.limit("5/minute")
async def recategorise_transactions(
    request: Request,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Re-run the categorisation engine on ALL existing transactions.

    Useful after updating categorisation rules so that historical
    transactions get proper categories instead of "General".

    - Only updates ``auto_category`` — ``user_category`` overrides are
      preserved and those rows are skipped entirely.
    - Processes transactions in batches to handle large volumes.
    """
    total_reviewed = 0
    updated = 0
    skipped_user_override = 0

    try:
        offset = 0
        while True:
            result = (
                db.table("transactions")
                .select("id, description, merchant_name, auto_category, user_category")
                .eq("user_id", user_id)
                .order("timestamp", desc=True)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )

            rows = result.data
            if not rows:
                break

            for row in rows:
                total_reviewed += 1

                # Skip transactions with manual overrides.
                if row.get("user_category"):
                    skipped_user_override += 1
                    continue

                # Re-categorise from description.
                # Note: transaction_classification is not stored in the DB
                # (only used at sync time), so we pass None here.
                merchant = row.get("merchant_name")
                description = row.get("description") or ""

                new_category = categorise_transaction(
                    None, merchant, description
                )

                # Only update if the category actually changed.
                old_category = row.get("auto_category")
                if new_category != old_category:
                    db.table("transactions").update(
                        {"auto_category": new_category}
                    ).eq("id", row["id"]).execute()
                    updated += 1

            # If we got fewer rows than PAGE_SIZE, we've reached the end.
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

    except APIError as e:
        logger.error(
            "Failed to recategorise transactions for user %s: %s",
            user_id, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to recategorise transactions",
        )

    logger.info(
        "Recategorised transactions for user %s: %d reviewed, %d updated, %d skipped (user override)",
        user_id, total_reviewed, updated, skipped_user_override,
    )

    return RecategoriseOut(
        total_reviewed=total_reviewed,
        updated=updated,
        skipped_user_override=skipped_user_override,
    )


# ---------------------------------------------------------------------------
# PATCH /transactions/{transaction_id}/category
# ---------------------------------------------------------------------------


@router.patch("/{transaction_id}/category", response_model=CategoryUpdateOut)
async def update_category(
    transaction_id: UUID,
    body: CategoryUpdateIn,
    user_id: str = Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """
    Manually override the category for a transaction.

    Send `{"category": "Groceries"}` to set a manual category, or
    `{"category": null}` to revert to the auto-categorised value.

    The override is stored in `user_category` and persists across syncs
    (the sync engine never overwrites user_category).
    """
    # Verify the transaction belongs to this user.
    try:
        check = (
            db.table("transactions")
            .select("id, auto_category, user_category")
            .eq("id", str(transaction_id))
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as e:
        logger.error("Failed to fetch transaction %s for user %s: %s", transaction_id, user_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transaction",
        )

    if not check.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )

    # Update user_category.
    try:
        db.table("transactions").update({
            "user_category": body.category,
        }).eq("id", str(transaction_id)).execute()
    except APIError as e:
        logger.error("Failed to update category for transaction %s: %s", transaction_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update category",
        )

    # Return the effective category after the update.
    effective_category = body.category if body.category is not None else check.data[0].get("auto_category")

    return CategoryUpdateOut(
        transaction_id=transaction_id,
        category=effective_category,
        is_user_override=body.category is not None,
    )
