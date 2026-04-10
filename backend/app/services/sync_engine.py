"""
Sync engine — orchestrates periodic data fetching from TrueLayer.

Responsibilities:
- Iterate over active bank connections
- Refresh tokens if near expiry
- Fetch accounts, balances, and transactions
- Upsert data with deduplication (ON CONFLICT)
- Record balance history snapshots
- Handle errors per-connection without failing the entire batch

Implements the sync flow described in ARCH.md §5.3.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from postgrest.exceptions import APIError
from supabase import Client

from app.services.categorisation import categorise_transaction
from app.services.encryption import decrypt_token, encrypt_token
from app.services.truelayer import TrueLayerClient, TrueLayerError

logger = logging.getLogger(__name__)

# How far back to fetch on the first sync for an account.
INITIAL_SYNC_LOOKBACK_DAYS = 365

# Overlap window for incremental syncs to catch late-arriving transactions.
INCREMENTAL_OVERLAP_DAYS = 2

# Refresh the access token if it expires within this many minutes.
TOKEN_REFRESH_THRESHOLD_MINUTES = 5

# Simple in-memory lock set to prevent concurrent syncs of the same connection.
# In production with multiple workers, replace with Redis or DB-level locking.
_syncing_connections: set[str] = set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def sync_connection(
    connection_id: str,
    db: Client,
    truelayer_client: TrueLayerClient,
) -> dict:
    """
    Full sync for a single bank connection.

    Follows the flow in ARCH.md §5.3:
      1. Check consent expiry
      2. Refresh token if near expiry
      3. Fetch accounts + balances (accounts & cards)
      4. Fetch transactions
      5. Update last_synced_at

    Returns a summary dict:
        {"status": "ok"|"skipped"|"error", "detail": "...", "accounts_synced": N, "transactions_synced": N}
    """
    # Connection-level lock
    if connection_id in _syncing_connections:
        logger.info("Sync already in progress for connection %s, skipping", connection_id)
        return {"status": "skipped", "detail": "Sync already in progress"}

    _syncing_connections.add(connection_id)
    try:
        return await _execute_sync(connection_id, db, truelayer_client)
    finally:
        _syncing_connections.discard(connection_id)


async def sync_all_active_connections(
    db: Client,
    truelayer_client: TrueLayerClient,
) -> list[dict]:
    """
    Sync all active bank connections.

    Called by the scheduled job every 4 hours and by the POST /sync endpoint.
    Processes connections sequentially to avoid overwhelming TrueLayer's rate limits.
    Returns a list of per-connection result dicts.
    """
    result = (
        db.table("bank_connections")
        .select("id")
        .in_("status", ["active", "expiring_soon", "error"])
        .execute()
    )

    results = []
    for conn in result.data:
        summary = await sync_connection(conn["id"], db, truelayer_client)
        results.append({"connection_id": conn["id"], **summary})

    return results


async def sync_user_connections(
    user_id: str,
    db: Client,
    truelayer_client: TrueLayerClient,
) -> list[dict]:
    """
    Sync all active connections for a specific user.

    Called by POST /api/v1/sync when triggered by the authenticated user.
    """
    result = (
        db.table("bank_connections")
        .select("id, status")
        .eq("user_id", user_id)
        .execute()
    )

    logger.info(
        "sync_user_connections: user=%s, all connections=%s",
        user_id, result.data,
    )

    # Filter to syncable connections. Include "error" so that transient
    # failures (like the account_type parsing bug) are retried on the next sync.
    SYNCABLE_STATUSES = {"active", "expiring_soon", "error"}
    active_connections = [
        c for c in result.data
        if c.get("status") in SYNCABLE_STATUSES
    ]

    if not active_connections:
        logger.warning(
            "sync_user_connections: no active connections for user %s "
            "(found %d total with statuses: %s)",
            user_id,
            len(result.data),
            [c.get("status") for c in result.data],
        )

    results = []
    for conn in active_connections:
        summary = await sync_connection(conn["id"], db, truelayer_client)
        results.append({"connection_id": conn["id"], **summary})

    return results


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


async def _execute_sync(
    connection_id: str,
    db: Client,
    truelayer_client: TrueLayerClient,
) -> dict:
    """Core sync logic for a single connection. See ARCH.md §5.3."""

    # Fetch the connection row (need tokens, user_id, consent/token expiry).
    conn_result = (
        db.table("bank_connections")
        .select("*")
        .eq("id", connection_id)
        .execute()
    )

    if not conn_result.data:
        logger.warning("Connection %s not found, skipping sync", connection_id)
        return {"status": "error", "detail": "Connection not found"}

    conn = conn_result.data[0]
    user_id = conn["user_id"]
    now = datetime.now(timezone.utc)

    # ── Step 1: Check consent expiry ──────────────────────────────────────
    consent_expires_at = datetime.fromisoformat(conn["consent_expires_at"])

    if consent_expires_at <= now:
        # Consent has expired — mark and skip.
        _update_connection_status(db, connection_id, "expired", "Consent expired")
        logger.info("Connection %s consent expired, skipping", connection_id)
        return {"status": "skipped", "detail": "Consent expired"}

    if consent_expires_at <= now + timedelta(days=7):
        # Consent expiring soon — update status but continue syncing.
        _update_connection_status(db, connection_id, "expiring_soon")
        logger.info("Connection %s consent expiring soon", connection_id)

    # ── Step 2: Check / refresh access token ──────────────────────────────
    token_expires_at = datetime.fromisoformat(conn["token_expires_at"])
    access_token = decrypt_token(conn["access_token"])
    refresh_token = decrypt_token(conn["refresh_token"])

    if token_expires_at <= now + timedelta(minutes=TOKEN_REFRESH_THRESHOLD_MINUTES):
        # Token expired or about to expire — refresh it.
        logger.info("Refreshing token for connection %s", connection_id)
        try:
            token_data = await truelayer_client.refresh_access_token(refresh_token)
        except TrueLayerError as e:
            error_msg = f"Token refresh failed: {e}"
            _update_connection_status(db, connection_id, "error", error_msg)
            logger.error("Connection %s: %s", connection_id, error_msg)
            return {"status": "error", "detail": error_msg}

        access_token = token_data["access_token"]
        new_refresh = token_data["refresh_token"]
        new_expires = token_data["token_expires_at"]

        # Store refreshed tokens (encrypted).
        db.table("bank_connections").update({
            "access_token": encrypt_token(access_token),
            "refresh_token": encrypt_token(new_refresh),
            "token_expires_at": new_expires.isoformat(),
        }).eq("id", connection_id).execute()

    # ── Step 3: Fetch accounts + balances + transactions ──────────────────
    accounts_synced = 0
    transactions_synced = 0

    try:
        accounts_synced, transactions_synced = await _sync_accounts_and_transactions(
            db=db,
            truelayer_client=truelayer_client,
            access_token=access_token,
            connection_id=connection_id,
            user_id=user_id,
            last_synced_at=conn.get("last_synced_at"),
        )
    except TrueLayerError as e:
        error_msg = f"Data fetch failed: {e}"
        _update_connection_status(db, connection_id, "error", error_msg)
        logger.error("Connection %s: %s", connection_id, error_msg)
        return {
            "status": "error",
            "detail": error_msg,
            "accounts_synced": accounts_synced,
            "transactions_synced": transactions_synced,
        }
    except (APIError, httpx.HTTPError) as e:
        error_msg = f"Unexpected error during sync: {e}"
        _update_connection_status(db, connection_id, "error", error_msg)
        logger.exception("Connection %s: %s", connection_id, error_msg)
        return {
            "status": "error",
            "detail": error_msg,
            "accounts_synced": accounts_synced,
            "transactions_synced": transactions_synced,
        }

    # ── Step 4: Update last_synced_at, clear errors ───────────────────────
    # Only reset to "active" if not already "expiring_soon".
    current_status = conn.get("status", "active")
    new_status = "active" if current_status != "expiring_soon" else "expiring_soon"

    db.table("bank_connections").update({
        "last_synced_at": now.isoformat(),
        "status": new_status,
        "error_message": None,
    }).eq("id", connection_id).execute()

    logger.info(
        "Connection %s synced: %d accounts, %d transactions",
        connection_id, accounts_synced, transactions_synced,
    )

    return {
        "status": "ok",
        "detail": "Sync completed successfully",
        "accounts_synced": accounts_synced,
        "transactions_synced": transactions_synced,
    }


async def _sync_accounts_and_transactions(
    db: Client,
    truelayer_client: TrueLayerClient,
    access_token: str,
    connection_id: str,
    user_id: str,
    last_synced_at: str | None,
) -> tuple[int, int]:
    """
    Fetch accounts (regular + cards), balances, and transactions.

    Returns (accounts_synced, transactions_synced) counts.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    accounts_synced = 0
    transactions_synced = 0

    # ── Regular bank accounts ─────────────────────────────────────────────
    try:
        accounts = await truelayer_client.get_accounts(access_token)
    except TrueLayerError as e:
        logger.warning("Failed to fetch accounts for connection %s: %s", connection_id, e)
        accounts = []

    for acct in accounts:
        acct_synced, txn_synced = await _sync_single_account(
            db=db,
            truelayer_client=truelayer_client,
            access_token=access_token,
            connection_id=connection_id,
            user_id=user_id,
            last_synced_at=last_synced_at,
            today_str=today_str,
            tl_account_id=acct.get("account_id", ""),
            account_type=_map_account_type(_extract_account_type(acct.get("account_type"))),
            display_name=acct.get("display_name", "Unknown Account"),
            currency=acct.get("currency", "GBP"),
            is_card=False,
        )
        accounts_synced += acct_synced
        transactions_synced += txn_synced

    # ── Credit cards ──────────────────────────────────────────────────────
    try:
        cards = await truelayer_client.get_cards(access_token)
    except TrueLayerError as e:
        logger.warning("Failed to fetch cards for connection %s: %s", connection_id, e)
        cards = []

    for card in cards:
        acct_synced, txn_synced = await _sync_single_account(
            db=db,
            truelayer_client=truelayer_client,
            access_token=access_token,
            connection_id=connection_id,
            user_id=user_id,
            last_synced_at=last_synced_at,
            today_str=today_str,
            tl_account_id=card.get("account_id", ""),
            account_type="credit_card",
            display_name=card.get("display_name", "Unknown Card"),
            currency=card.get("currency", "GBP"),
            is_card=True,
        )
        accounts_synced += acct_synced
        transactions_synced += txn_synced

    return accounts_synced, transactions_synced


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _sync_single_account(
    db: Client,
    truelayer_client: TrueLayerClient,
    access_token: str,
    connection_id: str,
    user_id: str,
    last_synced_at: str | None,
    today_str: str,
    tl_account_id: str,
    account_type: str,
    display_name: str,
    currency: str,
    is_card: bool,
) -> tuple[int, int]:
    """
    Upsert a single account/card, fetch its balance and transactions.

    Handles balance and transaction fetch failures per-account (logs warning,
    continues) as per ARCH.md §5.5 partial-failure strategy.

    On initial sync (last_synced_at is None), also backfills historical
    balance_history from synced transaction data.

    Returns (accounts_synced, transactions_synced) — always (1, N) on success.
    """
    # Upsert the account row.
    account_id = _upsert_account(
        db=db,
        user_id=user_id,
        connection_id=connection_id,
        tl_account_id=tl_account_id,
        account_type=account_type,
        display_name=display_name,
        currency=currency,
    )

    # Fetch balance (best-effort, continue on failure).
    current_balance = None
    try:
        if is_card:
            balance_data = await truelayer_client.get_card_balance(access_token, tl_account_id)
        else:
            balance_data = await truelayer_client.get_account_balance(access_token, tl_account_id)
        current_balance = balance_data.get("current")
        _update_balance(db, user_id, account_id, balance_data, today_str)
    except TrueLayerError as e:
        logger.warning("Failed to fetch balance for %s %s: %s",
                        "card" if is_card else "account", tl_account_id, e)

    # Fetch transactions (best-effort per ARCH.md §5.5).
    transactions_synced = 0
    try:
        transactions_synced = await _sync_transactions_for_account(
            db=db,
            truelayer_client=truelayer_client,
            access_token=access_token,
            account_id=account_id,
            tl_account_id=tl_account_id,
            user_id=user_id,
            last_synced_at=last_synced_at,
            today_str=today_str,
            is_card=is_card,
        )
    except TrueLayerError as e:
        logger.warning("Failed to fetch transactions for %s %s: %s",
                        "card" if is_card else "account", tl_account_id, e)

    # On initial sync, backfill historical balance_history from transactions.
    if last_synced_at is None and transactions_synced > 0:
        logger.info(
            "Backfill: triggering for account %s (current_balance=%s, today=%s)",
            account_id, current_balance, today_str,
        )
        try:
            _backfill_balance_history(
                db=db,
                user_id=user_id,
                account_id=account_id,
                current_balance=current_balance,
                today_str=today_str,
            )
        except (APIError, ValueError, TypeError) as e:
            # Non-fatal — the chart will just have fewer data points.
            logger.warning(
                "Balance history backfill failed for account %s: %s",
                account_id, e,
                exc_info=True,
            )
    else:
        logger.info(
            "Backfill: skipped for account %s (last_synced_at=%s, transactions_synced=%d)",
            account_id, last_synced_at, transactions_synced,
        )

    return 1, transactions_synced


