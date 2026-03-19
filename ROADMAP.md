# Development Roadmap

**Project:** UK Personal Finance Aggregator
**Version:** 0.1.0 (Planning Phase)
**Last Updated:** 2026-03-17
**Sprint Duration:** 2 weeks each

---

## Sprint Overview

| Sprint | Theme | Duration | Depends On |
|---|---|---|---|
| 0 | Project Setup & Tooling | 1 week | — |
| 1 | Auth & Database Foundation | 2 weeks | Sprint 0 |
| 2 | TrueLayer Handshake (Sandbox) | 2 weeks | Sprint 1 |
| 3 | Sync Engine & Transactions | 2 weeks | Sprint 2 |
| 4 | Dashboard & Net Worth | 2 weeks | Sprint 3 |
| 5 | Consent Management & Notifications | 2 weeks | Sprint 4 |
| 6 | Polish, Testing & Sandbox Sign-Off | 2 weeks | Sprint 5 |
| 7 | Production Prep & TrueLayer Live | 2 weeks | Sprint 6 |

**Total estimated timeline: ~15 weeks**

---

## Sprint 0: Project Setup & Tooling (1 week)

**Goal:** Repository structure, CI pipeline, and development environments ready.

### Tasks

- [ ] Initialise Git repository with `.gitignore` (Python, Flutter, env files)
- [ ] Create `backend/` directory with FastAPI skeleton (`main.py`, health check endpoint)
- [ ] Create `mobile/penny/` Flutter project via `flutter create`
- [ ] Set up Supabase project (cloud or local via `supabase init`)
- [ ] Create `.env.example` files for backend and mobile with all required variables
- [ ] Set up `requirements.txt` / `pyproject.toml` with initial dependencies:
  - `fastapi`, `uvicorn`, `httpx`, `pydantic-settings`, `cryptography`, `supabase-py`, `apscheduler`
- [ ] Set up `pubspec.yaml` with initial Flutter dependencies:
  - `supabase_flutter`, `http`, `flutter_riverpod` (or provider of choice), `url_launcher`
- [ ] Configure linting: `ruff` for Python, `flutter analyze` for Dart
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

- [ ] Write Supabase migration `001_create_bank_connections.sql`
- [ ] Write Supabase migration `002_create_accounts.sql`
- [ ] Write Supabase migration `003_create_transactions.sql`
- [ ] Write Supabase migration `004_create_balance_history.sql`
- [ ] Write Supabase migration `005_enable_rls.sql` (all RLS policies from ARCH.md §4.2)
- [ ] Run migrations against Supabase and verify via SQL editor
- [ ] Write seed data script for development/testing

### Week 2: Authentication

- [ ] Configure Supabase Auth: enable email/password sign-up
- [ ] Implement FastAPI JWT verification middleware (validate Supabase JWTs)
- [ ] Create FastAPI dependency `get_current_user()` that extracts `user_id` from JWT
- [ ] Build Flutter sign-up screen (email + password)
- [ ] Build Flutter login screen
- [ ] Integrate `supabase_flutter` SDK for auth in the mobile app
- [ ] Store Supabase session/JWT securely on device (Supabase SDK handles this)
- [ ] Implement logout flow
- [ ] Test: protected FastAPI endpoint returns 401 without valid JWT, 200 with it

### Definition of Done
- A new user can sign up, log in, and log out via the Flutter app
- All database tables exist with correct constraints and RLS policies
- FastAPI rejects unauthenticated requests and correctly identifies the user from JWT

---

## Sprint 2: TrueLayer Handshake — Sandbox (2 weeks)

**Goal:** Users can connect a sandbox bank account via TrueLayer and see their accounts listed.

### Week 1: Backend — TrueLayer OAuth

- [ ] Register app with TrueLayer and obtain sandbox credentials
- [ ] Implement `services/truelayer.py`: TrueLayer API client class
  - `build_auth_url()` — construct the OAuth redirect URL
  - `exchange_code(code)` — POST to `/connect/token` to get tokens
  - `refresh_access_token(refresh_token)` — refresh expired access tokens
- [ ] Implement `services/encryption.py`: Fernet encrypt/decrypt for tokens
- [ ] Create `POST /api/v1/connections/initiate` — returns TrueLayer auth URL
- [ ] Create `POST /api/v1/connections/callback` — receives auth code, exchanges for tokens, encrypts and stores in `bank_connections`
- [ ] Create `GET /api/v1/connections` — list connections for current user
- [ ] Create `DELETE /api/v1/connections/{id}` — revoke and delete
- [ ] Write unit tests for encryption service
- [ ] Write integration tests for TrueLayer OAuth flow (mocked)

### Week 2: Mobile — Connect Bank Flow

- [ ] Build "Connect Bank" button on home screen
- [ ] Implement deep link handling for `pennyapp://callback` (iOS + Android)
- [ ] Open TrueLayer auth URL in system browser / in-app browser
- [ ] Handle callback: extract `code` from deep link and POST to backend
- [ ] Build "Connected Banks" list screen showing connected institutions
- [ ] Implement disconnect flow (confirmation dialog + DELETE call)
- [ ] Test full sandbox flow: connect mock bank → see connection in list

