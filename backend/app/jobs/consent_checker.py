"""
Consent expiry checker — runs daily at 09:00 UTC.

Scans bank_connections for approaching/past consent expiry dates
and updates statuses + queues push notifications.
See ARCH.md §5.6 for the full algorithm.

Sprint 5: Full implementation.
"""
