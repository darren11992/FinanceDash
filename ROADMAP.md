# Development Roadmap

**Project:** Penny — UK Personal Finance Aggregator
**Version:** 0.1.0 (Active Development)
**Last Updated:** 2026-04-07
**Sprint Duration:** 2 weeks each

---

## Sprint Overview

| Sprint | Theme | Duration | Depends On | Status |
|---|---|---|---|---|
| 0 | Project Setup & Tooling | 1 week | — | Complete |
| 1 | Auth & Database Foundation | 2 weeks | Sprint 0 | Complete |
| 2 | TrueLayer Handshake (Sandbox) | 2 weeks | Sprint 1 | Complete |
| 3 | Sync Engine & Transactions | 2 weeks | Sprint 2 | Complete |
| 4 | Dashboard & Net Worth | 2 weeks | Sprint 3 | Complete |
| 5 | Consent Management (No Push Notifications) | 2 weeks | Sprint 4 | Complete |
| — | Categorisation Rewrite (unplanned) | — | Sprint 5 + Live data | Complete |
| — | TrueLayer Live Connection (unplanned) | — | Sprint 5 | Complete |
| 6 | Polish, Testing & Hardening | 2 weeks | Sprint 5 | Complete |
| 7 | Production Deployment & App Store | 2 weeks | Sprint 6 | Not Started |
| 8 | Tech Debt & Dependency Upgrades | 1 week | Sprint 7 | Not Started |

**Total estimated timeline: ~16 weeks**

---

## Sprint 0: Project Setup & Tooling (1 week)

**Goal:** Repository structure, CI pipeline, and development environments ready.

### Tasks

- [x] Initialise Git repository with `.gitignore` (Python, Flutter, env files)
- [x] Create `backend/` directory with FastAPI skeleton (`main.py`, health check endpoint)
- [x] Create `mobile/penny/` Flutter project via `flutter create`
- [x] Set up Supabase project (cloud or local via `supabase init`)
- [x] Create `.env.example` files for backend and mobile with all required variables
- [x] Set up `requirements.txt` / `pyproject.toml` with initial dependencies:
  - `fastapi`, `uvicorn`, `httpx`, `pydantic-settings`, `cryptography`, `supabase-py`, `apscheduler`
- [x] Set up `pubspec.yaml` with initial Flutter dependencies:
  - `supabase_flutter`, `http`, `flutter_riverpod` (or provider of choice), `url_launcher`
- [x] Configure linting: `ruff` for Python, `flutter analyze` for Dart
- [ ] Create basic CI pipeline (GitHub Actions): lint + test for both backend and mobile
- [ ] Write a `docker-compose.yml` for local development (FastAPI + Supabase local)

### Definition of Done
- `GET /health` returns `200 OK` from FastAPI
- Flutter app builds and runs on a simulator
- Supabase project accessible with publishable/secret keys
- CI pipeline runs green on push

---

## Sprint 1: Auth & Database Foundation (2 weeks)

**Goal:** Users can sign up, log in, and the database schema is deployed.

### Week 1: Database Schema

- [x] Write Supabase migration `001_create_bank_connections.sql`
- [x] Write Supabase migration `002_create_accounts.sql`
- [x] Write Supabase migration `003_create_transactions.sql`
- [x] Write Supabase migration `004_create_balance_history.sql`
- [x] Write Supabase migration `005_enable_rls.sql` (all RLS policies from ARCH.md §4.2)
- [x] Run migrations against Supabase and verify via SQL editor
- [x] Write seed data script for development/testing

### Week 2: Authentication

- [x] Configure Supabase Auth: enable email/password sign-up
- [x] Implement FastAPI JWT verification middleware (validate Supabase JWTs)
- [x] Create FastAPI dependency `get_current_user()` that extracts `user_id` from JWT
- [x] Build Flutter sign-up screen (email + password)
- [x] Build Flutter login screen
- [x] Integrate `supabase_flutter` SDK for auth in the mobile app
- [x] Store Supabase session/JWT securely on device (Supabase SDK handles this)
- [x] Implement logout flow
- [x] Test: protected FastAPI endpoint returns 401 without valid JWT, 200 with it

### Definition of Done
- A new user can sign up, log in, and log out via the Flutter app
- All database tables exist with correct constraints and RLS policies
- FastAPI rejects unauthenticated requests and correctly identifies the user from JWT

---

## Sprint 2: TrueLayer Handshake — Sandbox (2 weeks)