### Definition of Done
- User can tap "Connect Bank", complete TrueLayer sandbox OAuth, and return to the app
- `bank_connections` table has an encrypted token pair for the connection
- Connected bank appears in the app's bank list
- User can disconnect and the connection is removed

---

## Sprint 3: Sync Engine & Transactions (2 weeks)

**Goal:** The backend fetches accounts, balances, and transactions from TrueLayer and stores them without duplicates.

### Week 1: Sync Engine Core

- [ ] Implement `services/sync_engine.py`:
  - `sync_connection(connection_id)` — full sync flow per ARCH.md §5.3
  - Token refresh logic (check expiry, refresh if needed)
  - Fetch accounts from TrueLayer, upsert into `accounts` table
  - Fetch balances, update `accounts.current_balance` and `balance_history`
  - Fetch transactions with date range logic (initial vs incremental)
  - Upsert transactions with `ON CONFLICT` deduplication (ARCH.md §5.4)
- [ ] Implement `services/categorisation.py`: map TrueLayer `transaction_classification` to user-facing categories
- [ ] Handle TrueLayer credit card endpoints (`/data/v1/cards/*`) alongside account endpoints
- [ ] Write `POST /api/v1/sync` endpoint — triggers sync for current user
- [ ] Write `GET /api/v1/sync/status` endpoint — returns last sync time and errors
- [ ] Write unit tests for deduplication logic
- [ ] Write unit tests for categorisation mapping

### Week 2: Scheduled Sync & Mobile Transaction Feed

- [ ] Set up APScheduler to run `sync_all_active_connections()` every 4 hours
- [ ] Implement connection-level locking to prevent concurrent syncs of same connection
- [ ] Implement error handling and retry logic (ARCH.md §5.5)
- [ ] Create `GET /api/v1/transactions` endpoint with pagination, filtering (account, category, date range)
- [ ] Build Flutter transaction list screen:
  - Unified feed from all accounts, sorted by date
  - Each row: date, description, amount (colour-coded), category icon, source account
  - Pull-to-refresh triggers manual sync
- [ ] Build Flutter transaction detail view
- [ ] Implement `PATCH /api/v1/transactions/{id}/category` for manual category override
- [ ] Build category picker UI in transaction detail
- [ ] Test: verify no duplicates after multiple syncs of same data

### Definition of Done
- Backend fetches and stores accounts, balances, and transactions from TrueLayer sandbox
- Scheduled sync runs without duplicating data
- Flutter app displays a unified transaction feed across all connected accounts
- User can manually re-categorise a transaction and the override persists

---

## Sprint 4: Dashboard & Net Worth (2 weeks)

**Goal:** Home screen shows total net worth, per-account breakdown, and trend data.

### Week 1: Backend — Net Worth API

- [ ] Create `GET /api/v1/accounts` — list all accounts with balances
- [ ] Create `GET /api/v1/accounts/{id}` — single account detail
- [ ] Create `GET /api/v1/net-worth` — returns:
  - `total_net_worth` (sum of current/savings balances minus credit card balances)
  - `accounts[]` with per-account contribution
  - `last_updated` timestamp
- [ ] Create `GET /api/v1/net-worth/history` — daily net worth from `balance_history`, supports `period` param (7d, 30d, 90d)
- [ ] Ensure `balance_history` is populated correctly during each sync
- [ ] Write tests for net worth calculation (verify credit cards are subtracted)

### Week 2: Mobile — Dashboard UI

- [ ] Build home/dashboard screen:
  - Net worth summary card (large number, currency formatted)
  - Change indicator (vs yesterday / last week / last month)
  - Stale data indicator showing when each account was last synced
- [ ] Build account list section (expandable cards per account):
  - Account name, institution logo placeholder, balance
  - Tap to view account transactions
- [ ] Build simple net worth trend chart (line chart, last 30 days)
  - Use `fl_chart` or similar Flutter charting package
- [ ] Implement pull-to-refresh on dashboard (triggers sync, refreshes data)
- [ ] Handle loading states and empty states (no accounts connected yet)
- [ ] Handle credit card display (show balance as liability, negative contribution to net worth)

### Definition of Done
- Dashboard shows correct net worth with credit cards subtracted
- Per-account breakdown is visible and accurate
- Net worth trend chart displays historical data
- Pull-to-refresh triggers a sync and updates displayed data

---

## Sprint 5: Consent Management & Notifications (2 weeks)

**Goal:** The app proactively manages 90-day consent windows and alerts users before expiry.

### Week 1: Backend — Consent Lifecycle

- [ ] Implement `jobs/consent_checker.py`:
  - Daily job that queries connections approaching expiry (< 7 days)
  - Updates status to `expiring_soon` or `expired`
