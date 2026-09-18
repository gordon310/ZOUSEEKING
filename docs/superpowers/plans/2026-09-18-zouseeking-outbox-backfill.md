# Zouseeking Content Backfill and Report Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill all published content-library location/type fields through the owning generator and move report generation to one durable PostgreSQL outbox worker with atomic claims, idempotency, bounded retry, and local real-database concurrency evidence.

**Architecture:** Treat `data/content_library.json` as the generated canonical library and `scripts/generate_xhs_package.py` as the only writer, adding a required structured-location guard and regenerating the three legacy records from corrected configs. Add an additive `report_generation_outbox` table and enqueue it transactionally with `queries`/`generation_jobs`; FastAPI only enqueues, while a single `backend.app.report_worker` implementation claims and executes jobs. Reuse the existing market-report engine and safe public error mapping, with retry classification and terminal/replay state transitions in the worker.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, PostgreSQL/Supabase SQL migrations, pytest/pytest-asyncio, Playwright Chromium, Node test runner.

**Spec:** `/tmp/zouseeking-outbox-backfill-task.md`

## Global Constraints

- Do not edit generated `web/content-library.json` directly; regenerate it from `data/content_library.json` through `scripts/generate_xhs_package.py`.
- Add schema only through a new forward migration; update the bare filename manifest and migration-count baseline.
- Do not commit, push, deploy, connect to staging/production, or use live credentials.
- Preserve public job statuses/messages and never expose raw exception strings.
- Use atomic database claims, idempotent completion, bounded retries, classified failures, and post-commit side effects.
- Run every required backend, worker, frontend, schema, and content-library verification command and capture raw output in `/tmp/zouseeking-outbox-backfill-details.md`.

### Task 1: Content-library source backfill and generator guard

**Files:**
- Modify: `configs/jphouse_worker/*.json` for the three legacy records
- Modify: `scripts/generate_xhs_package.py`
- Test: `tests/unit/test_generate_xhs_package.py`
- Test: `tests/unit/test_content_library_contract.py`

- [ ] Write failing tests for valid structured location/type output and rejection of missing location fields.
- [ ] Run focused tests and record the expected failure.
- [ ] Correct only the three source configs using values present in `web/field-options.json` (`新潟县/新潟市/未細分`, `大阪府/大阪市/生野区`, `东京都/东京23区/港区`) and canonical asset types.
- [ ] Add generator validation before writing either library copy.
- [ ] Regenerate the three records with the existing generator and assert canonical/web byte equality.
- [ ] Run focused tests and the six-record vocabulary verification.

### Task 2: Durable outbox schema and contract tests

**Files:**
- Create: `supabase/migrations/20260918000400_report_generation_outbox.sql`
- Modify: `docs/architecture/schema-ownership.json`
- Modify: `supabase/migrations/README.md`
- Test: `tests/sql/test_report_generation_outbox_schema.sql`
- Test: `tests/architecture/test_schema_ownership_audit.py`

- [ ] Write the additive schema assertion before the migration and run it RED.
- [ ] Add an owner-independent service-worker outbox table with unique idempotency key, pending/running/retryable/completed/failed states, attempt counters, next-attempt time, claim lease, safe error code, and payload/query foreign keys.
- [ ] Add indexes and service-role-only write grants without broad member writes.
- [ ] Register the bare migration filename and increment the manifest baseline from 43 to 44.
- [ ] Run static migration/ownership assertions.

### Task 3: One report worker and API enqueue path

**Files:**
- Create: `backend/app/report_worker.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routes/intake.py`
- Delete: `scripts/run_jphouse_worker.py`
- Modify: `docs/architecture/authoritative-boundaries.json`
- Modify: `docs/architecture/adr-0001-authoritative-backend-and-schema.md`
- Modify: `docs/supabase-setup.md`
- Test: `tests/unit/test_report_worker.py`
- Test: `tests/integration/test_report_worker_postgres.py`
- Modify: `tests/api/test_legacy_job_routes.py`

- [ ] Write failing tests for enqueue-only API behavior, atomic claim, retry classification/backoff, idempotent replay, and safe public errors.
- [ ] Run focused tests and record the expected failure.
- [ ] Move the existing report execution logic into the worker module without changing terminal report/status wording.
- [ ] Make `create_or_get_query_job`, intake preview/convert, and legacy run route transactionally enqueue/reset outbox state; remove FastAPI `BackgroundTasks` execution.
- [ ] Implement one worker claim statement using `UPDATE ... WHERE ... RETURNING`, lease recovery, bounded retry, and terminal safe error persistence.
- [ ] Remove the old REST worker implementation and document the removed duplicate path.
- [ ] Run focused unit tests, true local PostgreSQL concurrent claim/replay tests, and API contract tests.

### Task 4: Full verification and evidence report

**Files:**
- Create: `/tmp/zouseeking-outbox-backfill-details.md` (untracked evidence only)

- [ ] Run backend `pytest -q`.
- [ ] Run the new concurrency/idempotency tests and preserve raw output.
- [ ] Run region-stats Playwright spec, complete Chromium suite, and `node --test tests/unit/i18n.test.js`.
- [ ] Run `python3 scripts/check_schema_ownership.py`.
- [ ] Verify generated library fields, vocabulary membership, content-library equality, migration filename/count, and `git diff --stat`.
- [ ] Write command lines plus unedited raw output and a concise conclusion to the required `/tmp` report.