**Goal:** Users can connect a sandbox bank account via TrueLayer and see their accounts listed.

### Week 1: Backend — TrueLayer OAuth

- [x] Register app with TrueLayer and obtain sandbox credentials
- [x] Implement `services/truelayer.py`: TrueLayer API client class
  - `build_auth_url()` — construct the OAuth redirect URL
  - `exchange_code(code)` — POST to `/connect/token` to get tokens
  - `refresh_access_token(refresh_token)` — refresh expired access tokens
- [x] Implement `services/encryption.py`: Fernet encrypt/decrypt for tokens
- [x] Create `POST /api/v1/connections/initiate` — returns TrueLayer auth URL
- [x] Create `POST /api/v1/connections/callback` — receives auth code, exchanges for tokens, encrypts and stores in `bank_connections`
- [x] Create `GET /api/v1/connections` — list connections for current user
- [x] Create `DELETE /api/v1/connections/{id}` — revoke and delete
- [x] Write unit tests for encryption service
- [x] Write integration tests for TrueLayer OAuth flow (mocked)

### Week 2: Mobile — Connect Bank Flow

- [x] Build "Connect Bank" button on home screen
- [x] Implement deep link handling for `pennyapp://callback` (iOS + Android)
- [x] Open TrueLayer auth URL in system browser / in-app browser
- [x] Handle callback: extract `code` from deep link and POST to backend
- [x] Build "Connected Banks" list screen showing connected institutions
- [x] Implement disconnect flow (confirmation dialog + DELETE call)
- [x] Test full sandbox flow: connect mock bank → see connection in list

### Definition of Done
- User can tap "Connect Bank", complete TrueLayer sandbox OAuth, and return to the app
- `bank_connections` table has an encrypted token pair for the connection
- Connected bank appears in the app's bank list
- User can disconnect and the connection is removed

---

## Sprint 3: Sync Engine & Transactions (2 weeks)

**Goal:** The backend fetches accounts, balances, and transactions from TrueLayer and stores them without duplicates.

### Week 1: Sync Engine Core

- [x] Implement `services/sync_engine.py`:
  - `sync_connection(connection_id)` — full sync flow per ARCH.md §5.3
  - Token refresh logic (check expiry, refresh if needed)
  - Fetch accounts from TrueLayer, upsert into `accounts` table
  - Fetch balances, update `accounts.current_balance` and `balance_history`
  - Fetch transactions with date range logic (initial vs incremental)
  - Upsert transactions with `ON CONFLICT` deduplication (ARCH.md §5.4)
- [x] Implement `services/categorisation.py`: map TrueLayer `transaction_classification` to user-facing categories
- [x] Handle TrueLayer credit card endpoints (`/data/v1/cards/*`) alongside account endpoints
- [x] Write `POST /api/v1/sync` endpoint — triggers sync for current user
- [x] Write `GET /api/v1/sync/status` endpoint — returns last sync time and errors
- [x] Write unit tests for deduplication logic
- [x] Write unit tests for categorisation mapping

### Week 2: Scheduled Sync & Mobile Transaction Feed

- [x] Set up APScheduler to run `sync_all_active_connections()` every 4 hours
- [x] Implement connection-level locking to prevent concurrent syncs of same connection
- [x] Implement error handling and retry logic (ARCH.md §5.5)
- [x] Create `GET /api/v1/transactions` endpoint with pagination, filtering (account, category, date range)
- [x] Build Flutter transaction list screen:
  - Unified feed from all accounts, sorted by date
  - Each row: date, description, amount (colour-coded), category icon, source account
  - Pull-to-refresh triggers manual sync
- [x] Build Flutter transaction detail view
- [x] Implement `PATCH /api/v1/transactions/{id}/category` for manual category override
- [x] Build category picker UI in transaction detail
- [x] Test: verify no duplicates after multiple syncs of same data

### Definition of Done
- Backend fetches and stores accounts, balances, and transactions from TrueLayer sandbox
- Scheduled sync runs without duplicating data
- Flutter app displays a unified transaction feed across all connected accounts
- User can manually re-categorise a transaction and the override persists

---

## Sprint 4: Dashboard & Net Worth (2 weeks)

**Goal:** Home screen shows total net worth, per-account breakdown, and trend data.

### Week 1: Backend — Net Worth API