- [ ] Implement push notification infrastructure:
  - Choose provider: Firebase Cloud Messaging (FCM)
  - Store device tokens in a `user_devices` table
  - Create notification service to send push notifications
- [ ] Send notifications at 7 days and 1 day before expiry
- [ ] Send notification on actual expiry
- [ ] Create `POST /api/v1/connections/{id}/reconnect` — generates fresh TrueLayer auth URL for re-consent
- [ ] On successful re-consent callback: reset `consent_created_at`, `consent_expires_at`, update status to `active`
- [ ] Write tests for consent expiry logic (mock time)

### Week 2: Mobile — Consent UI

- [ ] Add consent status indicators to connected banks list:
  - Green: active (> 7 days remaining)
  - Amber: expiring soon (< 7 days)
  - Red: expired
- [ ] Build dashboard banner: "Your {bank} connection expires in X days" (dismissible but persistent)
- [ ] Build re-consent flow: tap banner or bank → opens TrueLayer re-auth
- [ ] Handle expired state gracefully:
  - Historical data still visible but labelled as stale
  - "Reconnect" button prominently displayed
  - No crash or blank screen
- [ ] Integrate FCM for push notifications (iOS + Android setup)
- [ ] Test full consent lifecycle:
  - Connect → wait (or mock) → receive "expiring soon" notification → re-consent → status resets

### Definition of Done
- Backend correctly identifies and flags expiring/expired connections
- Push notifications fire at 7 days and 1 day before expiry
- User can re-consent from within the app and the 90-day window resets
- Expired connections display historical data with clear "expired" labelling

---

## Sprint 6: Polish, Testing & Sandbox Sign-Off (2 weeks)

**Goal:** App is stable, well-tested, and fully functional against TrueLayer sandbox.

### Week 1: Testing & Bug Fixes

- [ ] Write end-to-end tests for critical flows:
  - Sign up → connect bank → sync → view dashboard → view transactions
  - Disconnect bank → data removed
  - Re-consent flow
- [ ] Backend test coverage target: 80%+ on services and routers
- [ ] Flutter widget tests for key screens (dashboard, transaction list)
- [ ] Load testing: simulate 100 concurrent syncs, verify no duplicates or deadlocks
- [ ] Fix all known bugs from previous sprints
- [ ] Security review:
  - Verify tokens are encrypted in DB (inspect raw values)
  - Verify RLS prevents cross-user data access
  - Verify JWT validation cannot be bypassed
  - Verify no secrets in source code or logs

### Week 2: UX Polish & Performance

- [ ] Add loading skeletons / shimmer effects on all data-loading screens
- [ ] Add error states with retry buttons
- [ ] Implement local caching strategy (SQLite or Hive for offline access to recent data)
- [ ] Optimise transaction list performance (lazy loading, pagination)
- [ ] Review and improve category mapping accuracy
- [ ] Add app icon and splash screen
- [ ] Accessibility review (contrast, screen reader labels, tap target sizes)
- [ ] Final walkthrough of all flows on both iOS and Android simulators

### Definition of Done
- All critical paths tested and passing
- No P0/P1 bugs outstanding
- App feels responsive and handles errors gracefully
- Security checklist passed

---

## Sprint 7: Production Preparation & TrueLayer Live (2 weeks)

**Goal:** Migrate from sandbox to live TrueLayer credentials, deploy to production infrastructure, prepare for first real users.

### Week 1: Infrastructure & Deployment

- [ ] Set up production Supabase project (separate from dev/sandbox)
- [ ] Run all migrations against production database
- [ ] Deploy FastAPI to production hosting (options: Railway, Fly.io, AWS ECS)
- [ ] Set up production environment variables (secrets manager)
- [ ] Configure production logging and monitoring (e.g., Sentry for errors, basic health monitoring)
- [ ] Set up database backup schedule
- [ ] Configure production CORS and rate limiting
- [ ] Set up staging environment (mirrors production, uses TrueLayer sandbox)

### Week 2: TrueLayer Live & App Store Prep

- [ ] Apply for TrueLayer production access (requires compliance review)
- [ ] Switch to TrueLayer live credentials in production config
- [ ] Test with real bank account (developer's own account)
- [ ] Verify real transaction data flows through correctly
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

## Post-MVP Backlog (Unscheduled)

These items are candidates for future sprints after the MVP is stable:

| Feature | Estimated Effort | Priority |
|---|---|---|
| Budgeting (monthly limits per category) | 2 sprints | High |
| Recurring payment / subscription detection | 1 sprint | High |
| Spending analytics and charts | 1 sprint | Medium |
| Savings goals | 1 sprint | Medium |
| Transaction search (full-text) | 0.5 sprint | Medium |
| Export to CSV | 0.5 sprint | Low |
| Multi-currency support | 1 sprint | Low |
| Shared accounts / households | 2 sprints | Low |
| Biometric auth (FaceID / fingerprint) | 0.5 sprint | Medium |
| Dark mode | 0.5 sprint | Low |

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
