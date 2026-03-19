-- =============================================================================
-- Supabase Schema: UK Personal Finance Aggregator
-- =============================================================================
-- Run this file in the Supabase SQL Editor to create all tables, indexes,
-- and Row-Level Security policies.
--
-- This script is IDEMPOTENT — safe to re-run without errors.
--
-- Prerequisites: Supabase project with auth.users table (created automatically).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. bank_connections
-- -----------------------------------------------------------------------------
-- Represents a user's authorised link to a banking institution via TrueLayer.
-- Access and refresh tokens are stored encrypted (application-level Fernet).

CREATE TABLE IF NOT EXISTS public.bank_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider_id         TEXT NOT NULL,
    provider_name       TEXT NOT NULL,
    access_token        TEXT NOT NULL,
    refresh_token       TEXT NOT NULL,
    token_expires_at    TIMESTAMPTZ NOT NULL,
    consent_created_at  TIMESTAMPTZ NOT NULL,
    consent_expires_at  TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expiring_soon', 'expired', 'revoked', 'error')),
    last_synced_at      TIMESTAMPTZ,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bank_connections_user_id
    ON public.bank_connections(user_id);

CREATE INDEX IF NOT EXISTS idx_bank_connections_status
    ON public.bank_connections(status);

CREATE INDEX IF NOT EXISTS idx_bank_connections_consent_expires
    ON public.bank_connections(consent_expires_at);

COMMENT ON TABLE public.bank_connections IS
    'Stores TrueLayer OAuth connections per user. Tokens are Fernet-encrypted at the application layer.';
COMMENT ON COLUMN public.bank_connections.access_token IS
    'Fernet-encrypted TrueLayer access token. Never stored in plaintext.';
COMMENT ON COLUMN public.bank_connections.refresh_token IS
    'Fernet-encrypted TrueLayer refresh token. Never stored in plaintext.';
COMMENT ON COLUMN public.bank_connections.consent_expires_at IS
    'consent_created_at + 90 days. UK Open Banking AIS consent window.';


-- -----------------------------------------------------------------------------
-- 2. accounts
-- -----------------------------------------------------------------------------
-- Individual bank accounts (current, savings, credit card) under a connection.

CREATE TABLE IF NOT EXISTS public.accounts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    bank_connection_id      UUID NOT NULL REFERENCES public.bank_connections(id) ON DELETE CASCADE,
    truelayer_account_id    TEXT NOT NULL,
    account_type            TEXT NOT NULL
                            CHECK (account_type IN ('current', 'savings', 'credit_card')),
    display_name            TEXT NOT NULL,
    currency                TEXT NOT NULL DEFAULT 'GBP',
    current_balance         NUMERIC(12,2),
    available_balance       NUMERIC(12,2),
    balance_updated_at      TIMESTAMPTZ,
    is_included_in_net_worth BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(bank_connection_id, truelayer_account_id)
);

CREATE INDEX IF NOT EXISTS idx_accounts_user_id
    ON public.accounts(user_id);

CREATE INDEX IF NOT EXISTS idx_accounts_bank_connection_id
    ON public.accounts(bank_connection_id);


-- -----------------------------------------------------------------------------
-- 3. transactions
-- -----------------------------------------------------------------------------
-- Individual transaction records. Deduplicated on (account_id, truelayer_transaction_id).