- [x] Create `GET /api/v1/accounts` — list all accounts with balances
- [x] Create `GET /api/v1/accounts/{id}` — single account detail
- [x] Create `GET /api/v1/net-worth` — returns:
  - `total_net_worth` (sum of current/savings balances minus credit card balances)
  - `accounts[]` with per-account contribution
  - `last_updated` timestamp
- [x] Create `GET /api/v1/net-worth/history` — daily net worth from `balance_history`, supports `period` param (7d, 30d, 90d)
- [x] Ensure `balance_history` is populated correctly during each sync
- [x] Write tests for net worth calculation (verify credit cards are subtracted)
- [x] **Enhancement:** Balance history backfill — two-tier strategy (running_balance preferred, reverse-compute fallback) with `is_estimated` flag, runs on initial sync

### Week 2: Mobile — Dashboard UI

- [x] Build home/dashboard screen:
  - Net worth summary card (large number, currency formatted)
  - Change indicator (vs yesterday / last week / last month)
  - Stale data indicator showing when each account was last synced
- [x] Build account list section (expandable cards per account):
  - Account name, institution logo placeholder, balance
  - Tap to view account transactions
- [x] Build simple net worth trend chart (line chart, last 30 days)
  - Use `fl_chart` or similar Flutter charting package
- [x] Implement pull-to-refresh on dashboard (triggers sync, refreshes data)
- [x] Handle loading states and empty states (no accounts connected yet)
- [x] Handle credit card display (show balance as liability, negative contribution to net worth)
- [x] **Enhancement:** Estimated data indicator on trend chart when backfilled data is present

### Definition of Done
- Dashboard shows correct net worth with credit cards subtracted
- Per-account breakdown is visible and accurate
- Net worth trend chart displays historical data
- Pull-to-refresh triggers a sync and updates displayed data

---

## Sprint 5: Consent Management (2 weeks) — COMPLETE

**Goal:** The app proactively manages 90-day consent windows and alerts users before expiry.

> **Note:** Push notifications (FCM) were explicitly deferred. This sprint covers consent
> lifecycle detection, in-app banners, and reconnect flow only. No Firebase, no Apple
> Developer Account, no device token storage.

### Week 1: Backend — Consent Lifecycle

- [x] Implement `jobs/consent_checker.py`:
  - Daily job that queries connections approaching expiry (< 7 days)
  - Updates status to `expiring_soon` or `expired`
- [x] Create `POST /api/v1/connections/{id}/reconnect` — calls TrueLayer `extend_connection()`, returns either fresh tokens (no_action_needed) or a re-auth URL (authentication_needed)
- [x] On successful re-consent callback: reset `consent_created_at`, `consent_expires_at`, update status to `active`
- [x] Write tests for consent expiry logic (mock time) — 9 tests in `test_consent_checker.py`
- [x] Write tests for reconnect endpoint — 7 tests in `test_connections.py`
- [x] Wire consent checker as second APScheduler job in `scheduled_sync.py`
- [ ] ~~Implement push notification infrastructure (FCM)~~ — **Deferred** to post-MVP
- [ ] ~~Send notifications at 7 days and 1 day before expiry~~ — **Deferred** to post-MVP
- [ ] ~~Send notification on actual expiry~~ — **Deferred** to post-MVP

### Week 2: Mobile — Consent UI

- [x] Add consent status indicators to connected banks list:
  - Green: active (> 7 days remaining)
  - Amber: expiring soon (< 7 days)
  - Red: expired
- [x] Build dashboard banner (`_ExpiryBanner`): "Your {bank} connection expires in X days"
- [x] Build re-consent flow (`_ReconnectBanner`): tap banner or bank → calls reconnect endpoint → opens TrueLayer re-auth if needed
- [x] Handle expired state gracefully:
  - Historical data still visible but labelled as stale
  - "Reconnect" button prominently displayed
  - No crash or blank screen
- [x] Connection model extended: `daysUntilExpiry`, `isExpiringSoon`, `isExpired`, `needsReconnect`
- [ ] ~~Integrate FCM for push notifications (iOS + Android setup)~~ — **Deferred** to post-MVP

### Definition of Done
- ~~Push notifications fire at 7 days and 1 day before expiry~~ — Deferred
- [x] Backend correctly identifies and flags expiring/expired connections
- [x] User can re-consent from within the app and the 90-day window resets
- [x] Expired connections display historical data with clear "expired" labelling
- [x] 257 backend tests passing (including consent checker, reconnect, categorisation)

---

## Unplanned: Categorisation Rewrite — COMPLETE

