# MLIT Region Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import real MLIT transaction-price CSV downloads into a protected local/staging table and expose honest organization-scoped regional sale-price statistics to the B-side UI.

**Architecture:** Additive Supabase migration creates `public.mlit_transactions` with immutable raw payloads, provenance, constraints, indexes, and service-role-only writes. A Python importer downloads the official site’s base64 ZIP response by prefecture/year, normalizes explicit asset mappings, and upserts idempotently. FastAPI calculates median/quartiles/buckets from numeric rows at request time; the static B page renders localized stateful output.

**Tech Stack:** PostgreSQL/Supabase migrations, asyncpg, FastAPI/Pydantic, Python standard library CSV/ZIP/urllib, vanilla HTML/CSS/JavaScript, pytest, Playwright.

**Spec:** `/tmp/zouseeking-mb4-task.md`

## Global Constraints

- Use only real MLIT official downloads; never use estimates or synthetic fixtures as statistical input.
- All end-to-end imports use a disposable local database; never connect to production.
- API keys are environment variables only; no key is committed.
- Authentication and organization scope are server-side; UI restrictions are not authorization.
- No commit, push, deployment, SSH, or destructive database action.

---

### Task 1: Statistical contract and asset mapping

**Files:** Create `backend/app/region_stats.py`, Test `tests/unit/test_region_stats.py`.

- [ ] Write failing tests for explicit MLIT kind mappings, median/p25/p75, fixed bucket boundaries, insufficient sample, and unavailable rent-sale ratio.
- [ ] Run `backend/.venv/bin/python -m pytest tests/unit/test_region_stats.py -q` and observe the missing-module failure.
- [ ] Implement pure numeric aggregation and mapping functions with no database access.
- [ ] Run the focused tests again and verify they pass.

### Task 2: Forward migration and SQL contract

**Files:** Create `supabase/migrations/20260916000500_mlit_transactions.sql`, Test `tests/sql/test_mlit_transactions.sql`.

- [ ] Add the table, source FK, numeric/date checks, unique source/content key, indexes, RLS, authenticated SELECT policy, and service-role grants.
- [ ] Add SQL assertions for columns, constraints, indexes, RLS, and four-role access.
- [ ] Run the SQL contract against the disposable Supabase database and record output.

### Task 3: Real MLIT importer

**Files:** Create `scripts/import_mlit_transactions.py`, Test `tests/unit/test_import_mlit_transactions.py`.

- [ ] Write fixture-based tests for official JSON/base64 ZIP decoding, Japanese CSV field normalization, quarter parsing, and idempotent conflict keys.
- [ ] Implement environment-configured MLIT download URL/key, bounded logs, `--prefecture --year --dry-run`, and asyncpg batch upsert.
- [ ] Download the actual latest four quarters for Tokyo, Osaka, and Niigata into a temporary raw-data directory and import only into a disposable local database.
- [ ] Run the same import twice and capture row counts and period distribution.

### Task 4: Organization-scoped FastAPI endpoint

**Files:** Create `backend/app/region_stats_routes.py`, Modify `backend/app/main.py`, Test `tests/api/test_region_stats_routes.py`.

- [ ] Write failing tests for member read, non-member/organization-outside denial, sample insufficiency, real response metadata, and rent-sale unavailability.
- [ ] Implement `GET /api/org/region-stats` with validated filters and database-side numeric row retrieval followed by pure aggregation.
- [ ] Register the router and run focused API tests with the required Python interpreter.

### Task 5: B-side localized UI and browser coverage

**Files:** Modify `web/data-query.html`, `web/app.js`, `web/business.css`, `web/js/i18n.js`; Test `tests/web/region-stats.spec.js`.

- [ ] Add the region-stat form/result panel with visible source/license/limitations and rent-sale placeholder.
- [ ] Add zh-CN, zh-Hant conversion-chain source, ja, and en strings plus loading/empty/error/forbidden states.
- [ ] Add Playwright coverage for all states and absence of internal enum/error-code text.
- [ ] Run `npm run test:web -- --workers=1` and capture output.

### Task 6: CI and final evidence

**Files:** Modify `.github/workflows/release-gate.yml`, Create `tests/architecture/test_mlit_region_stats_contract.py`, Create `/tmp/zouseeking-mb4-details.md`.

- [ ] Add both required CI check names for the SQL contract and importer/endpoint tests, preserving existing checks.
- [ ] Validate workflow YAML locally and run `git diff --check`.
- [ ] Run the full required Python and web commands, compile/syntax checks, and local disposable end-to-end import.
- [ ] Write the detailed report with actual URLs/parameters, raw response format, counts, distributions, response JSON, psql recomputation query, permissions, UI output, and limitations.
