"""
Consent expiry checker — runs daily at 09:00 UTC.

Scans bank_connections for approaching/past consent expiry dates
and updates statuses accordingly. See ARCH.md §5.6 for the algorithm.

Status transitions:
  active → expiring_soon   (consent expires within 7 days)
  active/expiring_soon → expired   (consent has expired)

Sprint 5: Full implementation.
"""

import logging
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError
from supabase import Client

logger = logging.getLogger(__name__)

# How many days before expiry to set "expiring_soon".
EXPIRY_WARNING_DAYS = 7


async def check_consent_expiry(db: Client) -> dict:
    """
    Daily job: detect and update connections with expiring/expired consent.

    Algorithm (per ARCH.md §5.6):
      1. Find all active connections whose consent expires within 7 days
         → set status = 'expiring_soon'
      2. Find all active/expiring_soon connections whose consent has expired
         → set status = 'expired'

    Returns a summary dict:
        {"expiring_soon": N, "expired": M, "errors": E}
    """
    now = datetime.now(timezone.utc)
    warning_threshold = now + timedelta(days=EXPIRY_WARNING_DAYS)

    expiring_soon_count = 0
    expired_count = 0
    error_count = 0

    logger.info("Consent checker starting at %s", now.isoformat())

    # ── Step 1: Mark expired connections ──────────────────────────────────
    # Find connections that are active or expiring_soon but consent has passed.
    # Process expired FIRST so that a connection that crossed from
    # expiring_soon → expired in the same run gets the correct final state.
    try:
        expired_result = (
            db.table("bank_connections")
            .select("id, provider_name, consent_expires_at, status")
            .in_("status", ["active", "expiring_soon"])
            .lt("consent_expires_at", now.isoformat())
            .execute()
        )

        for conn in expired_result.data:
            try:
                db.table("bank_connections").update({
                    "status": "expired",
                    "error_message": "Consent expired — reconnect required",
                }).eq("id", conn["id"]).execute()

                expired_count += 1
                logger.info(
                    "Consent expired: connection %s (%s), was %s, "
                    "consent_expires_at=%s",
                    conn["id"],
                    conn.get("provider_name", "unknown"),
                    conn.get("status"),
                    conn.get("consent_expires_at"),
                )
            except APIError as e:
                error_count += 1
                logger.error(
                    "Failed to update expired connection %s: %s",
                    conn["id"], e,
                )
    except APIError as e:
        error_count += 1
        logger.error("Failed to query expired connections: %s", e)

    # ── Step 2: Mark expiring_soon connections ────────────────────────────
    # Find active connections whose consent expires within the warning window
    # but hasn't expired yet.
    try:
        expiring_result = (
            db.table("bank_connections")
            .select("id, provider_name, consent_expires_at, status")
            .eq("status", "active")
            .gte("consent_expires_at", now.isoformat())
            .lt("consent_expires_at", warning_threshold.isoformat())
            .execute()
        )

        for conn in expiring_result.data:
            try:
                db.table("bank_connections").update({
                    "status": "expiring_soon",
                    "error_message": None,
                }).eq("id", conn["id"]).execute()

                expiring_soon_count += 1
                logger.info(
                    "Consent expiring soon: connection %s (%s), "
                    "consent_expires_at=%s",
                    conn["id"],
                    conn.get("provider_name", "unknown"),
                    conn.get("consent_expires_at"),
                )
            except APIError as e:
                error_count += 1
                logger.error(
                    "Failed to update expiring_soon connection %s: %s",
                    conn["id"], e,
                )
    except APIError as e:
        error_count += 1
        logger.error("Failed to query expiring connections: %s", e)

    summary = {
        "expiring_soon": expiring_soon_count,
        "expired": expired_count,
        "errors": error_count,
    }

    logger.info(
        "Consent checker complete: %d expiring_soon, %d expired, %d errors",
        expiring_soon_count, expired_count, error_count,
    )

    return summary
