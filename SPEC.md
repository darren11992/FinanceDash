# Product Requirements Specification

**Project:** UK Personal Finance Aggregator
**Version:** 0.1.0 (Planning Phase)
**Last Updated:** 2026-03-17

---

## 1. Overview

A mobile-first personal finance aggregator targeting UK consumers. The app connects to users' bank accounts via Open Banking (TrueLayer), aggregates financial data across multiple institutions, and presents a unified view of their finances with automated transaction categorisation and net worth tracking.

---

## 2. Target Users

- UK residents with one or more current accounts, savings accounts, or credit cards
- Users who want a single view of finances spread across multiple banks (e.g., Monzo + Barclays + Amex)
- Financially-aware individuals who want automated spending insights without manual spreadsheet tracking

---

## 3. Must-Have Features (MVP)

### 3.1 Bank Account Aggregation (UK Banks)

| Requirement | Detail |
|---|---|
| Connect UK bank accounts | Via TrueLayer Data API using the OAuth/Open Banking redirect flow |
| Supported account types | Current accounts, savings accounts, credit cards |
| Multi-bank support | A single user can connect accounts from multiple institutions simultaneously |
| Account metadata | Display account name, type, currency (GBP), current balance, and institution branding |
| Disconnect flow | Users can revoke a bank connection from within the app at any time |

**Acceptance Criteria:**
- User taps "Connect Bank" and is redirected to TrueLayer's auth-link.
- After consent, the app stores the access/refresh token pair and fetches account data.
- Connected accounts appear on the dashboard within 5 seconds of returning from the redirect.

### 3.2 Transaction Fetching & Automated Categorisation

| Requirement | Detail |
|---|---|
| Transaction sync | Fetch transactions from all connected accounts via TrueLayer `/data/v1/accounts/{id}/transactions` |
| Historical depth | Fetch up to 12 months of transaction history on initial connection (subject to bank availability) |
| Incremental sync | Subsequent syncs fetch only new/updated transactions since the last successful sync |
| Deduplication | The sync engine must not create duplicate transaction records (see ARCH.md §5) |
| Auto-categorisation | Each transaction is assigned a category based on TrueLayer's `transaction_classification` field |
| Category mapping | Map TrueLayer's classification taxonomy to a simplified user-facing set of categories |
| Manual override | Users can re-categorise any transaction; overrides persist across future syncs |

**User-Facing Categories (Initial Set):**

| Category | Examples |
|---|---|
| Groceries | Tesco, Sainsbury's, Aldi |
| Eating Out | Deliveroo, Nando's, Pret |
| Transport | TfL, Uber, fuel stations |
| Shopping | Amazon, ASOS, John Lewis |
| Bills & Subscriptions | Netflix, Spotify, council tax |
| Salary & Income | Employer payments, HMRC refunds |
| Transfers | Between own accounts, to other people |
| Cash & ATM | ATM withdrawals |
| Entertainment | Cinema, gaming, events |
| Health & Fitness | Gym memberships, pharmacies |
| General | Uncategorised fallback |

**Acceptance Criteria:**
- All transactions from connected accounts appear in a unified feed, sorted by date descending.
- Each transaction displays: date, description, amount, category, and source account.
- Auto-categorisation covers at least 80% of transactions without manual intervention.

### 3.3 Total Net Worth Dashboard

| Requirement | Detail |
|---|---|
| Net worth calculation | Sum of all account balances (positive for current/savings, credit cards reflected as liability) |
| Dashboard view | Single summary card showing total net worth in GBP |
| Breakdown | Expandable view showing per-account contribution to net worth |
| Balance freshness | Display timestamp of last successful sync for each account |
| Trend indicator | Show net worth change vs. previous day/week/month (requires balance history) |

**Acceptance Criteria:**
- Dashboard loads as the home screen after authentication.
- Net worth is calculated from cached balances (no blocking API call on every app open).
- Credit card balances are subtracted from (not added to) net worth.

### 3.4 UK-Specific Compliance: 90-Day Consent Management

Under UK Open Banking regulations (PSD2 / FCA guidelines), AIS (Account Information Service) consent expires after a maximum of 90 days. After expiry, the app loses access to the user's bank data and must prompt re-authorisation.

| Requirement | Detail |
|---|---|
| Consent tracking | Store the `consent_created_at` timestamp for each bank connection |
| Expiry calculation | Flag connections approaching expiry (< 7 days remaining) |
| Proactive notification | Push notification at 7 days and 1 day before expiry |
| Re-consent flow | In-app prompt guiding the user through re-authorisation via TrueLayer |
| Expired state handling | Connections past 90 days are marked `expired`; stale data is retained but clearly labelled |
| Grace period UX | Show a banner on the dashboard when any connection is within 7 days of expiry |

**Acceptance Criteria:**
- The system never silently loses access. Users are always warned before consent expires.
- Re-consent refreshes the token and resets the 90-day window.
- Expired connections do not cause app crashes or blank screens; historical data remains visible with an "expired" label.

---

## 4. Nice-to-Have Features (Post-MVP)

These are explicitly out of scope for the initial build but documented for future planning:

- **Budgeting:** Set monthly spending limits per category with progress tracking.
- **Recurring payment detection:** Identify and list subscriptions automatically.
- **Spending analytics:** Charts showing weekly/monthly spending trends by category.
- **Multi-currency support:** For users with foreign-currency accounts.
- **Savings goals:** Track progress toward named financial targets.
- **Export to CSV/PDF:** Download transaction history.
- **Shared accounts/households:** Multiple users viewing shared finances.

---

## 5. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Performance | Dashboard loads in < 2s from cached data |
| Availability | Backend targets 99.5% uptime |
| Security | Tokens encrypted at rest; all API calls over HTTPS; Supabase RLS enforced on every table |
| Privacy | No transaction data shared with third parties; GDPR-compliant data deletion on account removal |
| Scalability | Architecture supports up to 10,000 users before requiring infrastructure changes |
| Platform | iOS and Android via single Flutter codebase |
| Region | UK only (GBP, FCA-regulated banks via TrueLayer) |

---

## 6. Glossary

| Term | Definition |
|---|---|
| AIS | Account Information Service — the regulatory category for apps that read (but don't write) bank data |
| PSD2 | Payment Services Directive 2 — EU/UK regulation enabling Open Banking |
| TrueLayer | Third-party Open Banking provider acting as the AISP (Account Information Service Provider) |
| Consent window | The 90-day period during which the app has permission to access a user's bank data |
| RLS | Row-Level Security — Supabase/PostgreSQL feature ensuring users can only access their own data |
