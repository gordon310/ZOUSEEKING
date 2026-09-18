# Rent Source Key Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the typoed 122-5 rent reference source key to `estat_housing_land_122_5` through a forward migration and all repository consumers.

**Architecture:** Preserve the canonical Supabase migration history by adding one idempotent forward migration that updates only the typoed key and documents the reason. Keep the importer, backend response path, browser contract, integration fixtures, ownership manifest, and migration-count assertion aligned with the new canonical key.

**Tech Stack:** PostgreSQL/Supabase migrations, Python importer and backend, pytest/unittest, Playwright Chromium, repository ownership audit.

**Spec:** `/tmp/zouseeking-srckey-task.md`

## Global Constraints

- Do not edit existing migrations; add one forward migration only.
- Do not commit, push, deploy, SSH, or touch online databases/environments.
- Use only a disposable local database for migration/import/API verification.
- The old key may remain only in the new migration's `UPDATE` statement.
- Run the complete requested verification and write real output to `/tmp/zouseeking-srckey-details.md`.

### Task 1: Establish red contract tests

**Files:**
- Modify: `tests/unit/test_import_rent_reference.py`
- Modify: `tests/integration/test_region_stats_postgres.py`
- Modify: `tests/web/region-stats.spec.js`
- Modify: `tests/architecture/test_schema_ownership_audit.py`

- [ ] Update expected source keys and migration count to the requested target values.
- [ ] Run focused tests and record the expected failures caused by the unchanged implementation.

### Task 2: Implement the rename and migration ledger updates

**Files:**
- Create: `supabase/migrations/20260918000300_rent_reference_source_key_alignment.sql`
- Modify: `scripts/import_rent_reference.py`
- Modify: `backend/app/region_stats_routes.py`
- Modify: `docs/architecture/schema-ownership.json`

- [ ] Change every importer source selector/constant/reference and backend constant to `estat_housing_land_122_5`.
- [ ] Add the exact forward update plus a column comment documenting the typo correction.
- [ ] Register the bare migration filename and make the architecture baseline 43.
- [ ] Run focused tests and repository grep/audit checks.

### Task 3: Verify disposable local database behavior

**Files:**
- Evidence only: `/tmp/zouseeking-srckey-details.md`

- [ ] Reset a disposable local Supabase database and apply all migrations.
- [ ] Import 122-5 fixture/data twice and verify second-run `inserted=0`.
- [ ] Verify an old-key row migrates with equal row counts, no old rows, no unique-key collision, and repeated migration/import is harmless.
- [ ] Verify the region-stats API returns the database value rather than a hard-coded key.

### Task 4: Run complete verification and capture evidence

- [ ] Run i18n, region-stats, Chromium, backend, schema audit, syntax/compile, and repository checks available in this checkout.
- [ ] Capture `git diff --stat`, migration contents, before/after counts, and test tail lines in `/tmp/zouseeking-srckey-details.md`.