def _extract_account_type(account_type_field: object) -> str:
    """
    Extract the account type string from TrueLayer's account_type field.

    TrueLayer returns account_type in different shapes depending on the provider:
      - Nested object: {"type": "TRANSACTION"}  (live providers)
      - Plain string:  "TRANSACTION"             (sandbox mock bank)

    This helper normalises both to a plain string.
    """
    if isinstance(account_type_field, dict):
        return account_type_field.get("type", "")
    if isinstance(account_type_field, str):
        return account_type_field
    return ""


def _map_account_type(tl_type: str) -> str:
    """Map TrueLayer account_type to our schema enum."""
    tl_type_lower = tl_type.lower()
    if "savings" in tl_type_lower:
        return "savings"
    if "credit" in tl_type_lower or "card" in tl_type_lower:
        return "credit_card"
    # Default to current for TRANSACTION, CHECKING, etc.
    return "current"


def _upsert_account(
    db: Client,
    user_id: str,
    connection_id: str,
    tl_account_id: str,
    account_type: str,
    display_name: str,
    currency: str,
) -> str:
    """
    Insert or update an account row. Returns the account UUID.

    Uses the UNIQUE(bank_connection_id, truelayer_account_id) constraint.
    """
    row = {
        "user_id": user_id,
        "bank_connection_id": connection_id,
        "truelayer_account_id": tl_account_id,
        "account_type": account_type,
        "display_name": display_name,
        "currency": currency,
    }

    result = (
        db.table("accounts")
        .upsert(row, on_conflict="bank_connection_id,truelayer_account_id")
        .execute()
    )

    return result.data[0]["id"]


