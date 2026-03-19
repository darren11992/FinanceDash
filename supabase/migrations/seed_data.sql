-- =============================================================================
-- Seed Data for Development / Testing
-- =============================================================================
-- Run this AFTER supabase_schema.sql in the Supabase SQL Editor.
--
-- Prerequisites:
--   1. Schema migration has been applied (all 4 tables exist).
--   2. A test user exists in auth.users. Create one first via:
--        - Supabase Dashboard → Authentication → Add User
--        - Or sign up through the Flutter app
--      Then replace the UUID below with the actual user ID.
--
-- IMPORTANT: This script uses a placeholder user_id. You MUST replace it
-- with a real auth.users.id from your Supabase project.
-- =============================================================================


-- ── Step 0: Set the test user ID ─────────────────────────────────────────────
-- Replace this UUID with your actual test user's auth.users.id.
-- You can find it in Supabase Dashboard → Authentication → Users.
DO $$
DECLARE
    test_user_id UUID := '00000000-0000-0000-0000-000000000001';  -- REPLACE ME
    conn_monzo   UUID;
    conn_starling UUID;
    acct_monzo_current   UUID;
    acct_monzo_savings   UUID;
    acct_starling_current UUID;
    acct_starling_cc     UUID;
BEGIN

-- ── Step 1: bank_connections ─────────────────────────────────────────────────
-- Tokens are placeholder ciphertext. In real usage these would be Fernet-encrypted.
-- The sync engine will never try to decrypt these seed values.

INSERT INTO public.bank_connections (
    id, user_id, provider_id, provider_name,
    access_token, refresh_token,
    token_expires_at, consent_created_at, consent_expires_at,
    status, last_synced_at
) VALUES
(
    gen_random_uuid(), test_user_id,
    'ob-monzo', 'Monzo',
    'SEED_ENCRYPTED_ACCESS_TOKEN_MONZO',
    'SEED_ENCRYPTED_REFRESH_TOKEN_MONZO',
    now() + INTERVAL '1 hour',
    now() - INTERVAL '30 days',
    now() + INTERVAL '60 days',
    'active',
    now() - INTERVAL '2 hours'
),
(
    gen_random_uuid(), test_user_id,
    'ob-starling', 'Starling Bank',
    'SEED_ENCRYPTED_ACCESS_TOKEN_STARLING',
    'SEED_ENCRYPTED_REFRESH_TOKEN_STARLING',
    now() + INTERVAL '1 hour',
    now() - INTERVAL '80 days',
    now() + INTERVAL '10 days',
    'expiring_soon',
    now() - INTERVAL '4 hours'
)
RETURNING id INTO conn_monzo;

-- Retrieve both connection IDs
SELECT id INTO conn_monzo
    FROM public.bank_connections
    WHERE user_id = test_user_id AND provider_id = 'ob-monzo';
SELECT id INTO conn_starling
    FROM public.bank_connections
    WHERE user_id = test_user_id AND provider_id = 'ob-starling';


-- ── Step 2: accounts ─────────────────────────────────────────────────────────

INSERT INTO public.accounts (
    id, user_id, bank_connection_id, truelayer_account_id,
    account_type, display_name, currency,
    current_balance, available_balance, balance_updated_at
) VALUES
(
    gen_random_uuid(), test_user_id, conn_monzo,
    'tl-monzo-current-001',
    'current', 'Monzo Current Account', 'GBP',
    1543.27, 1543.27, now() - INTERVAL '2 hours'
),
(
    gen_random_uuid(), test_user_id, conn_monzo,
    'tl-monzo-savings-001',
    'savings', 'Monzo Savings Pot', 'GBP',
    5200.00, 5200.00, now() - INTERVAL '2 hours'
),
(
    gen_random_uuid(), test_user_id, conn_starling,
    'tl-starling-current-001',
    'current', 'Starling Current Account', 'GBP',
    892.50, 850.00, now() - INTERVAL '4 hours'
),
(
    gen_random_uuid(), test_user_id, conn_starling,
    'tl-starling-cc-001',
    'credit_card', 'Starling Credit Card', 'GBP',
    -437.89, NULL, now() - INTERVAL '4 hours'
);

