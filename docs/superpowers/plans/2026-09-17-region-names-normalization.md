# MLIT Japanese Region Names Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize all MLIT prefecture/municipality names into the exact frontend vocabulary, import them safely, repair existing rows, and prove zero unmapped names for the required fixtures.

**Architecture:** `backend/app/region_names.py` owns vocabulary loading, bidirectional character folding, explicit exceptions, prefecture/city/ward validation, and mapping counters. The importer calls it for both API and CSV rows, retains Japanese source values in `raw`, and performs a conflict update only when tracked values differ. Tests use deterministic vocabulary-driven cases and a disposable loopback PostgreSQL database.

**Tech Stack:** Python 3.9+, asyncpg, pytest/pytest-asyncio, PostgreSQL, JSON vocabulary.

**Spec:** `/tmp/zouseeking-region-names-task.md` (version 2)

## Global Constraints

- Use `backend/.venv/bin/python` and `PYTHONPATH=<repo root>` for scripts/tests.
- Never connect to production, commit, push, deploy, SSH, or print credentials.
- Target values must be members of `web/field-options.json` and raw Japanese values stay in `raw`.
- Unknown names return `None`, are counted with original samples, and are never guessed.
- Required validation commands must run for real; unavailable items are reported as `NOT_EXECUTED`.

### Task 1: Add vocabulary normalization contract

**Files:**
- Create: `backend/app/region_names.py`
- Test: `tests/unit/test_region_names.py`

- [ ] Write table-driven tests for all 47 prefectures, every Niigata city including county-prefix and ward forms, Tokyo’s 62 entries, Osaka’s 43 entries, folding, and an unmapped original sample.
- [ ] Run the new unit test and observe the expected failure because the module is absent.
- [ ] Implement exact vocabulary loading, shared folding, explicit overrides, county-prefix retry, generic ward splitting, and report counters.
- [ ] Run the focused unit test to green.

### Task 2: Apply normalization and auditable upserts

**Files:**
- Modify: `scripts/import_mlit_transactions.py`
- Test: `tests/unit/test_import_mlit_transactions.py`

- [ ] Add importer tests asserting canonical fields, raw Japanese preservation, unmapped summaries, and update SQL behavior.
- [ ] Run those tests red.
- [ ] Route both row shapes through `map_region_names`, reject unmapped regions, and return separate counters.
- [ ] Replace conflict no-op with `is distinct from` guarded update and count inserted/updated/skipped plus unmapped counters.
- [ ] Run focused and existing unit tests green.

### Task 3: Make the PostgreSQL integration non-skipping and prove repair/idempotency

**Files:**
- Modify: `tests/integration/test_mlit_xit001_import.py`
- Modify: `tests/support/pg_bootstrap.py` only if local discovery needs a reusable loopback helper

- [ ] Add XIT001-shaped Niigata county/ward samples and assertions for canonical prefecture/city/ward values, zero Japanese-prefecture rows, zero vocabulary violations, and in-place repair.
- [ ] Run the integration test against the repository’s local PostgreSQL; if `DATABASE_URL` is absent, start a disposable loopback server/database and set it for the command.
- [ ] Run all required existing unit/integration tests and record exact output.

### Task 4: Final verification and report

**Files:**
- Create: `/tmp/zouseeking-region-names-details.md`

- [ ] Run compile, focused tests, existing tests, and `git diff --check`.
- [ ] Verify no production URL is used and collect unmapped samples (expected only the deliberate synthetic unknown, if any).
- [ ] Write every command, real output, changed file, unmapped list, and `NOT_EXECUTED` item to the detailed report.

