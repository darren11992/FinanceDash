# Technical Architecture

**Project:** UK Personal Finance Aggregator
**Version:** 0.1.0 (Planning Phase)
**Last Updated:** 2026-03-17

---

## 1. System Overview

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────────┐
│             │       │                  │       │                 │
│   Flutter   │◄─────►│  FastAPI Backend  │◄─────►│    Supabase     │
│  Mobile App │ HTTPS │  (Python 3.12+)  │  SQL  │   (PostgreSQL)  │
│             │       │                  │       │                 │
└─────────────┘       └────────┬─────────┘       └─────────────────┘
                               │
                               │ HTTPS
                               ▼
                      ┌──────────────────┐
                      │                  │
                      │    TrueLayer     │
                      │    Data API      │
                      │                  │
                      └──────────────────┘
```

**Component responsibilities:**

| Component | Role |
|---|---|
| Flutter App | UI, local caching, Supabase Auth SDK, deep-link handling for OAuth callbacks |
| FastAPI Backend | Business logic, TrueLayer integration, sync orchestration, token management |
| Supabase | PostgreSQL database, user authentication (email/password + magic link), Row-Level Security |
| TrueLayer | Open Banking data provider — account info, balances, transactions |

---

## 2. Authentication Flow

```
User                    Flutter App              Supabase Auth           FastAPI
 │                          │                        │                     │
 │── Sign up / Log in ─────►│                        │                     │
 │                          │── Create user ────────►│                     │
 │                          │◄── JWT + refresh ──────│                     │
 │                          │                        │                     │
 │                          │── API call + JWT ──────────────────────────►│
 │                          │                        │                     │
 │                          │                  │── Verify JWT ───────────►│
 │                          │                        │◄── Valid ──────────│
 │                          │◄── Response ───────────────────────────────│
```

- Supabase handles user registration and session management.
- The Flutter app stores the Supabase JWT and sends it in the `Authorization` header on every request to FastAPI.
- FastAPI validates the JWT using the public key from Supabase's JWKS endpoint (asymmetric ES256 signing key, no shared secret stored in the backend).
- The Supabase `auth.users.id` (UUID) is the canonical `user_id` used across all tables.

---

## 3. Data Schema

All tables live in the Supabase PostgreSQL instance. UUIDs are used for all primary keys. Timestamps are stored in UTC.

### 3.1 `bank_connections`

Represents a user's authorised link to a single banking institution via TrueLayer.

```sql
CREATE TABLE bank_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider_id     TEXT NOT NULL,               -- TrueLayer provider identifier (e.g., "ob-monzo")
    provider_name   TEXT NOT NULL,               -- Human-readable name (e.g., "Monzo")
    access_token    TEXT NOT NULL,               -- Encrypted TrueLayer access token
    refresh_token   TEXT NOT NULL,               -- Encrypted TrueLayer refresh token
    token_expires_at TIMESTAMPTZ NOT NULL,       -- When the access token expires
    consent_created_at TIMESTAMPTZ NOT NULL,     -- When the 90-day consent window started
    consent_expires_at TIMESTAMPTZ NOT NULL,     -- consent_created_at + 90 days
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'expiring_soon', 'expired', 'revoked', 'error')),
    last_synced_at  TIMESTAMPTZ,                 -- Last successful data sync
    error_message   TEXT,                        -- Last error encountered during sync
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bank_connections_user_id ON bank_connections(user_id);
CREATE INDEX idx_bank_connections_status ON bank_connections(status);
CREATE INDEX idx_bank_connections_consent_expires ON bank_connections(consent_expires_at);
```

### 3.2 `accounts`

Individual bank accounts (current, savings, credit card) belonging to a connection.

```sql
CREATE TABLE accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_connection_id  UUID NOT NULL REFERENCES bank_connections(id) ON DELETE CASCADE,
    truelayer_account_id TEXT NOT NULL,           -- TrueLayer's identifier for this account
    account_type        TEXT NOT NULL
                        CHECK (account_type IN ('current', 'savings', 'credit_card')),
    display_name        TEXT NOT NULL,            -- e.g., "Monzo Current Account"
    currency            TEXT NOT NULL DEFAULT 'GBP',
    current_balance     NUMERIC(12,2),            -- Latest known balance
    available_balance   NUMERIC(12,2),            -- Available (may differ from current)
    balance_updated_at  TIMESTAMPTZ,              -- When balance was last fetched
    is_included_in_net_worth BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(bank_connection_id, truelayer_account_id)
);