**Trigger:** Connecting a real UK bank revealed that TrueLayer's `transaction_classification`
array is always empty for real providers. All transactions were categorised as "General".

### What was done

- [x] Rewrote `services/categorisation.py` with three-tier approach:
  1. TrueLayer `transaction_classification` array (when available — works for sandbox only)
  2. Description-based regex keyword matching (~130 rules covering UK supermarkets, restaurants, transport, subscriptions, banks, shopping, entertainment, health, travel)
  3. Default fallback to "General"
- [x] Payment-type structural rules (e.g. "BILL PAYMENT VIA FASTER PAYMENT TO") evaluated first to correctly classify person-to-person transfers even when reference text mentions a merchant
- [x] Updated `sync_engine.py` to pass `description` to `categorise_transaction()`
- [x] Rewrote `test_categorisation.py` — 65 tests covering all three tiers, including tests against real UK bank transaction descriptions
- [x] Added `POST /api/v1/transactions/recategorise` endpoint — re-runs categorisation engine on all existing transactions in the database (preserves `user_category` overrides)
- [x] 6 tests for recategorise endpoint in `test_transactions.py`

---

## Unplanned: TrueLayer Live Connection — COMPLETE

**Trigger:** TrueLayer Live credentials obtained. Switched from sandbox to live to test
with a real UK bank account.

### What was done

- [x] Switched `.env` to live TrueLayer credentials (no code changes — `is_sandbox` auto-detects from auth URL)
- [x] Successfully connected real UK bank account via TrueLayer Live
- [x] Real accounts, balances, and transactions syncing correctly
- [x] Improved error logging in `exchange_code()` to include TrueLayer response body
- [x] Discovered and fixed: real UK banks return empty `transaction_classification` (led to categorisation rewrite above)

---

## Sprint 6: Polish, Testing & Hardening (2 weeks) — COMPLETE

**Goal:** App is stable, well-tested, and production-ready. Already working against TrueLayer Live with real bank data.

> **Context:** TrueLayer Live is already connected and real data is flowing. This sprint
> is about hardening what we have, not sandbox sign-off. The categorisation rewrite and
> recategorise endpoint are already done.

### Week 1: Testing & Bug Fixes

- [x] Write end-to-end tests for critical flows — 25 tests in `test_e2e_flows.py`:
  - Sign up → connect bank → sync → view dashboard → view transactions
  - Disconnect bank → data removed
  - Re-consent flow
- [x] Backend test coverage: **304 tests** across 15 test files covering all services and routers
- [x] Flutter widget tests for key screens — 33 tests in `widget_test.dart` (dashboard, transaction list, connections, auth)
- [x] Load testing — 8 tests in `test_load.py`: simulate 100 concurrent syncs, verify no duplicates or deadlocks
- [x] Fix all known bugs from previous sprints
- [x] Security review — comprehensive audit with 13 findings (3 High, 7 Medium, 3 Low), all fixed:
  - Rate limiting via `slowapi` on all sensitive endpoints
  - `APP_DEBUG` default changed to `False`
  - OAuth state nonce store migrated to `TTLCache(maxsize=10_000, ttl=600)`
  - TrueLayer error details sanitised (no leak to clients)
  - Input validation: `max_length` on `code` and `category` fields
  - Category filter SQL injection prevention via regex validation
  - JWT issuer validation added
  - Global exception handler added (generic 500s in production)
  - `certifi` pinned in requirements.txt
  - 14 security tests in `test_security.py` — all passing

### Week 2: UX Polish & Performance

- [x] Add loading skeletons / shimmer effects on all data-loading screens — `skeleton_loaders.dart` with 6 reusable shimmer widgets (using `shimmer ^3.0.0`)
- [x] Add error states with retry buttons — all screens show error + retry on failure
- [x] Implement local caching strategy — `CacheService` using `shared_preferences` with JSON serialisation and 1-hour staleness window; cache-first-then-network pattern in all providers; cache cleared on sign-out
- [x] Optimise transaction list performance (lazy loading, pagination) — already implemented via paginated API + PostgREST `.range()`
- [x] Review and improve category mapping accuracy (done: categorisation rewrite + recategorise endpoint)
- [x] Add branded splash screen — `PennyApp` converted to StatefulWidget with gradient coin logo, "Penny" title, tagline, and loading spinner during async init; error state with retry
- [x] Accessibility review — comprehensive audit, all P0/P1/P2 issues fixed:
  - `textOnDarkMuted` contrast upgraded from #5A7A96 to #85A0B9 (WCAG AA compliant)
  - Net worth chart wrapped in descriptive `Semantics` (value, direction, percentage)
  - All 6 skeleton loaders wrapped in `Semantics(label: ..., excludeSemantics: true)`
  - Error messages wrapped in `Semantics(liveRegion: true)` for screen reader announcement
  - Loading spinners given `semanticsLabel` properties
  - FAB given `tooltip: 'Connect Bank'`