CREATE TABLE IF NOT EXISTS public.transactions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id                  UUID NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    truelayer_transaction_id    TEXT NOT NULL,
    timestamp                   TIMESTAMPTZ NOT NULL,
    description                 TEXT NOT NULL,
    amount                      NUMERIC(12,2) NOT NULL,
    currency                    TEXT NOT NULL DEFAULT 'GBP',
    transaction_type            TEXT,
    merchant_name               TEXT,
    auto_category               TEXT,
    user_category               TEXT,
    running_balance             NUMERIC(12,2),
    metadata                    JSONB DEFAULT '{}',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(account_id, truelayer_transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_id
    ON public.transactions(user_id);

CREATE INDEX IF NOT EXISTS idx_transactions_account_id
    ON public.transactions(account_id);

CREATE INDEX IF NOT EXISTS idx_transactions_timestamp
    ON public.transactions(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_transactions_category
    ON public.transactions(COALESCE(user_category, auto_category));

COMMENT ON COLUMN public.transactions.amount IS
    'Negative = debit/spend, Positive = credit/income.';
COMMENT ON COLUMN public.transactions.user_category IS
    'Manual category override by user. NULL means auto_category is used. Preserved across syncs.';


-- -----------------------------------------------------------------------------
-- 4. balance_history
-- -----------------------------------------------------------------------------
-- Daily balance snapshots per account for net worth trend tracking.

CREATE TABLE IF NOT EXISTS public.balance_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id  UUID NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    balance     NUMERIC(12,2) NOT NULL,
    recorded_at DATE NOT NULL DEFAULT CURRENT_DATE,

    UNIQUE(account_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS idx_balance_history_user_id
    ON public.balance_history(user_id);

CREATE INDEX IF NOT EXISTS idx_balance_history_account_recorded
    ON public.balance_history(account_id, recorded_at DESC);


-- =============================================================================
-- 5. updated_at trigger
-- =============================================================================
-- Automatically set updated_at on row modification for tables that have it.

CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_updated_at_bank_connections ON public.bank_connections;
CREATE TRIGGER set_updated_at_bank_connections
    BEFORE UPDATE ON public.bank_connections
    FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS set_updated_at_accounts ON public.accounts;
CREATE TRIGGER set_updated_at_accounts
    BEFORE UPDATE ON public.accounts
    FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();


-- =============================================================================
-- 6. Row-Level Security (RLS)
-- =============================================================================
-- Every table is locked down so users can only access rows where
-- user_id = auth.uid(). The FastAPI backend uses a Supabase secret key
-- (sb_secret_..., which assumes the service_role Postgres role and
-- bypasses RLS) for sync operations.

ALTER TABLE public.bank_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.balance_history ENABLE ROW LEVEL SECURITY;

-- ── bank_connections (server-only access) ────────────────────────────────
-- This table holds encrypted TrueLayer tokens. Even though tokens are
-- Fernet-encrypted, we don't want ciphertext leaking to the client, nor
-- do we want clients mutating connection state directly.
--
-- Revoke all grants from anon and authenticated so PostgREST cannot
-- reach this table. The FastAPI backend uses the secret key (service_role),
-- which bypasses both RLS and these grants.

REVOKE ALL ON public.bank_connections FROM anon, authenticated;

-- No RLS policies needed — the REVOKE above blocks all client access.
-- The service_role used by FastAPI bypasses RLS entirely.

-- accounts
DROP POLICY IF EXISTS "Users can select their own accounts" ON public.accounts;
CREATE POLICY "Users can select their own accounts"
    ON public.accounts FOR SELECT
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can insert their own accounts" ON public.accounts;
CREATE POLICY "Users can insert their own accounts"
    ON public.accounts FOR INSERT
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can update their own accounts" ON public.accounts;
CREATE POLICY "Users can update their own accounts"
    ON public.accounts FOR UPDATE
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can delete their own accounts" ON public.accounts;
CREATE POLICY "Users can delete their own accounts"
    ON public.accounts FOR DELETE
    USING (user_id = auth.uid());

-- transactions
DROP POLICY IF EXISTS "Users can select their own transactions" ON public.transactions;
CREATE POLICY "Users can select their own transactions"
    ON public.transactions FOR SELECT
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can insert their own transactions" ON public.transactions;
CREATE POLICY "Users can insert their own transactions"
    ON public.transactions FOR INSERT
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can update their own transactions" ON public.transactions;
CREATE POLICY "Users can update their own transactions"
    ON public.transactions FOR UPDATE
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can delete their own transactions" ON public.transactions;
CREATE POLICY "Users can delete their own transactions"
    ON public.transactions FOR DELETE
    USING (user_id = auth.uid());

-- balance_history
DROP POLICY IF EXISTS "Users can select their own balance_history" ON public.balance_history;
CREATE POLICY "Users can select their own balance_history"
    ON public.balance_history FOR SELECT
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can insert their own balance_history" ON public.balance_history;
CREATE POLICY "Users can insert their own balance_history"
    ON public.balance_history FOR INSERT
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can update their own balance_history" ON public.balance_history;
CREATE POLICY "Users can update their own balance_history"
    ON public.balance_history FOR UPDATE
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "Users can delete their own balance_history" ON public.balance_history;
CREATE POLICY "Users can delete their own balance_history"
    ON public.balance_history FOR DELETE
    USING (user_id = auth.uid());
