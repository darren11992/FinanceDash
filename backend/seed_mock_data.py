"""
Seed the database with realistic mock transactions and balance history.

Usage:
    cd backend
    source .venv/bin/activate
    python seed_mock_data.py

Reads .env for Supabase credentials. Finds the first active bank_connection
and its user_id automatically — no manual UUID editing needed.

Creates:
  - 2 accounts (current + savings) under the existing connection
  - ~40 transactions spread over the last 30 days
  - 30 days of balance_history for net worth charts

Safe to run multiple times — uses upsert (ON CONFLICT) where possible
and checks for existing seed data before inserting.
"""

import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()  # noqa: E402 — must load before importing app modules

from supabase import create_client  # noqa: E402

from app.config import settings  # noqa: E402


def main() -> None:
    db = create_client(settings.supabase_url, settings.supabase_secret_key)

    # ── Find an existing connection to attach data to ─────────────────────
    conns = (
        db.table("bank_connections")
        .select("id, user_id, provider_name")
        .eq("status", "active")
        .limit(1)
        .execute()
    )

    if not conns.data:
        print("No active bank connections found.")
        print("Connect a bank first (POST /connections/initiate) then re-run.")
        sys.exit(1)

    conn = conns.data[0]
    user_id = conn["user_id"]
    connection_id = conn["id"]
    provider = conn["provider_name"]
    print(f"Using connection: {provider} ({connection_id})")
    print(f"User: {user_id}")

    # ── Create accounts ───────────────────────────────────────────────────
    now = datetime.now(timezone.utc)

    current_account = {
        "user_id": user_id,
        "bank_connection_id": connection_id,
        "truelayer_account_id": "seed-current-001",
        "account_type": "current",
        "display_name": f"{provider} Current Account",
        "currency": "GBP",
        "current_balance": 2847.53,
        "available_balance": 2847.53,
        "balance_updated_at": now.isoformat(),
    }
    savings_account = {
        "user_id": user_id,
        "bank_connection_id": connection_id,
        "truelayer_account_id": "seed-savings-001",
        "account_type": "savings",
        "display_name": f"{provider} Savings",
        "currency": "GBP",
        "current_balance": 12500.00,
        "available_balance": 12500.00,
        "balance_updated_at": now.isoformat(),
    }

    result = (
        db.table("accounts")
        .upsert(
            [current_account, savings_account],
            on_conflict="bank_connection_id,truelayer_account_id",
        )
        .execute()
    )
    current_id = None
    savings_id = None
    for row in result.data:
        if row["truelayer_account_id"] == "seed-current-001":
            current_id = row["id"]
        else:
            savings_id = row["id"]

    print(f"Accounts upserted: current={current_id}, savings={savings_id}")

    # ── Generate transactions ─────────────────────────────────────────────
    # Realistic UK spending patterns over 30 days
    transaction_templates = [
        # (description, amount, type, merchant, category, day_offset)
        ("TESCO STORES 3217", -67.42, "DEBIT", "Tesco", "Groceries", 0),
        ("TFL TRAVEL CHARGE", -2.80, "DEBIT", "Transport for London", "Transport", 0),
        ("PRET A MANGER LONDON", -5.95, "DEBIT", "Pret A Manger", "Eating Out", 1),
        ("SALARY - ACME CORP LTD", 3450.00, "CREDIT", None, "Salary & Income", 1),
        ("AMAZON.CO.UK MARKETPLACE", -24.99, "DEBIT", "Amazon", "Shopping", 2),
        ("DIRECT DEBIT - VODAFONE", -32.00, "DIRECT_DEBIT", "Vodafone", "Bills & Subscriptions", 2),
        ("SAINSBURYS SUPERMARKET", -43.18, "DEBIT", "Sainsbury's", "Groceries", 3),
        ("UBER *TRIP", -12.50, "DEBIT", "Uber", "Transport", 3),
        ("COSTA COFFEE", -3.85, "DEBIT", "Costa Coffee", "Eating Out", 4),
        ("STANDING ORDER - LANDLORD", -1200.00, "STANDING_ORDER", None, "General", 4),
        ("NETFLIX.COM", -15.99, "DEBIT", "Netflix", "Entertainment", 5),
        ("LIDL GB LONDON", -31.26, "DEBIT", "Lidl", "Groceries", 5),
        ("NANDOS RESTAURANTS", -18.90, "DEBIT", "Nando's", "Eating Out", 6),
        ("BP PETROL STATION", -62.30, "DEBIT", "BP", "Transport", 7),
        ("SPOTIFY", -10.99, "DEBIT", "Spotify", "Bills & Subscriptions", 7),
        ("M&S FOOD HALL", -22.47, "DEBIT", "M&S", "Groceries", 8),
        ("GREGGS", -4.20, "DEBIT", "Greggs", "Eating Out", 8),
        ("ATM WITHDRAWAL", -40.00, "DEBIT", None, "Cash & ATM", 9),
        ("PRIMARK STORES", -35.00, "DEBIT", "Primark", "Shopping", 10),
        ("GYM DIRECT DEBIT", -29.99, "DIRECT_DEBIT", "PureGym", "Health & Fitness", 10),
        ("ALDI STORES LTD", -28.73, "DEBIT", "Aldi", "Groceries", 11),
        ("DELIVEROO", -22.45, "DEBIT", "Deliveroo", "Eating Out", 12),
        ("COUNCIL TAX DD", -145.00, "DIRECT_DEBIT", None, "Bills & Subscriptions", 12),
        ("ENERGY COMPANY DD", -89.00, "DIRECT_DEBIT", "Octopus Energy", "Bills & Subscriptions", 13),
        ("TESCO STORES 3217", -54.32, "DEBIT", "Tesco", "Groceries", 14),
        ("JOHN LEWIS OXFORD ST", -79.00, "DEBIT", "John Lewis", "Shopping", 15),
        ("WAGAMAMA LONDON", -28.50, "DEBIT", "Wagamama", "Eating Out", 16),
        ("THREE MOBILE DD", -18.00, "DIRECT_DEBIT", "Three", "Bills & Subscriptions", 17),
        ("TRANSFER FROM SAVINGS", 500.00, "CREDIT", None, "Transfers", 18),
        ("WAITROSE SUPERMARKET", -38.65, "DEBIT", "Waitrose", "Groceries", 19),
        ("CINEMA TICKETS", -24.00, "DEBIT", "Odeon", "Entertainment", 20),
        ("BOOTS PHARMACY", -8.75, "DEBIT", "Boots", "Health & Fitness", 21),
        ("IKEA WEMBLEY", -156.00, "DEBIT", "IKEA", "Shopping", 22),
        ("ALDI STORES LTD", -26.40, "DEBIT", "Aldi", "Groceries", 23),
        ("JUST EAT", -19.50, "DEBIT", "Just Eat", "Eating Out", 24),
        ("WATER BILL DD", -32.00, "DIRECT_DEBIT", "Thames Water", "Bills & Subscriptions", 25),
        ("ASDA SUPERSTORE", -72.31, "DEBIT", "Asda", "Groceries", 26),
        ("UBER *TRIP", -8.90, "DEBIT", "Uber", "Transport", 27),
        ("FREELANCE PAYMENT", 450.00, "CREDIT", None, "Salary & Income", 28),
        ("CURRYS PC WORLD", -299.00, "DEBIT", "Currys", "Shopping", 29),
    ]

    rows = []
    for desc, amount, txn_type, merchant, category, day_offset in transaction_templates:
        txn_id = f"seed-txn-{uuid4().hex[:12]}"
        ts = now - timedelta(days=day_offset, hours=random.randint(8, 20), minutes=random.randint(0, 59))
        rows.append({
            "user_id": user_id,
            "account_id": current_id,
            "truelayer_transaction_id": txn_id,
            "timestamp": ts.isoformat(),
            "description": desc,
            "amount": amount,
            "currency": "GBP",
            "transaction_type": txn_type,
            "merchant_name": merchant,
            "auto_category": category,
        })

    # Savings account: just a couple of interest payments
    for i, day in enumerate([5, 15, 25]):
        rows.append({
            "user_id": user_id,
            "account_id": savings_id,
            "truelayer_transaction_id": f"seed-txn-savings-{i}",
            "timestamp": (now - timedelta(days=day)).isoformat(),
            "description": "INTEREST PAYMENT",
            "amount": round(random.uniform(8.0, 15.0), 2),
            "currency": "GBP",
            "transaction_type": "CREDIT",
            "merchant_name": None,
            "auto_category": "Salary & Income",
        })

    result = (
        db.table("transactions")
        .upsert(rows, on_conflict="account_id,truelayer_transaction_id")
        .execute()
    )
    print(f"Transactions upserted: {len(result.data)}")

    # ── Balance history (30 days) ─────────────────────────────────────────
    # Simulate a realistic current account balance over time
    balance_rows = []
    base_balance = Decimal("1200.00")

    for day in range(30, -1, -1):
        date_str = (now - timedelta(days=day)).strftime("%Y-%m-%d")

        # Salary bump on day ~28 ago
        if day <= 28:
            base_balance += Decimal("3450.00") if day == 28 else Decimal("0")

        # Random daily spend
        daily_change = Decimal(str(round(random.uniform(-80, -10), 2)))
        if day == 18:
            daily_change += Decimal("500.00")  # transfer in
        base_balance += daily_change

        balance_rows.append({
            "user_id": user_id,
            "account_id": current_id,
            "balance": float(base_balance),
            "recorded_at": date_str,
        })

        # Savings — slow growth
        balance_rows.append({
            "user_id": user_id,
            "account_id": savings_id,
            "balance": float(Decimal("12450.00") + Decimal(str(day)) * Decimal("1.50")),
            "recorded_at": date_str,
        })

    result = (
        db.table("balance_history")
        .upsert(balance_rows, on_conflict="account_id,recorded_at")
        .execute()
    )
    print(f"Balance history upserted: {len(result.data)} data points")

    # ── Update connection last_synced_at ──────────────────────────────────
    db.table("bank_connections").update({
        "last_synced_at": now.isoformat(),
    }).eq("id", connection_id).execute()

    print("\nDone! Seed data populated successfully.")
    print("Refresh the transactions screen to see data.")


if __name__ == "__main__":
    main()
