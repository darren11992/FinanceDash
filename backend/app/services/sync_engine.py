"""
Sync engine — orchestrates periodic data fetching from TrueLayer.

Responsibilities:
- Iterate over active bank connections
- Refresh tokens if near expiry
- Fetch accounts, balances, and transactions
- Upsert data with deduplication (ON CONFLICT)
- Record balance history snapshots
- Handle errors per-connection without failing the entire batch

Sprint 3: Full implementation.
"""