CREATE INDEX idx_accounts_user_id ON accounts(user_id);
CREATE INDEX idx_accounts_bank_connection_id ON accounts(bank_connection_id);
```

### 3.3 `transactions`

Individual transaction records. The deduplication key is the combination of `account_id` + `truelayer_transaction_id`.

```sql
CREATE TABLE transactions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id              UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    truelayer_transaction_id TEXT NOT NULL,       -- TrueLayer's unique transaction ID
    timestamp               TIMESTAMPTZ NOT NULL, -- When the transaction occurred
    description             TEXT NOT NULL,         -- Raw description from the bank
    amount                  NUMERIC(12,2) NOT NULL,-- Negative = debit, positive = credit
    currency                TEXT NOT NULL DEFAULT 'GBP',
    transaction_type        TEXT,                  -- e.g., "DEBIT", "CREDIT", "DIRECT_DEBIT"
    merchant_name           TEXT,                  -- Cleaned merchant name (if available)
    auto_category           TEXT,                  -- Category from TrueLayer classification
    user_category           TEXT,                  -- User override (NULL if not overridden)
    running_balance         NUMERIC(12,2),         -- Running balance after this transaction (if provided)
    metadata                JSONB DEFAULT '{}',    -- Flexible store for extra TrueLayer fields
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(account_id, truelayer_transaction_id)
);

CREATE INDEX idx_transactions_user_id ON transactions(user_id);
CREATE INDEX idx_transactions_account_id ON transactions(account_id);
CREATE INDEX idx_transactions_timestamp ON transactions(timestamp DESC);
CREATE INDEX idx_transactions_category ON transactions(
    COALESCE(user_category, auto_category)
);
```

### 3.4 `balance_history`

Daily snapshots for net worth trend tracking.

```sql
CREATE TABLE balance_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    balance     NUMERIC(12,2) NOT NULL,
    recorded_at DATE NOT NULL DEFAULT CURRENT_DATE,

    UNIQUE(account_id, recorded_at)
);

CREATE INDEX idx_balance_history_user_id ON balance_history(user_id);
CREATE INDEX idx_balance_history_account_recorded ON balance_history(account_id, recorded_at DESC);
```

### 3.5 Entity-Relationship Diagram

```
auth.users (Supabase)
    │
    │ 1:N
    ▼
bank_connections
    │
    │ 1:N
    ▼
accounts
    │
    ├── 1:N ──► transactions
    │
    └── 1:N ──► balance_history
```

---

## 4. Security Plan

### 4.1 Token Encryption at Rest

TrueLayer `access_token` and `refresh_token` values are sensitive credentials. They are **never stored in plaintext**.

**Strategy: Application-level encryption using Fernet (symmetric encryption)**

```
┌──────────────┐     encrypt()      ┌──────────────────┐
│  TrueLayer   │ ──────────────────►│  Supabase DB     │
│  plaintext   │                    │  (ciphertext)    │
│  token       │ ◄──────────────────│                  │
└──────────────┘     decrypt()      └──────────────────┘
```

- Encryption key stored as an environment variable (`TRUELAYER_TOKEN_ENCRYPTION_KEY`) on the FastAPI backend, **never** in the database or source code.
- The `cryptography` Python library's `Fernet` implementation provides AES-128-CBC with HMAC authentication.
- Tokens are encrypted before INSERT/UPDATE and decrypted only in-memory when making TrueLayer API calls.
- The Flutter app never sees or handles TrueLayer tokens directly.

### 4.2 Row-Level Security (RLS)

Every table with a `user_id` column has RLS enabled. Policies ensure a user can only read/write their own data.

```sql
-- Enable RLS on all tables
ALTER TABLE bank_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE balance_history ENABLE ROW LEVEL SECURITY;