- [ ] Final walkthrough of all flows on both iOS and Android simulators — **Deferred** (Xcode not installed; tested via `flutter build web`)

### Definition of Done
- [x] All critical paths tested and passing (304 backend tests, 33 Flutter widget tests)
- [x] No P0/P1 bugs outstanding
- [x] App feels responsive and handles errors gracefully (shimmer skeletons, cache-first loading, retry buttons)
- [x] Security checklist passed (13 findings, all resolved)

---

## Sprint 7: Production Deployment & App Store (2 weeks)

**Goal:** Deploy to production infrastructure and prepare for first real users.

> **Context:** TrueLayer Live is already working in local dev (done ahead of schedule).
> This sprint focuses on production infrastructure and app store submission.

### Week 1: Infrastructure & Deployment

- [ ] Set up production Supabase project (separate from dev)
- [ ] Run all migrations against production database
- [ ] Deploy FastAPI to production hosting (options: Railway, Fly.io, AWS ECS)
- [ ] Set up production environment variables (secrets manager)
- [ ] Configure production logging and monitoring (e.g., Sentry for errors, basic health monitoring)
- [ ] Set up database backup schedule
- [ ] Configure production CORS and rate limiting
- [ ] Set up staging environment (mirrors production, uses TrueLayer sandbox)

### Week 2: App Store Prep

