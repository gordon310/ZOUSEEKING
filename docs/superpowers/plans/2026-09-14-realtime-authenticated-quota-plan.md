# Realtime Authenticated Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all five usage consumers authenticated, idempotent, transactionally quota-metered from live `plan_entitlements`, and prove the behavior with offline, SQL, concurrency, and real HTTP evidence.

**Architecture:** Add one asyncpg quota helper that owns plan resolution, entitlement lookup, quota-row synchronization, locking, idempotency, and consumption. Route all five consumers through it while preserving existing report/query ownership and the frozen schema. Add one forward-only migration only for new required objects, plus a staging evidence runner that accepts secrets only from environment variables.

**Tech Stack:** FastAPI, asyncpg, PostgreSQL/Supabase migrations, Pydantic, pytest/pytest-asyncio, existing HTTP/staging test utilities.

**Spec:** `docs/superpowers/specs/2026-09-14-realtime-authenticated-quota-design.md`

## Global Constraints

- 免费预览端点必须 `require_user` 认证。
- helper 必须在消费事务中实时读取 active `plan_entitlements`，同步 `usage_quotas.limit_units`。
- migration 只允许新增对象；不得修改/删除既有列、约束、策略或数据行。
- 不信任请求体身份；重复稳定 fingerprint 不重复计费；超限 HTTP 429。
- 不写死限额；C+ report 不得出现 `12` 作为运行时限额。
- 密钥只从环境变量读取，不落文件；测试数据自建自清。
- 每个行为先写失败测试并观察失败，再写最小实现。

### Task 1: Add failing contracts for the shared helper

**Files:**
- Create: `tests/unit/test_realtime_quota.py`
- Create: `tests/sql/test_realtime_quota_contract.sql`

**Interfaces:**
- Tests define `consume_current_entitlement(conn, user, metric, period, units, idempotency_key, fingerprint, scope_key=None)`.
- Tests assert `QuotaExceeded`, duplicate outcomes, live limit refresh, day/month buckets, and serialized concurrent consumption.

- [ ] Write tests that first create an entitlement value, consume, change only the entitlement value in the same test database, then consume again and assert the quota row limit follows the new value.
- [ ] Add tests for duplicate fingerprint, distinct A/B user scopes, UTC+8 day/month boundary, and `limit=1` concurrent callers where exactly one consumes.
- [ ] Add SQL assertions that the forward migration is additive and that existing relation columns/constraints/policies remain present.
- [ ] Run `PYTHONPATH=. backend/.venv/bin/pytest tests/unit/test_realtime_quota.py -q` and the SQL contract command; record the expected RED failure before implementation.

### Task 2: Implement the single transactional helper

**Files:**
- Create: `backend/app/usage/quota.py`
- Modify: `backend/app/usage/__init__.py` only if export is needed
- Test: `tests/unit/test_realtime_quota.py`

**Interfaces:**
- Produces `QuotaConsumption` with `status`, `metric`, `period_key`, `used`, `limit`, and `remaining`.
- Raises `QuotaExceeded` without event/idempotency/counter mutation.

- [ ] Resolve `plan_code` from the authenticated profile/audience and active organization path, using existing `plan_for_tier`.
- [ ] Query the active entitlement inside the caller's transaction, lock or create the target quota row, set `limit_units` to the live value, and only then check capacity.
- [ ] Insert event and idempotency records atomically; handle replay before charging; use a stable server fingerprint and no client identity fields.
- [ ] Run the focused helper tests and confirm GREEN, then refactor only while they remain GREEN.