-- Retrieve account IDs
SELECT id INTO acct_monzo_current
    FROM public.accounts
    WHERE user_id = test_user_id AND truelayer_account_id = 'tl-monzo-current-001';
SELECT id INTO acct_monzo_savings
    FROM public.accounts
    WHERE user_id = test_user_id AND truelayer_account_id = 'tl-monzo-savings-001';
SELECT id INTO acct_starling_current
    FROM public.accounts
    WHERE user_id = test_user_id AND truelayer_account_id = 'tl-starling-current-001';
SELECT id INTO acct_starling_cc
    FROM public.accounts
    WHERE user_id = test_user_id AND truelayer_account_id = 'tl-starling-cc-001';


-- ── Step 3: transactions ─────────────────────────────────────────────────────
-- A mix of debits and credits across accounts over the last 30 days.

INSERT INTO public.transactions (
    user_id, account_id, truelayer_transaction_id,
    timestamp, description, amount, currency,
    transaction_type, merchant_name, auto_category, user_category
) VALUES
-- Monzo Current Account transactions
(test_user_id, acct_monzo_current, 'tl-txn-001',
 now() - INTERVAL '1 day', 'TESCO STORES 3217', -45.67, 'GBP',
 'DEBIT', 'Tesco', 'groceries', NULL),

(test_user_id, acct_monzo_current, 'tl-txn-002',
 now() - INTERVAL '2 days', 'TFL TRAVEL CHARGE', -2.80, 'GBP',
 'DEBIT', 'Transport for London', 'transport', NULL),

(test_user_id, acct_monzo_current, 'tl-txn-003',
 now() - INTERVAL '3 days', 'SALARY - ACME CORP', 3200.00, 'GBP',
 'CREDIT', NULL, 'income', NULL),

(test_user_id, acct_monzo_current, 'tl-txn-004',
 now() - INTERVAL '4 days', 'AMAZON.CO.UK MARKETPLACE', -29.99, 'GBP',
 'DEBIT', 'Amazon', 'shopping', 'electronics'),  -- user override

(test_user_id, acct_monzo_current, 'tl-txn-005',
 now() - INTERVAL '5 days', 'DIRECT DEBIT - VODAFONE', -32.00, 'GBP',
 'DIRECT_DEBIT', 'Vodafone', 'bills', NULL),

(test_user_id, acct_monzo_current, 'tl-txn-006',
 now() - INTERVAL '7 days', 'PRET A MANGER LONDON', -6.50, 'GBP',
 'DEBIT', 'Pret A Manger', 'eating_out', NULL),

(test_user_id, acct_monzo_current, 'tl-txn-007',
 now() - INTERVAL '10 days', 'STANDING ORDER - LANDLORD', -1200.00, 'GBP',
 'STANDING_ORDER', NULL, 'housing', NULL),

(test_user_id, acct_monzo_current, 'tl-txn-008',
 now() - INTERVAL '14 days', 'SHELL PETROL STATION', -55.40, 'GBP',
 'DEBIT', 'Shell', 'transport', NULL),

-- Starling Current Account transactions
(test_user_id, acct_starling_current, 'tl-txn-009',
 now() - INTERVAL '1 day', 'SAINSBURYS SUPERMARKET', -32.18, 'GBP',
 'DEBIT', 'Sainsbury''s', 'groceries', NULL),

(test_user_id, acct_starling_current, 'tl-txn-010',
 now() - INTERVAL '3 days', 'NETFLIX.COM', -15.99, 'GBP',
 'DEBIT', 'Netflix', 'entertainment', 'subscriptions'),  -- user override

(test_user_id, acct_starling_current, 'tl-txn-011',
 now() - INTERVAL '6 days', 'TRANSFER IN', 500.00, 'GBP',
 'CREDIT', NULL, 'transfers', NULL),