- [x] ~~Apply for TrueLayer production access~~ — Already have live credentials
- [x] ~~Switch to TrueLayer live credentials~~ — Already done in local dev
- [x] ~~Test with real bank account (developer's own account)~~ — Already done
- [x] ~~Verify real transaction data flows through correctly~~ — Already verified, including categorisation fix
- [ ] Prepare App Store listing (screenshots, description, privacy policy)
- [ ] Prepare Google Play listing
- [ ] Draft privacy policy and terms of service (required for app stores and FCA compliance)
- [ ] Internal beta via TestFlight (iOS) and Google Play Internal Testing (Android)
- [ ] Create runbook for common operational tasks (manual sync trigger, user data export, connection debugging)

### Definition of Done
- App connects to real UK bank accounts via TrueLayer live
- Backend deployed to production with monitoring
- Real transactions sync without issues
- App submitted for internal beta testing
- Privacy policy and terms of service drafted

---

## Sprint 8: Tech Debt & Dependency Upgrades (1 week)

**Goal:** Upgrade all dependencies to latest major versions, clean up accumulated tech debt, and ensure the codebase is maintainable going forward.

### Flutter Dependency Upgrades

- [ ] Upgrade `flutter_riverpod` from ^2.6.1 to ^3.x — rewrite providers to use Riverpod 3 API (code generation, new provider syntax)
- [ ] Upgrade `app_links` from ^6.4.0 to ^7.x — update deep link listener API in `deep_link_service.dart`
- [ ] Upgrade `flutter_dotenv` from ^5.2.1 to ^6.x — update env loading calls if API changed
- [ ] Run `flutter pub upgrade --major-versions` for remaining transitive dependencies
- [ ] Run `flutter analyze` and fix any new lint warnings from upgraded packages
- [ ] Verify `flutter build web` compiles cleanly

### Backend Dependency Upgrades

- [ ] Audit `requirements.txt` — check all packages for latest stable versions
- [ ] Upgrade any backend dependencies with available major versions
- [ ] Run full test suite after upgrades, fix any breakage
- [ ] Regenerate `pip freeze > requirements-lock.txt` for reproducible builds

### General Tech Debt

- [ ] Review and remove any TODO/FIXME comments that are no longer relevant
- [ ] Consolidate error handling patterns across all backend routers
- [ ] Review logging — ensure all routes log enough context for debugging without leaking secrets
- [ ] Move TrueLayer state nonces from in-memory dict to Redis or DB (required for multi-worker production)
- [ ] Add type hints to any untyped functions in backend services
- [ ] Review Dart code for any `dynamic` types that can be made explicit

### Definition of Done
- All Flutter and backend dependencies on latest stable versions
- `flutter analyze` — 0 issues
- All backend tests pass
- No known tech debt items remaining that would block production operations

---

## Post-MVP Backlog (Unscheduled)

These items are candidates for future sprints after the MVP is stable:

| Feature | Estimated Effort | Priority |
|---|---|---|
| Trading212 integration (investment accounts) | 1.5 sprints | High |
| Budgeting (monthly limits per category) | 2 sprints | High |
| Recurring payment / subscription detection | 1 sprint | High |
| Spending analytics and charts | 1 sprint | Medium |
| Savings goals | 1 sprint | Medium |
| Manual account entry (Chip, other non-API accounts) | 0.5 sprint | Medium |
| Transaction search (full-text) | 0.5 sprint | Medium |
| Export to CSV | 0.5 sprint | Low |
| Multi-currency support | 1 sprint | Low |
| Shared accounts / households | 2 sprints | Low |
| Biometric auth (FaceID / fingerprint) | 0.5 sprint | Medium |
| Dark mode | 0.5 sprint | Low |

---

## Trading212 Integration — Detail

**Status:** Researched, ready to implement post-MVP
**API:** `https://live.trading212.com/api/v0/` (REST, API key auth, free for account holders)
**Docs:** `https://t212public-api-docs.redoc.ly/` (requires Redocly login)

Trading212 provides a public REST API giving read access to Invest & ISA account data. Authentication is via a personal API key generated in the T212 app (Settings > API). No OAuth flow — user pastes their key into Penny.

### Key Endpoints for Penny

| Endpoint | Data | Use in Penny |
|---|---|---|
| `GET equity/account/cash` | total, free, invested, P&L, pieCash | Account-level balances for net worth |
| `GET equity/portfolio` | All open positions (ticker, qty, avgPrice, currentPrice, ppl) | Holdings breakdown |
| `GET history/dividends` | Dividend payments (amount, ticker, date) | Income tracking |
| `GET equity/pies` | Pie allocations and performance | Portfolio groupings |
| `GET equity/account/info` | Account ID, currency | Account metadata |

### Implementation Plan (~1.5 sprints)

**Week 1 — Backend:**
- New `services/trading212.py` — API client (httpx, API key auth, rate limit handling)
- Schema extension: `provider_type` column on `accounts` table (`open_banking` | `trading212` | `manual`), new `investment_positions` table (ticker, quantity, average_price, current_price, ppl, fx_ppl, pie_name, account_id, user_id), new `investment_dividends` table
- New `routers/trading212.py` — `POST /connections/trading212` (store encrypted API key), `GET /trading212/portfolio`, `DELETE /connections/trading212/{id}`
- Sync engine extension: T212 positions sync alongside Open Banking account sync
- Net worth calculation updated to include T212 `total` (cash + invested)

**Week 2 — Flutter:**
- "Add Trading212" flow in connections screen — API key input field (no browser redirect)
- Portfolio/holdings screen showing positions, current value, P&L per holding
- T212 account card on home dashboard contributing to net worth
- Dividend history view

**Week 3 — Polish:**
- T212 sync scheduling (less frequent than bank sync — daily is fine, positions don't change as fast)
- Error handling for invalid/revoked API keys
- Tests for T212 service, sync, and routers

### Chip / Non-API Accounts

Chip (getchip.uk) savings accounts are held at ClearBank, which is a wholesale B2B bank. ClearBank accounts are not accessible via consumer Open Banking flows (TrueLayer/Yapily). Chip has no public API. Options:
- **Manual balance entry** — user enters/updates balance periodically (0.5 sprint, included in backlog above)
- **CSV import** — if Chip provides export functionality
- **Wait for Open Finance** — FCA framework that would extend Open Banking obligations to savings/investment providers (timeline: 2027+)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TrueLayer production approval delayed | Medium | High | Start application in Sprint 5; use sandbox for all development |
| Bank API inconsistencies (missing fields, different formats) | High | Medium | Defensive parsing with fallback defaults; log anomalies |
| Transaction deduplication edge cases | Medium | High | Database-level constraint as safety net; comprehensive test suite |
| Token encryption key rotation needed | Low | High | Design key rotation support from the start (versioned keys) |
| App store rejection | Low | Medium | Review guidelines early; ensure privacy policy is comprehensive |
| Scope creep into "nice-to-have" features | High | Medium | Strict sprint discipline; post-MVP backlog for all non-essential features |
