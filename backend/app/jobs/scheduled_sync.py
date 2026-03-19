"""
Scheduled sync job — runs every 4 hours via APScheduler.

Iterates over all active bank connections and triggers a sync
for each one. See ARCH.md §5.2 for sync frequency details.

Sprint 3: Full implementation.
"""
