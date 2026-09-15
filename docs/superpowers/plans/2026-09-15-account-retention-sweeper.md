# Account Retention Sweeper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, idempotent retention job that verifies completed account deletions and records backup expiry without violating the `auth.users` or append-only `usage_events` boundaries.

**Architecture:** `scripts/account_retention_sweeper.py` exposes timezone-safe pure planning helpers and an async database runner. The runner claims at most `--limit` completed ledger rows with `FOR UPDATE SKIP LOCKED`, verifies the already-applied deletion contract, and conditionally writes only `backup_expired_at` in a per-row transaction. Dry-run performs no writes and all output is aggregate/stable-code JSON without PII.

**Tech Stack:** Python 3.12, asyncio, asyncpg, argparse, pytest, PostgreSQL/Supabase SQL migrations.

**Spec:** `/tmp/zouseeking-retention-task.md`

## Global Constraints

- Never update or delete `public.usage_events`.
- Never hard-delete `auth.users`.
- Process no more than `--limit` rows per invocation; default 50.
- `--dry-run` must not write.
- Each row failure must not abort other rows.
- Logs and JSON output must not contain email, name, token, raw payload, or user identifiers.
- Schema evolution is additive through a new forward migration only.
- No commit, push, deployment, SSH, live database mutation, or destructive action.

### Task 1: Add failing pure-logic retention tests

**Files:**
- Create: `tests/unit/test_account_retention_sweeper.py`
- Test: `scripts/account_retention_sweeper.py`

**Interfaces:**
- `is_due(due_at: datetime | None, now: datetime) -> bool`
- `validate_limit(limit: int) -> int`
- `plan_retention_actions(row: Mapping[str, Any], now: datetime) -> tuple[str, ...]`
- `run_planned_actions(rows: Iterable[Mapping[str, Any]], now: datetime, limit: int, dry_run: bool, record_backup_expiry: Callable[[Mapping[str, Any]], None]) -> SweepSummary`

- [ ] Write tests for due/not-due timezone-aware values, limit validation, dry-run no-write, and repeated backup-expiry runs producing one callback.
- [ ] Run `PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit/test_account_retention_sweeper.py -q` and observe the expected import failure.

### Task 2: Implement the pure logic and CLI/DB runner

**Files:**
- Create: `scripts/account_retention_sweeper.py`
- Test: `tests/unit/test_account_retention_sweeper.py`

**Interfaces:**
- `sweep_account_retention(pool: Any, *, now: datetime, limit: int = 50, dry_run: bool = False) -> SweepSummary`
- CLI: `python3 scripts/account_retention_sweeper.py [--limit N] [--dry-run] [--now ISO]`

- [ ] Implement minimal helpers to make Task 1 green.
- [ ] Add candidate selection for `status='completed'` and due primary/backup deadlines, bounded with `FOR UPDATE SKIP LOCKED`.
- [ ] Verify only the existing anonymization contract: blank profile values, no owner query/export/session/org-membership/quota rows, and retained reports have no owner/query link; never write those tables from the sweeper.
- [ ] Record `backup_expired_at` only when due and null, in the same per-row transaction; dry-run only reports planned actions.
- [ ] Catch and aggregate per-row failures with stable codes; do not print identifiers or exception text.
- [ ] Run focused tests and CLI `--help`/invalid-limit checks.

### Task 3: Add additive migration and SQL assertions

**Files:**
- Create: `supabase/migrations/20260915000400_account_retention_sweeper.sql`
- Create: `tests/sql/test_account_retention_sweeper.sql`
- Modify: `docs/architecture/schema-ownership.json`
- Modify: `tests/architecture/test_schema_ownership_audit.py`
- Modify: `tests/sql/test_m1_reconciliation_contract.sql` only if live disposable counts change

- [ ] Add nullable `backup_expired_at timestamptz` and a due/expiry index without changing or removing existing columns, grants, policies, or triggers.
- [ ] Assert the column, additive migration ledger, index, and absence of write grants for anon/authenticated.
- [ ] Update the canonical migration list and exact expected count from 34 to 35.
- [ ] Run the schema ownership audit and the SQL assertion against disposable Supabase if available.

### Task 4: Integrate CI and document operational behavior

**Files:**
- Modify: `.github/workflows/release-gate.yml`
- Modify: `tests/architecture/test_release_gate_contract.py`
- Modify: `tests/unit/test_release_evidence.py` only if a duplicated required-check fixture needs the new name
- Modify: `docs/data-dictionary.md`
- Modify: `docs/legal/privacy-operations-runbook.md`
- Modify: `supabase/migrations/README.md`

- [ ] Register the new SQL assertion in the SQL job and both required-check lists/baselines.
- [ ] Document that primary expiry is verification-only after controlled deletion, backup expiry records the fact but does not mutate provider backups, and the job remains unexecuted against live systems in this task.
- [ ] Run all relevant Python tests, compileall, pip check, schema audit, and offline policy checks.

### Task 5: Produce the required evidence report

**Files:**
- Create/overwrite: `/tmp/zouseeking-retention-details.md`

- [ ] Record changed files, migration/column details, exact focused and full test output, SQL result or blocked reason, CI registration, unexecuted items, risks, and explicit no-commit/no-push/no-deploy status.
- [ ] Re-check `git status`, `git diff --check`, and forbidden operations before final response.