-- Starling Credit Card transactions
(test_user_id, acct_starling_cc, 'tl-txn-012',
 now() - INTERVAL '2 days', 'JOHN LEWIS OXFORD ST', -189.00, 'GBP',
 'DEBIT', 'John Lewis', 'shopping', NULL),

(test_user_id, acct_starling_cc, 'tl-txn-013',
 now() - INTERVAL '5 days', 'WAGAMAMA LONDON', -28.50, 'GBP',
 'DEBIT', 'Wagamama', 'eating_out', NULL),

(test_user_id, acct_starling_cc, 'tl-txn-014',
 now() - INTERVAL '8 days', 'PAYMENT RECEIVED - THANK YOU', 200.00, 'GBP',
 'CREDIT', NULL, 'transfers', NULL);


-- ── Step 4: balance_history ──────────────────────────────────────────────────
-- 14 days of daily balance snapshots for net worth trend chart.

INSERT INTO public.balance_history (user_id, account_id, balance, recorded_at) VALUES
-- Monzo Current
(test_user_id, acct_monzo_current, 1380.00, CURRENT_DATE - 13),
(test_user_id, acct_monzo_current, 1377.20, CURRENT_DATE - 12),
(test_user_id, acct_monzo_current, 1350.00, CURRENT_DATE - 11),
(test_user_id, acct_monzo_current, 1294.60, CURRENT_DATE - 10),
(test_user_id, acct_monzo_current, 1294.60, CURRENT_DATE - 9),
(test_user_id, acct_monzo_current, 1294.60, CURRENT_DATE - 8),
(test_user_id, acct_monzo_current, 1242.00, CURRENT_DATE - 7),
(test_user_id, acct_monzo_current, 1235.50, CURRENT_DATE - 6),
(test_user_id, acct_monzo_current, 1235.50, CURRENT_DATE - 5),
(test_user_id, acct_monzo_current, 1203.50, CURRENT_DATE - 4),
(test_user_id, acct_monzo_current, 4403.50, CURRENT_DATE - 3),  -- salary day
(test_user_id, acct_monzo_current, 4400.70, CURRENT_DATE - 2),
(test_user_id, acct_monzo_current, 1597.90, CURRENT_DATE - 1),
(test_user_id, acct_monzo_current, 1543.27, CURRENT_DATE),

-- Monzo Savings (stable)
(test_user_id, acct_monzo_savings, 5200.00, CURRENT_DATE - 13),
(test_user_id, acct_monzo_savings, 5200.00, CURRENT_DATE - 6),
(test_user_id, acct_monzo_savings, 5200.00, CURRENT_DATE),

-- Starling Current
(test_user_id, acct_starling_current, 710.00, CURRENT_DATE - 13),
(test_user_id, acct_starling_current, 678.00, CURRENT_DATE - 10),
(test_user_id, acct_starling_current, 1178.00, CURRENT_DATE - 6),  -- transfer in
(test_user_id, acct_starling_current, 945.82, CURRENT_DATE - 3),
(test_user_id, acct_starling_current, 892.50, CURRENT_DATE),

-- Starling Credit Card (liability — negative contribution)
(test_user_id, acct_starling_cc, -420.39, CURRENT_DATE - 13),
(test_user_id, acct_starling_cc, -420.39, CURRENT_DATE - 8),
(test_user_id, acct_starling_cc, -220.39, CURRENT_DATE - 5),  -- payment
(test_user_id, acct_starling_cc, -437.89, CURRENT_DATE - 2),
(test_user_id, acct_starling_cc, -437.89, CURRENT_DATE);

RAISE NOTICE 'Seed data inserted successfully for user %', test_user_id;
RAISE NOTICE 'Connections: % (Monzo), % (Starling)', conn_monzo, conn_starling;
RAISE NOTICE 'Accounts: 4 (2 current, 1 savings, 1 credit card)';
RAISE NOTICE 'Transactions: 14';
RAISE NOTICE 'Balance history: 27 data points over 14 days';

END $$;
