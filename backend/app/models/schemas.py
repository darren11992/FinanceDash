"""
Pydantic schemas for API request/response validation.

Organised by domain area. Each endpoint in ARCH.md §7 has a
corresponding response schema here. Request bodies only exist
where the client sends structured data (e.g., category override).

Naming convention:
  - *Out   = response schema (returned to client)
  - *In    = request body schema (received from client)
  - *Base  = shared fields between In/Out
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Auth
# =============================================================================


class UserOut(BaseModel):
    """Response for GET /api/v1/me."""

    user_id: str


# =============================================================================
# Bank Connections (Sprint 2)
# =============================================================================


class ConnectionOut(BaseModel):
    """A single bank connection returned to the client.

    Sensitive fields (tokens) are never exposed — only the metadata
    needed by the UI to display connection status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: str
    provider_name: str
    status: str = Field(
        description="One of: active, expiring_soon, expired, revoked, error"
    )
    last_synced_at: datetime | None = None
    consent_created_at: datetime
    consent_expires_at: datetime
    error_message: str | None = None
    created_at: datetime


class ConnectionInitiateOut(BaseModel):
    """Response for POST /api/v1/connections/initiate.

    Returns the TrueLayer auth URL for the client to open in a browser.
    """

    auth_url: str


class ConnectionCallbackIn(BaseModel):
    """Request body for POST /api/v1/connections/callback.

    The Flutter app extracts the auth code from the deep-link redirect
    and sends it here.
    """

    code: str = Field(
        max_length=2048,
        description="OAuth authorization code from TrueLayer redirect",
    )


class ConnectionCallbackOut(BaseModel):
    """Response for POST /api/v1/connections/callback."""

    connection_id: UUID
    provider_name: str
    status: str


class ReconnectOut(BaseModel):
    """Response for POST /api/v1/connections/{id}/reconnect.

    Two possible outcomes:
      - action = "no_action_needed": consent extended silently, tokens refreshed.
        auth_url is None.
      - action = "authentication_needed": user must visit auth_url to re-consent
        at their bank. The backend returns the auth URL for the client to open.
    """

    action: str = Field(
        description="One of: no_action_needed, authentication_needed"
    )
    auth_url: str | None = Field(
        None,
        description="Bank auth URL (only present when action = authentication_needed)",
    )
    message: str = Field(
        description="Human-readable explanation of the outcome"
    )


# =============================================================================
# Accounts (Sprint 3-4)
# =============================================================================


class AccountOut(BaseModel):
    """A single bank account returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bank_connection_id: UUID
    truelayer_account_id: str
    account_type: str = Field(
        description="One of: current, savings, credit_card"
    )
    display_name: str
    currency: str = "GBP"
    current_balance: Decimal | None = None
    available_balance: Decimal | None = None
    balance_updated_at: datetime | None = None
    is_included_in_net_worth: bool = True


# =============================================================================
# Transactions (Sprint 3)
# =============================================================================


class TransactionOut(BaseModel):
    """A single transaction returned to the client.

    The `category` field is the effective category: user_category if
    the user overrode it, otherwise auto_category.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    timestamp: datetime
    description: str
    amount: Decimal = Field(description="Negative = debit/spend, Positive = credit/income")
    currency: str = "GBP"
    transaction_type: str | None = None
    merchant_name: str | None = None
    category: str | None = Field(
        None,
        description="Effective category: COALESCE(user_category, auto_category)",
    )
    running_balance: Decimal | None = None


class TransactionListOut(BaseModel):
    """Paginated response for GET /api/v1/transactions."""

    transactions: list[TransactionOut]
    total: int = Field(description="Total matching transactions (before pagination)")
    page: int
    page_size: int
    has_more: bool


class CategoryUpdateIn(BaseModel):
    """Request body for PATCH /api/v1/transactions/{id}/category."""

    category: str | None = Field(
        None,
        max_length=100,
        description="New category name, or null to revert to auto-categorisation",
    )


class CategoryUpdateOut(BaseModel):
    """Response for PATCH /api/v1/transactions/{id}/category."""

    transaction_id: UUID
    category: str | None
    is_user_override: bool


class RecategoriseOut(BaseModel):
    """Response for POST /api/v1/transactions/recategorise."""

    total_reviewed: int
    updated: int
    skipped_user_override: int


# =============================================================================
# Net Worth (Sprint 4)
# =============================================================================


class NetWorthAccountBreakdown(BaseModel):
    """Per-account contribution to net worth."""

    account_id: UUID
    display_name: str
    account_type: str
    current_balance: Decimal | None = None
    currency: str = "GBP"
    is_liability: bool = Field(
        description="True for credit_card accounts (balance subtracted from net worth)"
    )


class NetWorthOut(BaseModel):
    """Response for GET /api/v1/net-worth."""

    total_net_worth: Decimal
    currency: str = "GBP"
    accounts: list[NetWorthAccountBreakdown]
    last_updated: datetime | None = Field(
        None,
        description="Most recent balance_updated_at across all included accounts",
    )


class NetWorthHistoryPoint(BaseModel):
    """A single data point in the net worth trend."""

    date: date
    net_worth: Decimal
    is_estimated: bool = Field(
        False,
        description=(
            "True if any contributing balance was reconstructed from "
            "transactions rather than from a live balance snapshot or "
            "running_balance."
        ),
    )


class NetWorthHistoryOut(BaseModel):
    """Response for GET /api/v1/net-worth/history."""

    period: str = Field(description="Requested period: 7d, 30d, or 90d")
    data_points: list[NetWorthHistoryPoint]
    currency: str = "GBP"


# =============================================================================
# Sync (Sprint 3)
# =============================================================================


class SyncConnectionResult(BaseModel):
    """Per-connection result from a sync run."""

    connection_id: str
    status: str = Field(description="ok, skipped, or error")
    detail: str | None = None
    accounts_synced: int = 0
    transactions_synced: int = 0


class SyncTriggerOut(BaseModel):
    """Response for POST /api/v1/sync."""

    message: str
    connections_queued: int
    results: list[SyncConnectionResult] = Field(
        default_factory=list,
        description="Per-connection sync results (debug info)",
    )


class ConnectionSyncStatus(BaseModel):
    """Sync status for a single connection."""

    connection_id: UUID
    provider_name: str
    status: str
    last_synced_at: datetime | None = None
    error_message: str | None = None


class SyncStatusOut(BaseModel):
    """Response for GET /api/v1/sync/status."""

    connections: list[ConnectionSyncStatus]


# =============================================================================
# Shared / Generic
# =============================================================================


class ErrorOut(BaseModel):
    """Standard error response body."""

    detail: str


class HealthOut(BaseModel):
    """Response for GET /health."""

    status: str
    version: str
    environment: str
    truelayer_env: str
    timestamp: str