def _update_balance(
    db: Client,
    user_id: str,
    account_id: str,
    balance_data: dict,
    today_str: str,
) -> None:
    """
    Update the account's current/available balance and record a balance_history snapshot.
    """
    current = balance_data.get("current")
    available = balance_data.get("available")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Update account balance.
    db.table("accounts").update({
        "current_balance": current,
        "available_balance": available,
        "balance_updated_at": now_iso,
    }).eq("id", account_id).execute()

    # Upsert today's balance_history snapshot (authoritative, not estimated).
    # UNIQUE(account_id, recorded_at) prevents duplicates for same day.
    if current is not None:
        db.table("balance_history").upsert(
            {
                "user_id": user_id,
                "account_id": account_id,
                "balance": current,
                "recorded_at": today_str,
                "is_estimated": False,
            },
            on_conflict="account_id,recorded_at",
        ).execute()


def _update_connection_status(
    db: Client,
    connection_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Helper to update a connection's status and error_message."""
    update = {"status": status, "error_message": error_message}
    db.table("bank_connections").update(update).eq("id", connection_id).execute()


async def _sync_transactions_for_account(
    db: Client,
    truelayer_client: TrueLayerClient,
    access_token: str,
    account_id: str,
    tl_account_id: str,
    user_id: str,
    last_synced_at: str | None,
    today_str: str,
    is_card: bool,
) -> int:
    """
    Fetch and upsert transactions for a single account/card.

    Date range logic (per ARCH.md §5.3 step 4):
      - First sync: 12 months back
      - Incremental: last_synced_at minus 2-day overlap

    Returns the number of transactions upserted.
    """
    now = datetime.now(timezone.utc)

    if last_synced_at:
        # Incremental sync — overlap by 2 days to catch stragglers.
        from_dt = datetime.fromisoformat(last_synced_at) - timedelta(days=INCREMENTAL_OVERLAP_DAYS)
    else:
        # Initial sync — go back 12 months.
        from_dt = now - timedelta(days=INITIAL_SYNC_LOOKBACK_DAYS)

    from_date = from_dt.strftime("%Y-%m-%d")
    to_date = today_str

    # Fetch from the appropriate endpoint (accounts vs cards).
    if is_card:
        raw_txns = await truelayer_client.get_card_transactions(
            access_token, tl_account_id, from_date, to_date
        )
    else:
        raw_txns = await truelayer_client.get_transactions(
            access_token, tl_account_id, from_date, to_date
        )

    if not raw_txns:
        return 0

    # Build upsert rows.
    rows = []
    for txn in raw_txns:
        tl_txn_id = txn.get("transaction_id", "")
        if not tl_txn_id:
            logger.warning("Transaction missing transaction_id, skipping: %s", txn)
            continue

        classification = txn.get("transaction_classification", [])
        if not isinstance(classification, list):
            classification = [classification] if classification else []

        meta = txn.get("meta")
        merchant = txn.get("merchant_name") or (
            meta.get("provider_merchant_name") if isinstance(meta, dict) else None
        )

        running_bal = txn.get("running_balance")
        running_bal_amount = (
            running_bal.get("amount") if isinstance(running_bal, dict) else None
        )

        description = txn.get("description", "")

        rows.append({
            "user_id": user_id,
            "account_id": account_id,
            "truelayer_transaction_id": tl_txn_id,
            "timestamp": txn.get("timestamp", now.isoformat()),
            "description": description,
            "amount": txn.get("amount", 0),
            "currency": txn.get("currency", "GBP"),
            "transaction_type": txn.get("transaction_type"),
            "merchant_name": merchant,
            "auto_category": categorise_transaction(classification, merchant, description),
            "running_balance": running_bal_amount,
            "metadata": {
                k: v for k, v in txn.items()
                if k not in (
                    "transaction_id", "timestamp", "description", "amount",
                    "currency", "transaction_type", "merchant_name",
                    "transaction_classification", "running_balance",
                )
            },
        })

    if not rows:
        return 0

    # Upsert with deduplication per ARCH.md §5.4.
    # ON CONFLICT (account_id, truelayer_transaction_id) DO UPDATE
    # — updates mutable fields but preserves user_category.
    #
    # PostgREST UPSERT merges provided columns only — columns NOT in the
    # payload (like user_category) are left untouched.
    result = (
        db.table("transactions")
        .upsert(rows, on_conflict="account_id,truelayer_transaction_id")
        .execute()
    )

    return len(result.data)


# ---------------------------------------------------------------------------
# Balance history backfill
# ---------------------------------------------------------------------------


def _backfill_balance_history(
    db: Client,
    user_id: str,
    account_id: str,
    current_balance: float | None,
    today_str: str,
) -> None:
    """
    Reconstruct historical daily balances from synced transactions.

    Two-tier strategy:
      1. **Preferred**: Use running_balance from transactions (authoritative
         bank-provided value). Take the last transaction per day and use its
         running_balance as that day's closing balance. Marked is_estimated=False.
      2. **Fallback**: If running_balance is NULL, reverse-compute from the
         current known balance by walking backwards through transactions.
         Marked is_estimated=True (approximation — see docstring caveats).

    Only runs on initial sync (when balance_history has at most today's
    snapshot). Does NOT overwrite existing rows — uses ON CONFLICT DO NOTHING
    style by only inserting dates that don't already exist.
    """
    # Fetch ALL transactions for this account, ordered by timestamp ASC.
    # PostgREST has a default row limit (typically 1000), so we must
    # paginate to ensure we get every transaction.
    PAGE_SIZE = 1000
    transactions: list[dict] = []
    offset = 0

    while True:
        page = (
            db.table("transactions")
            .select("timestamp, amount, running_balance")
            .eq("account_id", account_id)
            .order("timestamp")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        transactions.extend(page.data)
        if len(page.data) < PAGE_SIZE:
            break  # Last page — no more rows.
        offset += PAGE_SIZE

    if not transactions:
        logger.debug("Backfill: no transactions for account %s", account_id)
        return

    logger.info(
        "Backfill: fetched %d transactions for account %s "
        "(first running_balance samples: %s)",
        len(transactions),
        account_id,
        [txn.get("running_balance") for txn in transactions[:5]],
    )

    # Check if running_balance is available (check first few transactions).
    has_running_balance = any(
        _parse_numeric(txn.get("running_balance")) is not None
        for txn in transactions[:10]
    )

    if has_running_balance:
        daily_balances = _backfill_from_running_balance(transactions)
        is_estimated = False
        logger.info(
            "Backfill: using running_balance for account %s (%d days)",
            account_id, len(daily_balances),
        )
    elif current_balance is not None:
        daily_balances = _backfill_from_reverse_compute(
            transactions, current_balance, today_str,
        )
        is_estimated = True
        logger.info(
            "Backfill: using reverse-compute for account %s (%d days, estimated)",
            account_id, len(daily_balances),
        )
    else:
        logger.debug(
            "Backfill: no running_balance and no current_balance for account %s",
            account_id,
        )
        return

    if not daily_balances:
        logger.info("Backfill: no daily balances computed for account %s", account_id)
        return

    logger.info(
        "Backfill: computed %d daily balances for account %s (date range: %s to %s)",
        len(daily_balances),
        account_id,
        min(daily_balances.keys()),
        max(daily_balances.keys()),
    )

    # Check which dates already exist to avoid overwriting live snapshots.
    existing_result = (
        db.table("balance_history")
        .select("recorded_at")
        .eq("account_id", account_id)
        .execute()
    )
    existing_dates = {row["recorded_at"] for row in existing_result.data}

    logger.info(
        "Backfill: %d existing dates in balance_history for account %s",
        len(existing_dates), account_id,
    )

    # Build rows for dates that don't already exist.
    rows = [
        {
            "user_id": user_id,
            "account_id": account_id,
            "balance": balance,
            "recorded_at": date_str,
            "is_estimated": is_estimated,
        }
        for date_str, balance in daily_balances.items()
        if date_str not in existing_dates
    ]

    if not rows:
        logger.info("Backfill: all dates already exist for account %s", account_id)
        return

    # Batch upsert (on_conflict to handle any race conditions).
    db.table("balance_history").upsert(
        rows, on_conflict="account_id,recorded_at",
    ).execute()

    logger.info(
        "Backfill: inserted %d historical balance rows for account %s",
        len(rows), account_id,
    )


def _backfill_from_running_balance(
    transactions: list[dict],
) -> dict[str, float]:
    """
    Extract daily closing balances from running_balance on transactions.

    For each day, takes the running_balance of the LAST transaction of
    that day as the closing balance. Days with no transactions are
    forward-filled from the previous day.

    Returns {date_str: balance} dict.
    """
    # Group: last running_balance per day.
    day_balances: dict[str, float] = {}

    for txn in transactions:
        rb = _parse_numeric(txn.get("running_balance"))
        if rb is None:
            continue
        timestamp = txn.get("timestamp", "")
        day_str = timestamp[:10]  # "YYYY-MM-DD"
        if len(day_str) == 10:
            # Last-write-wins since transactions are ordered ASC.
            day_balances[day_str] = rb

    if not day_balances:
        return {}

    # Forward-fill gaps between dates.
    return _forward_fill(day_balances)


def _backfill_from_reverse_compute(
    transactions: list[dict],
    current_balance: float,
    today_str: str,
) -> dict[str, float]:
    """
    Reverse-compute historical balances from current balance and transactions.

    Starts with today's known balance and walks backwards through
    transactions, reversing each one's effect to derive what the
    balance was on prior days.

    Returns {date_str: balance} dict. All values are estimates.
    """
    # Group net daily movement: sum of all transaction amounts per day.
    daily_movement: dict[str, float] = {}

    for txn in transactions:
        timestamp = txn.get("timestamp", "")
        day_str = timestamp[:10]
        if len(day_str) != 10:
            continue
        amount = _parse_numeric(txn.get("amount"))
        if amount is None:
            continue
        daily_movement[day_str] = daily_movement.get(day_str, 0) + amount

    if not daily_movement:
        return {}

    # Sort days ascending.
    sorted_days = sorted(daily_movement.keys())

    # Walk backwards from today_str.
    # The balance at end of day D = balance at end of day D+1 - movement on D+1.
    day_balances: dict[str, float] = {today_str: current_balance}
    balance = current_balance

    # Build a complete day range from the day before the earliest
    # transaction to today.  The extra day captures the opening balance
    # before any transactions occurred.
    from datetime import date as date_type

    earliest = date_type.fromisoformat(sorted_days[0])
    one_day_before_earliest = earliest - timedelta(days=1)
    today = date_type.fromisoformat(today_str)
    current = today

    while current >= one_day_before_earliest:
        current_str = current.isoformat()
        if current_str == today_str:
            # Already set.
            current -= timedelta(days=1)
            continue

        # The next day's movement tells us what happened the day after.
        next_day = current + timedelta(days=1)
        next_day_str = next_day.isoformat()
        next_movement = daily_movement.get(next_day_str, 0)

        # Reverse: balance at end of current day = balance at end of next day - next day's movement.
        balance = balance - next_movement
        day_balances[current_str] = round(balance, 2)

        current -= timedelta(days=1)

    return day_balances


def _forward_fill(day_balances: dict[str, float]) -> dict[str, float]:
    """
    Fill gaps between dates by carrying forward the previous day's balance.

    Input: sparse {date_str: balance} dict.
    Output: dense {date_str: balance} dict with every date covered.
    """
    from datetime import date as date_type

    if not day_balances:
        return {}

    sorted_dates = sorted(day_balances.keys())
    start = date_type.fromisoformat(sorted_dates[0])
    end = date_type.fromisoformat(sorted_dates[-1])

    filled: dict[str, float] = {}
    current = start
    last_balance = day_balances[sorted_dates[0]]

    while current <= end:
        current_str = current.isoformat()
        if current_str in day_balances:
            last_balance = day_balances[current_str]
        filled[current_str] = last_balance
        current += timedelta(days=1)

    return filled


def _parse_numeric(value: object) -> float | None:
    """Parse a numeric value that may be str, int, float, or None."""
    if value is None:
        return None
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None