### Task 3: Route query, report, stats, and export through the helper

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/analysis/routes.py`
- Modify: `backend/app/exports/routes.py`
- Modify: `tests/api/test_query_quota_routes.py`
- Modify: `tests/api/test_analysis_routes.py`
- Modify: `tests/api/test_exports_routes.py`

**Interfaces:**
- Query creation consumes `query/month` once per owner/query key before scheduling.
- Report completion consumes `report/month` from the helper; no literal entitlement limit remains.
- Analysis consumes `stats_query/month`; export consumes `export_row/month`.

- [ ] Add failing endpoint/store tests for 429, live entitlement update, duplicate query retry, report entitlement update, stats, export, and A/B scope separation.
- [ ] Replace the independent `_consume_c_plus_report_quota`, `_meter`, and export metering blocks with helper calls inside their existing transactions.
- [ ] Make `POST /api/query` consume only when it creates a new query task; cached/replayed query keys return without another charge.
- [ ] Run the focused endpoint tests; then run `rg -n "values.*12|report.*12|monthly_report_quota|monthly_query_limit|export_rows_monthly" backend/app scripts supabase/functions` and remove runtime quota literals while retaining non-runtime docs/fixtures.

### Task 4: Authenticate and meter free preview idempotently

**Files:**
- Modify: `backend/app/routes/intake.py`
- Modify: `backend/app/intake/repository.py` only where existing owner column is written/read
- Modify: `tests/api/test_intake_routes.py`
- Create: `tests/api/test_free_preview_quota.py`

**Interfaces:**
- `POST /api/intake/sessions/{session_id}/preview` depends on `require_user` and returns the existing `FreePreviewResponse` shape.
- Anonymous requests return 401; same authenticated session/fingerprint replays without extra charge; capacity exhaustion returns 429.

- [ ] Add failing tests for anonymous rejection, authenticated owner success, request-body `username` spoofing, stable replay, and over-limit response body.
- [ ] Add `user_id` to session creation flow from `require_user` while retaining existing frozen fields and session-token authorization.
- [ ] Wrap preview persistence and helper consumption in one transaction or use a repository transaction boundary so a rejected charge cannot leave a new preview.
- [ ] Run the intake-focused tests and confirm RED-to-GREEN evidence.

### Task 5: Add additive migration and migration guardrails

**Files:**
- Create: `supabase/migrations/20260914000200_realtime_authenticated_quota.sql`
- Create: `tests/sql/test_realtime_quota_migration_additive.sql`
- Modify: `supabase/migrations/README.md` if required by existing convention

**Interfaces:**
- Migration adds only new objects required by the helper and preserves all existing schema objects.

- [ ] Write the migration contract test before migration SQL and run it RED.
- [ ] Add only additive SQL (new index/function/constraint/column if proven necessary); do not use `drop`, `replace`, or alter existing policy/constraint/column.
- [ ] Run SQL static checks and, when staging credentials are available, apply through the reviewed migration workflow and query object inventories before/after.

### Task 6: Build and run real acceptance evidence

**Files:**
- Create: `scripts/staging_realtime_quota_acceptance.py`
- Create: `docs/superpowers/reports/2026-09-14-realtime-authenticated-quota-task-report.md`

**Interfaces:**
- Script reads `RLS_TEST_BASE_URL`, `RLS_TEST_ANON_KEY`, service/admin credentials, and test user credentials only from environment variables; it redacts tokens.
- Report records exact commands and actual outputs, including complete JSON responses for two entitlement values and actual 429 response.

- [ ] Add script tests for redaction, response capture, and concurrency result accounting.
- [ ] Run staging SQL/API acceptance when credentials exist; capture before/after entitlement rows, two full API responses, 429 status/body, concurrency counts, day/month rollovers, A/B isolation, anonymous rejection, and spoofed body identity.
- [ ] If credentials are unavailable, execute all offline/SQL-contract tests and explicitly report each unexecuted real-staging command and reason.

### Task 7: Full verification and handoff

**Files:**
- Modify: `docs/superpowers/reports/2026-09-14-realtime-authenticated-quota-task-report.md`

- [ ] Run `PYTHONPATH=. backend/.venv/bin/pytest -q` and record exact pass/skip/fail counts, comparing against the stated 487/83 baseline without silently substituting a different collection.
- [ ] Run `PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache backend/.venv/bin/python -m compileall -q backend scripts src`.
- [ ] Run `node --check web/app.js` and `git diff --check`.
- [ ] Inspect `git diff` and `git status --short` to verify unrelated pre-existing changes were preserved and no secrets or test rows were committed.

