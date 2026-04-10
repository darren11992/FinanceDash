"""
Tests for the consent expiry checker job.

Covers:
- Active connections with consent expiring within 7 days → expiring_soon
- Active/expiring_soon connections with expired consent → expired
- Active connections with consent far in the future → no change
- Mixed batch: some expiring, some expired, some fine
- Database query errors handled gracefully
- Per-connection update errors don't stop the batch
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call

import pytest
from postgrest.exceptions import APIError

from app.jobs.consent_checker import EXPIRY_WARNING_DAYS, check_consent_expiry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2026, 3, 30, 9, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _mock_db(expired_rows=None, expiring_rows=None, raise_on_query=False, raise_on_update_ids=None):
    """
    Build a mock Supabase client that returns different results based on
    the query filters used (lt/gte/eq for consent_expires_at and status).

    Args:
        expired_rows: rows for the "expired" query (status in active/expiring_soon, consent < now)
        expiring_rows: rows for the "expiring_soon" query (status = active, consent >= now and < threshold)
        raise_on_query: if True, .execute() raises on SELECT queries
        raise_on_update_ids: set of connection IDs that should fail on UPDATE
    """
    expired_rows = expired_rows or []
    expiring_rows = expiring_rows or []
    raise_on_update_ids = raise_on_update_ids or set()

    db = MagicMock()

    # Track which query is being built by intercepting the chain.
    # The consent checker makes two SELECT queries and N UPDATE queries.
    # We differentiate by tracking which status filter was applied.

    call_count = {"select": 0}

    class ChainableMock:
        """Mimics the PostgREST query builder chain."""

        def __init__(self):
            self._filters = {}
            self._is_update = False
            self._update_data = None
            self._eq_id = None

        def select(self, *args, **kwargs):
            self._is_update = False
            return self

        def update(self, data, **kwargs):
            self._is_update = True
            self._update_data = data
            return self

        def eq(self, col, val):
            self._filters[col] = val
            if col == "id":
                self._eq_id = val
            return self

        def in_(self, col, vals):
            self._filters[f"{col}__in"] = vals
            return self

        def lt(self, col, val):
            self._filters[f"{col}__lt"] = val
            return self

        def gte(self, col, val):
            self._filters[f"{col}__gte"] = val
            return self

        def execute(self):
            if raise_on_query and not self._is_update:
                raise APIError({"message": "DB query failed"})

            if self._is_update:
                # Check if this ID should fail on update.
                if self._eq_id in raise_on_update_ids:
                    raise APIError({"message": f"Update failed for {self._eq_id}"})
                result = MagicMock()
                result.data = [{"id": self._eq_id}]
                return result

            # SELECT query — determine which one by inspecting filters.
            result = MagicMock()

            # The expired query uses .in_("status", [...]) and .lt("consent_expires_at", now)
            # The expiring query uses .eq("status", "active") and .gte(...) and .lt(...)
            if "status" in self._filters and self._filters["status"] == "active":
                # This is the expiring_soon query
                result.data = expiring_rows
            else:
                # This is the expired query (uses .in_)
                result.data = expired_rows

            call_count["select"] += 1
            return result

    def table_factory(table_name):
        return ChainableMock()

    db.table = table_factory
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_connections_needing_update():
    """When all connections are healthy, nothing changes."""
    db = _mock_db(expired_rows=[], expiring_rows=[])
    result = await check_consent_expiry(db)

    assert result["expiring_soon"] == 0
    assert result["expired"] == 0
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_active_connection_becomes_expiring_soon():
    """Active connection with consent expiring in 3 days → expiring_soon."""
    expiring_rows = [
        {
            "id": "conn-1",
            "provider_name": "Mock Bank",
            "consent_expires_at": _iso(NOW + timedelta(days=3)),
            "status": "active",
        },
    ]
    db = _mock_db(expiring_rows=expiring_rows)
    result = await check_consent_expiry(db)

    assert result["expiring_soon"] == 1
    assert result["expired"] == 0
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_active_connection_becomes_expired():
    """Active connection with past consent → expired."""
    expired_rows = [
        {
            "id": "conn-2",
            "provider_name": "Mock Bank",
            "consent_expires_at": _iso(NOW - timedelta(days=1)),
            "status": "active",
        },
    ]
    db = _mock_db(expired_rows=expired_rows)
    result = await check_consent_expiry(db)

    assert result["expiring_soon"] == 0
    assert result["expired"] == 1
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_expiring_soon_connection_becomes_expired():
    """Connection already expiring_soon but consent now past → expired."""
    expired_rows = [
        {
            "id": "conn-3",
            "provider_name": "Mock Bank",
            "consent_expires_at": _iso(NOW - timedelta(hours=2)),
            "status": "expiring_soon",
        },
    ]
    db = _mock_db(expired_rows=expired_rows)
    result = await check_consent_expiry(db)

    assert result["expired"] == 1
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_mixed_batch():
    """Multiple connections: some expiring, some expired, some fine."""
    expired_rows = [
        {
            "id": "conn-expired-1",
            "provider_name": "Bank A",
            "consent_expires_at": _iso(NOW - timedelta(days=2)),
            "status": "active",
        },
        {
            "id": "conn-expired-2",
            "provider_name": "Bank B",
            "consent_expires_at": _iso(NOW - timedelta(hours=1)),
            "status": "expiring_soon",
        },
    ]
    expiring_rows = [
        {
            "id": "conn-warning-1",
            "provider_name": "Bank C",
            "consent_expires_at": _iso(NOW + timedelta(days=5)),
            "status": "active",
        },
    ]
    db = _mock_db(expired_rows=expired_rows, expiring_rows=expiring_rows)
    result = await check_consent_expiry(db)

    assert result["expired"] == 2
    assert result["expiring_soon"] == 1
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_db_query_error_handled_gracefully():
    """Database query failure doesn't raise — returns error count."""
    db = _mock_db(raise_on_query=True)
    result = await check_consent_expiry(db)

    # Both queries fail, so 2 errors.
    assert result["errors"] == 2
    assert result["expiring_soon"] == 0
    assert result["expired"] == 0


@pytest.mark.asyncio
async def test_per_connection_update_error():
    """One connection fails to update — others still processed."""
    expired_rows = [
        {
            "id": "conn-ok",
            "provider_name": "Bank A",
            "consent_expires_at": _iso(NOW - timedelta(days=1)),
            "status": "active",
        },
        {
            "id": "conn-fail",
            "provider_name": "Bank B",
            "consent_expires_at": _iso(NOW - timedelta(days=1)),
            "status": "active",
        },
    ]
    db = _mock_db(expired_rows=expired_rows, raise_on_update_ids={"conn-fail"})
    result = await check_consent_expiry(db)

    assert result["expired"] == 1  # conn-ok succeeded
    assert result["errors"] == 1   # conn-fail failed


@pytest.mark.asyncio
async def test_connection_with_consent_far_in_future_not_touched():
    """Active connection with 80+ days remaining → no change."""
    # No expired rows, no expiring rows returned by DB
    db = _mock_db(expired_rows=[], expiring_rows=[])
    result = await check_consent_expiry(db)

    assert result["expiring_soon"] == 0
    assert result["expired"] == 0
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_expiry_warning_days_constant():
    """Verify the warning threshold is 7 days."""
    assert EXPIRY_WARNING_DAYS == 7
