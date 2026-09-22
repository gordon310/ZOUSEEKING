# Multi-month Regional Trend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a quota-metered, provenance-complete multi-quarter regional price series and render it accessibly in the statistics panel.

**Architecture:** Add a dedicated `/api/org/region-stats/trend` endpoint and store method so the single-period contract stays stable. The store groups exact MLIT rows by parsed `YYYYQn`, derives every accepted period through the existing numeric aggregator and provenance builder, and reports excluded periods rather than inventing values. The existing statistics panel requests that endpoint when its new trend mode is selected and renders a textual summary plus a semantic table.

**Tech Stack:** FastAPI, asyncpg/PostgreSQL, existing quota ledger, vanilla JavaScript/i18n, Playwright, pytest.

**Spec:** `/Users/gordonmac/zouseeking-cron-tasks/2026-09-20-multi-month-trend.md`

## Global Constraints

- A trend contains at least two comparable accepted periods; never interpolate absent periods.
- Each accepted period must include all 12 fields from `REQUIRED_STATISTIC_FIELDS`.
- Period ordering parses year and quarter numerically, not lexicographically.
- The trend route must retain active-organization authorization and consume the `stats_query` entitlement transactionally.
- Fixtures are explicit `synthetic_fixture` test data and the local PostgreSQL stack only; do not touch production.
- UI copy uses `uiText`/`formatUiText` and has `zh-CN`, `zh-Hant`, `en`, and `ja` entries.
- No commit, push, deployment, or SSH action is allowed.

---

### Task 1: Pure trend construction

**Files:**
- Modify: `backend/app/region_stats.py`
- Test: `tests/unit/test_region_stats.py`

**Interfaces:**
- Produces: `parse_trade_quarter(period: str) -> tuple[int, int] | None` and `aggregate_region_trend_rows(rows, *, asset_type) -> dict[str, Any]`.
- Consumes: `aggregate_region_rows` and `MIN_SAMPLE_SIZE`.

- [ ] Write tests for cross-year numeric ordering, excluded under-sampled periods, two-period qualification, and a one-period `insufficient_periods` result.
- [ ] Run `backend/.venv/bin/python -m pytest tests/unit/test_region_stats.py -q` and observe the missing-function failure.
- [ ] Implement parsing, grouping, and stable `excluded_periods` records with only accepted metric periods in the series.
- [ ] Re-run the focused unit test and confirm it passes.

### Task 2: Provenance-complete, quota-metered API

**Files:**
- Modify: `backend/app/region_stats_routes.py`
- Modify: `tests/api/test_region_stats_routes.py`
- Modify: `tests/integration/test_region_stats_postgres.py`

**Interfaces:**
- Produces: `RegionStatsStore.get_trend(user, prefecture, city, ward, asset_type, from_period, to_period) -> dict[str, Any]` and `GET /api/org/region-stats/trend`.
- Consumes: Task 1 series, `_region_statistic_provenance`, `statistic_provenance`, `assert_statistic_provenance`, and `consume_current_entitlement(metric="stats_query")`.

- [ ] Write route tests for normalized filters, every accepted period's required provenance fields, under-two `insufficient_periods` no-data response, and delegated quota-path use.
- [ ] Run the targeted API test and observe it fail because the trend endpoint is absent.
- [ ] Query candidate rows once, group them with Task 1, compute per-period provenance from only the accepted rows, and validate each period before returning it.
- [ ] In the same database transaction, verify active membership then consume a deterministic request fingerprint through the existing entitlement primitive.
- [ ] Seed explicit local fixture periods and assert an actual routed response has correct chronological order and all provenance fields.
- [ ] Re-run API and integration tests.

### Task 3: Accessible four-language trend panel

**Files:**
- Modify: `web/data-query.html`
- Modify: `web/app.js`
- Modify: `web/js/i18n.js`
- Modify: `tests/unit/i18n.test.js`
- Create: `tests/web/region-stats-trend.spec.js`

**Interfaces:**
- Consumes: trend response `{status, period_count, periods, excluded_periods, comparability, unit, limitations}`.
- Produces: a selected trend mode that requests `/api/org/region-stats/trend`, an `aria-live` textual summary, and a table with period, mean, median, quartile range, sample count, and source.

- [ ] Write the i18n and Playwright tests first; the browser test stubs `**/api/**`, checks summary/table and records console errors.
- [ ] Run the focused browser test and observe the absent control/result failure.
- [ ] Add the mode control, route selection, loading/error/no-data states, and DOM-built escaped table rendering using four-language keys.
- [ ] Run focused i18n and Chromium tests, including the no-data state.

### Task 4: Documentation and full verification

**Files:**
- Modify: `docs/data-dictionary.md`
- Modify: `docs/data-provenance-contract.md`
- Modify: `AGENTS.md`
- Create: `/tmp/zouseeking-trend-details.md`

- [ ] Document endpoint inputs, response shape, comparability/exclusion semantics, and the per-period provenance envelope.
- [ ] Update the AGENTS trend-dataset statement to cite the endpoint and fixture-backed tests while preserving the distinction from a full content-library trend dataset.
- [ ] Run the requested full local pytest command, focused unit/API/browser/i18n commands, syntax checks, and a fixture-backed local response capture.
- [ ] Append raw stdout/stderr and exit statuses verbatim to `/tmp/zouseeking-trend-details.md`, including `git diff --stat`.