-- Policy pattern (applied to each table):
CREATE POLICY "Users can only access their own data"
    ON bank_connections
    FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can only access their own data"
    ON accounts
    FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can only access their own data"
    ON transactions
    FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can only access their own data"
    ON balance_history
    FOR ALL
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());
```

**Important:** The FastAPI backend connects to Supabase using a **secret** key (`sb_secret_...`, which assumes the `service_role` Postgres role and bypasses RLS) for sync operations that write data on behalf of users. Direct client connections from Flutter use the **publishable** key (`sb_publishable_...`, which assumes the `anon` Postgres role) and are subject to RLS. See the [Supabase API keys discussion](https://github.com/orgs/supabase/discussions/29260) for details on the new key format.

### 4.3 API Security

| Layer | Measure |
|---|---|
| Transport | All communications over TLS 1.2+ (HTTPS) |
| Authentication | Supabase JWT validated on every FastAPI request via JWKS public key (ES256) |
| Authorisation | Backend verifies `user_id` from JWT matches requested resource |
| Rate limiting | FastAPI middleware limits requests per user (e.g., 60/min) |
| Input validation | Pydantic models validate all request bodies; parameterised SQL prevents injection |
| CORS | FastAPI CORS middleware restricted to the app's domain/deep-link scheme |
| Secrets management | All secrets (Supabase keys, TrueLayer credentials, encryption key) via environment variables, never committed to source |

### 4.4 Data Retention & Deletion

- When a user deletes their account, `ON DELETE CASCADE` removes all related data.
- When a user disconnects a bank, the `bank_connection` and its child `accounts` and `transactions` are deleted.
- TrueLayer tokens are revoked via their API before deletion from the database.

---

## 5. Sync Engine

The sync engine is the core backend process that keeps financial data fresh. It runs as a scheduled background task within the FastAPI application.

### 5.1 Architecture

```
┌─────────────────────────────────────────────────────┐
│                  FastAPI Backend                     │
│                                                     │
│  ┌─────────────┐    ┌──────────────────────────┐   │
│  │  Scheduler   │───►│     Sync Orchestrator     │   │
│  │  (APScheduler│    │                          │   │
│  │   or cron)  │    │  1. Get active connections │   │
│  └─────────────┘    │  2. Refresh tokens if near │   │
│                      │     expiry                 │   │
│                      │  3. Fetch balances         │   │
│                      │  4. Fetch transactions     │   │
│                      │  5. Deduplicate & upsert   │   │
│                      │  6. Update sync timestamp  │   │
│                      └──────────┬───────────────┘   │
│                                 │                    │
└─────────────────────────────────┼────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ TrueLayer│ │ TrueLayer│ │ TrueLayer│
              │ (Bank A) │ │ (Bank B) │ │ (Bank C) │
              └──────────┘ └──────────┘ └──────────┘
```

### 5.2 Sync Frequency

| Trigger | Frequency |
|---|---|
| Scheduled sync | Every 4 hours for all `active` connections |
| User-initiated refresh | On-demand when user pulls-to-refresh in the app |
| Post-connection sync | Immediately after a new bank connection is established |

### 5.3 Sync Process (Per Connection)

```
START sync for bank_connection.id

1. CHECK consent_expires_at
   ├── If expired → set status = 'expired', SKIP, notify user
   ├── If < 7 days → set status = 'expiring_soon', continue
   └── If OK → continue

2. CHECK token_expires_at
   ├── If expired or < 5 min remaining → REFRESH token via TrueLayer
   │   ├── Success → update access_token, refresh_token, token_expires_at
   │   └── Failure → set status = 'error', log error, SKIP
   └── If OK → continue

