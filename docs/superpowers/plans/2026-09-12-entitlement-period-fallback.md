# Entitlement Period Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix period-aware entitlement fallback and member snapshot overwrites so database-configured day/month limits remain authoritative, while legacy and code defaults are used only under the specified conditions.

**Architecture:** Keep `normalize_entitlements` as the canonical resolver returning `(metric, period)` keys. Add metric-level detection of any active database row, treat zero/NULL legacy values as unconfigured, and make the member response choose a deterministic primary period (day before month) while preserving `limit` and `period`. Update the pricing seed to pass `NULL` for unconfigured legacy columns and provide an unexecuted SQL repair path outside `supabase/`.

**Tech Stack:** Python, asyncpg-facing repository code, pytest, PostgreSQL SQL repair script.

**Spec:** `/tmp/zouseeking-entitlement-fix2-task.md`

## Global Constraints

- Do not modify `supabase/`.
- Do not execute data cleanup.
- Do not run `git commit` or `git push`.
- Do not print secrets.
- Preserve backward-compatible `entitlements.<name>.limit` and `.period` fields.
- Run `PYTHONPATH=. backend/.venv/bin/pytest tests/unit tests/api tests/billing -q` and report exact result.

### Task 1: Establish entitlement resolver regression coverage

**Files:**
- Modify: `tests/unit/test_entitlements.py`

**Interfaces:**
- Consumes: `backend.app.billing.entitlements.entitlement_limit` and `normalize_entitlements`.
- Produces: Failing tests for DB day-only/month-only/both, metric-level legacy fallback, zero legacy unconfigured behavior, and code defaults.

- [x] **Step 1: Write failing tests** for the five resolver cases and assert day wins when both periods exist.
- [x] **Step 2: Run** `PYTHONPATH=. backend/.venv/bin/pytest tests/unit/test_entitlements.py -q` and confirm failures demonstrate current legacy/period behavior.

### Task 2: Implement metric-level fallback and member period priority

**Files:**
- Modify: `backend/app/billing/entitlements.py`
- Modify: `backend/app/member/routes.py`
- Modify: `tests/unit/test_member_read.py`

**Interfaces:**
- Consumes: Task 1 resolver expectations and existing member snapshot contract.
- Produces: Resolver semantics where any active row for a metric blocks legacy fallback for all periods; member snapshots select day as primary when both day/month are resolved and expose optional multi-period data without overwriting the primary.

- [x] **Step 1: Add a member regression test** for day and month rows, asserting day is the returned primary `limit` and `period`.
- [x] **Step 2: Run the focused member test** and confirm it fails because month currently overwrites day.
- [x] **Step 3: Implement the smallest resolver and route changes**; treat `None` and `0` legacy values as unconfigured.
- [x] **Step 4: Run focused entitlement/member tests** and confirm they pass.

### Task 3: Make seed legacy columns nullable-by-semantics and add unexecuted repair path

**Files:**
- Modify: `scripts/seed_pricing_catalog.py`
- Modify: `tests/unit/test_pricing_seed.py`
- Create: `scripts/repair_pricing_legacy_nulls.sql`

**Interfaces:**
- Consumes: `PLANS` entitlement definitions.
- Produces: Idempotent seed parameters using `NULL` for absent monthly entitlements and an operator-run SQL statement that targets only zero legacy values.

- [x] **Step 1: Add a seed test** asserting absent monthly legacy fields are `None` in the plan specification/derived values.
- [x] **Step 2: Run the focused seed test** and confirm it fails against zero-valued legacy derivation.
- [x] **Step 3: Update seed derivation** and add the repair SQL without executing it.
- [x] **Step 4: Run focused seed tests** and inspect the SQL for exact target columns and an idempotent `UPDATE` predicate.

### Task 4: Full verification and handoff evidence

**Files:**
- No additional source files unless a focused test reveals a scoped defect.

- [x] **Step 1: Run** `PYTHONPATH=. backend/.venv/bin/pytest tests/unit tests/api tests/billing -q`.
- [x] **Step 2: Run** `PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src`.
- [x] **Step 3: Run** `git diff --check` and `git status --short`.
- [x] **Step 4: Report** changed files, fallback decision table, repair SQL path/command, test results, and unverified schema constraint risk; do not commit or push.
