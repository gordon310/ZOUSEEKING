# Rent Reference Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:verification-before-completion. This plan is executed locally only; do not commit, deploy, or use a non-loopback database.

**Goal:** Add database-backed official rent references and gross rent-to-price ratio data to the organization regional-statistics page.

**Architecture:** Add one additive Supabase migration for `public.rent_reference_stats`; parse the two official e-Stat XLSX files in a reusable import script, normalize names through `backend.app.region_names`, and upsert through a temporary table/COPY path. Extend `DbRegionStatsStore` with municipality-to-prefecture fallback queries and render the response through four-language UI copy without numeric fallbacks.

**Tech Stack:** PostgreSQL/Supabase SQL migrations, Python 3 + asyncpg + openpyxl, FastAPI, vanilla JavaScript, Playwright, Node test runner.

**Spec:** `/tmp/zouseeking-rent-ref-task.md`

## Global Constraints

- All numeric rent and ratio values come from `public.rent_reference_stats`; no hard-coded production values.
- Only a new forward migration may change the schema.
- Only loopback disposable PostgreSQL may be used for verification.
- Region names must pass through `backend.app.region_names` and match the existing frontend vocabulary; the special Tokyo 23-ward aggregate is stored as `东京都 / 东京23区 / __not_subdivided__`.
- Official e-Stat attribution must include the source URL and “加工して作成”.
- Missing `-`/blank values are skipped, never converted to zero or a valid NULL observation.

### Task 1: Contract tests and migration

Create failing SQL/API tests for the additive table, constraints, RLS, response keys, municipality fallback, and ratio formula; add `supabase/migrations/20260918000100_rent_reference_stats.sql`.

### Task 2: XLSX parser and idempotent importer

Create failing parser tests for both official workbook layouts, cross-check values, skipped markers, Tokyo aggregate mapping, and two-run upsert counts; implement `scripts/import_rent_reference.py` and add `openpyxl` to backend requirements.

### Task 3: API integration

Extend the database store to query municipality then prefecture references, monthly city references, and compute the gross ratio from the stored rent and existing mean unit price. Add real local-Postgres coverage including an update-then-reread assertion.

### Task 4: Four-language UI and browser tests

Add complete `regionStats` translations and safe rendering for available, monthly, prefecture-fallback, and unavailable states. Update the region-stat Playwright spec and preserve the e-Stat attribution text.

### Task 5: Full local verification and report

Run migrations/import/tests against one disposable loopback database, capture raw tails and before/after API JSON, run the full Chromium suite and required Node test, compute `git diff --stat`, and write `/tmp/zouseeking-rent-ref-details.md`.