3. FETCH BALANCES
   ├── GET /data/v1/accounts from TrueLayer
   ├── For each account:
   │   ├── UPSERT account record (match on truelayer_account_id)
   │   ├── Update current_balance, available_balance, balance_updated_at
   │   └── INSERT into balance_history (ON CONFLICT DO UPDATE for today's date)
   └── Handle new/removed accounts

4. FETCH TRANSACTIONS
   ├── For each account:
   │   ├── Determine date range:
   │   │   ├── First sync → from = 12 months ago
   │   │   └── Subsequent → from = last_synced_at - 2 day overlap
   │   ├── GET /data/v1/accounts/{id}/transactions?from=...&to=...
   │   ├── DEDUPLICATE (see §5.4)
   │   └── UPSERT transactions
   └── Continue to next account

5. UPDATE bank_connection
   ├── last_synced_at = now()
   ├── status = 'active' (clear any previous error)
   └── error_message = NULL

END
```

### 5.4 Transaction Deduplication Strategy

Duplicate transactions are the most common failure mode in finance aggregators. Our strategy uses a **database-level unique constraint** combined with **upsert semantics**.

**Unique Key:** `(account_id, truelayer_transaction_id)`

```sql
-- The UNIQUE constraint on the transactions table:
UNIQUE(account_id, truelayer_transaction_id)

-- Upsert pattern used by the sync engine:
INSERT INTO transactions (
    user_id, account_id, truelayer_transaction_id,
    timestamp, description, amount, currency,
    transaction_type, merchant_name, auto_category,
    running_balance, metadata
) VALUES (...)
ON CONFLICT (account_id, truelayer_transaction_id)
DO UPDATE SET
    -- Update fields that might change (e.g., pending → settled)
    amount          = EXCLUDED.amount,
    description     = EXCLUDED.description,
    transaction_type = EXCLUDED.transaction_type,
    merchant_name   = EXCLUDED.merchant_name,
    auto_category   = EXCLUDED.auto_category,
    running_balance = EXCLUDED.running_balance,
    metadata        = EXCLUDED.metadata
    -- NOTE: user_category is NOT in the update set,
    -- preserving manual overrides
;
```

**Why this works:**
- TrueLayer provides a stable `transaction_id` for each transaction.
- The unique constraint prevents duplicate rows at the database level regardless of application bugs.
- `ON CONFLICT DO UPDATE` handles the case where a pending transaction settles (amount or description may change).
- `user_category` is excluded from the update, so manual categorisation overrides are never overwritten.
- The 2-day overlap window on incremental syncs ensures transactions that appeared after the last sync timestamp are caught, while the unique constraint prevents those already-stored transactions from duplicating.

### 5.5 Error Handling & Resilience

| Scenario | Handling |
|---|---|
| TrueLayer API timeout | Retry up to 3 times with exponential backoff (1s, 4s, 16s) |
| TrueLayer rate limit (429) | Respect `Retry-After` header; queue for later |
| Token refresh failure | Mark connection as `error`; do not delete tokens (may be transient) |
| Partial sync failure | Per-account granularity: if one account fails, continue with others |
| Database write failure | Wrap each connection's sync in a transaction; rollback on failure |
| Scheduler overlap | Use a distributed lock (or `max_instances=1` in APScheduler) to prevent concurrent syncs of the same connection |

### 5.6 Consent Expiry Background Job

A separate lightweight job runs daily to manage consent lifecycle:

```
DAILY at 09:00 UTC:

1. SELECT all bank_connections WHERE status = 'active'
   AND consent_expires_at < now() + INTERVAL '7 days'
   → Set status = 'expiring_soon'
   → Queue push notification: "Your {provider_name} connection expires in X days"

2. SELECT all bank_connections WHERE status IN ('active', 'expiring_soon')
   AND consent_expires_at < now()
   → Set status = 'expired'
   → Queue push notification: "Your {provider_name} connection has expired. Reconnect to keep your data up to date."
```

---

## 6. TrueLayer Integration Details

### 6.1 OAuth Flow (Bank Connection)

```
User            Flutter App           FastAPI              TrueLayer
 │                  │                    │                     │
 │── Tap "Add       │                    │                     │
 │   Bank" ────────►│                    │                     │
 │                  │── POST /connect ──►│                     │
 │                  │                    │── Build auth URL ──►│
 │                  │◄── auth_url ───────│                     │
 │                  │                    │                     │
 │◄── Open browser/│                    │                     │
 │    webview ──────│                    │                     │
 │                  │                    │                     │
 │── Select bank,   │                    │                     │
 │   grant consent ─────────────────────────────────────────►│
 │                  │                    │                     │
 │◄── Redirect to   │                    │                     │
 │    app deep link ◄────────────────────────── ?code=xxx ───│
 │                  │                    │                     │
 │                  │── POST /callback   │                     │
 │                  │   {code: xxx} ────►│                     │
 │                  │                    │── Exchange code ───►│
 │                  │                    │◄── access_token, ──│
 │                  │                    │    refresh_token    │
 │                  │                    │                     │
 │                  │                    │── Encrypt & store   │
 │                  │                    │   tokens in DB      │
 │                  │                    │                     │
 │                  │                    │── Trigger initial   │
 │                  │                    │   sync              │
 │                  │◄── 200 OK ────────│                     │
 │◄── Show accounts │                    │                     │
```

### 6.2 Key TrueLayer Endpoints Used

| Endpoint | Purpose |
|---|---|
| `POST /connect/token` | Exchange auth code for access/refresh tokens |
| `POST /connect/token` (grant_type=refresh_token) | Refresh an expired access token |
| `GET /data/v1/accounts` | List all accounts under a connection |
| `GET /data/v1/accounts/{id}/balance` | Get current balance for an account |
| `GET /data/v1/accounts/{id}/transactions` | Get transactions with date range filter |
| `GET /data/v1/cards` | List credit cards (separate endpoint) |
| `GET /data/v1/cards/{id}/balance` | Credit card balance |
| `GET /data/v1/cards/{id}/transactions` | Credit card transactions |

### 6.3 Environment Configuration

```
TRUELAYER_CLIENT_ID=...
TRUELAYER_CLIENT_SECRET=...
TRUELAYER_REDIRECT_URI=pennyapp://callback
TRUELAYER_AUTH_BASE_URL=https://auth.truelayer.com
TRUELAYER_DATA_BASE_URL=https://api.truelayer.com
TRUELAYER_ENV=sandbox  # "sandbox" or "live"
```

---

## 7. API Design (FastAPI Endpoints)

### 7.1 Auth-Related

| Method | Path | Description |
|---|---|---|
| — | — | Auth handled by Supabase client SDK directly; no FastAPI endpoints needed |

### 7.2 Bank Connections

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/connections/initiate` | Generate TrueLayer auth URL for the user |
| POST | `/api/v1/connections/callback` | Handle OAuth callback, store tokens, trigger sync |
| GET | `/api/v1/connections` | List user's bank connections with status |
| DELETE | `/api/v1/connections/{id}` | Disconnect a bank (revoke token + delete data) |
| POST | `/api/v1/connections/{id}/reconnect` | Initiate re-consent for an expiring/expired connection |

### 7.3 Accounts & Balances

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/accounts` | List all accounts across all connections |
| GET | `/api/v1/accounts/{id}` | Get single account details |
| GET | `/api/v1/net-worth` | Calculate and return total net worth + breakdown |
| GET | `/api/v1/net-worth/history` | Net worth trend over time (from balance_history) |

### 7.4 Transactions

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/transactions` | Paginated transaction list (filters: account, category, date range) |
| PATCH | `/api/v1/transactions/{id}/category` | Update user_category override |

### 7.5 Sync

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/sync` | Trigger manual sync for all user's active connections |
| GET | `/api/v1/sync/status` | Get last sync timestamps and any errors |

---

## 8. Project Structure

```
penny/
├── SPEC.md
├── ARCH.md
├── ROADMAP.md
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── config.py                # Settings via pydantic-settings
│   │   ├── dependencies.py          # Dependency injection (DB, auth)
│   │   ├── auth/
│   │   │   └── jwt.py               # Supabase JWT verification (JWKS / ES256)
│   │   ├── routers/
│   │   │   ├── connections.py
│   │   │   ├── accounts.py
│   │   │   ├── transactions.py
│   │   │   └── sync.py
│   │   ├── services/
│   │   │   ├── truelayer.py          # TrueLayer API client
│   │   │   ├── sync_engine.py        # Sync orchestration logic
│   │   │   ├── categorisation.py     # Category mapping logic
│   │   │   └── encryption.py         # Token encryption/decryption
│   │   ├── models/
│   │   │   ├── database.py           # SQLAlchemy/raw SQL models
│   │   │   └── schemas.py            # Pydantic request/response schemas
│   │   └── jobs/
│   │       ├── scheduled_sync.py     # Periodic sync job
│   │       └── consent_checker.py    # Daily consent expiry check
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── mobile/
│   └── penny/                        # Flutter project
│       ├── lib/
│       │   ├── main.dart
│       │   ├── config/
│       │   ├── models/
│       │   ├── services/
│       │   ├── providers/
│       │   └── screens/
│       ├── pubspec.yaml
│       └── ...
└── supabase/
    └── migrations/
        ├── 001_create_bank_connections.sql
        ├── 002_create_accounts.sql
        ├── 003_create_transactions.sql
        ├── 004_create_balance_history.sql
        └── 005_enable_rls.sql
```
