# Migration Ledger Final Check — 2026-09-30 (G4 migration dimension, D-7)

## Why this unit

The 2026-09-30 countdown row (D-7) is `C05` (production four-identity re-verification)
plus the G4 final check on migrations / RLS / quota / logs. The four-identity part, the
live ledger read, and the staging re-verification all need staging or production
credentials that this autonomous shift must not use, and the quota dimension was already
delivered offline on 2026-09-28. The first remaining dimension that can be closed
**offline** is the migration dimension, so this shift closes it statically.

## Scope checked

`scripts/check_migration_ledger_offline.py` walks the canonical history
`supabase/migrations` and checks seven things:

| Check | What it proves |
|---|---|
| C1 | Every migration filename is `<14-digit version>_<slug>.sql`, versions are unique, and the history is in ascending version order (no back-dated insert, no duplicate timestamp). |
| C2 | `docs/architecture/schema-ownership.json` lists exactly the files on disk, in the append-only canonical order, and declares the same canonical history. |
| C3 | Every already-applied migration still hashes to the SHA-256 pinned in the contract — an in-place edit of an applied migration fails here. A new migration without a pin fails here too. |
| C4 | The two migrations whose SHA-256 was recorded on the production line (`docs/release/m1-database-production-line-evidence.json`) still match both the recorded value and the pin. |
| C5 | The current documents that claim a zero-gap ledger (readiness summary §1, checklist §A row A1) still bind to the repository: exactly one claim occurrence each, `production == repo == 54`, `max_version == 20260923000300`. |
| C6 | Destructive SQL keywords (drop table / drop column / drop schema / drop type / drop constraint / truncate / delete from / alter column … type) appear only in the registered `(file, kind, count)` triples. A new destructive statement, a changed count, or a stale registration fails. |
| C7 | The contract itself is well-formed: required keys, compiles, named regex groups, repo-relative paths, valid binding targets, declared destructive kinds. |

It does **not** check whether a runtime request reaches anything, database atomicity,
concurrency, the real `supabase_migrations.schema_migrations` contents, or whether the
54/54 claim is still true in production. The gate reads no network, no socket, no
environment variable and no credential, never executes SQL, and never writes to the
repository. It is not wired into CI (the new unit tests are already covered by the
existing `python-pytest` job); this shift did not touch `.github/workflows/release-gate.yml`.

## Required self-check commands

### `python3 scripts/check_migration_ledger_offline.py`

Raw output:

```text
PASS C1 filename and version integrity
PASS C2 ownership manifest matches the canonical history
PASS C3 pinned sha256 for every applied migration
PASS C4 recorded production-line hashes still match
PASS C5 current zero-gap ledger claims match the repository
PASS C6 destructive statements are registered
PASS C7 contract structure
```

`--json` → `{"status": "pass", "errors": []}` (exit `0`).

### `python3 scripts/check_migration_ledger_offline.py --print-pins`

Prints the 54-entry `pinned_hashes` block that must be extended in the same change that
adds a forward migration (the command is read-only; it does not rewrite the contract).

### `backend/.venv/bin/python -m pytest tests/unit/test_migration_ledger_offline.py -q`

```text
18 passed
```

### Regression and offline baseline (this checkout, HEAD `10b9f35`)

```text
backend/.venv/bin/python -m pytest tests/unit tests/architecture -q  → 667 passed / 91 skipped
    (baseline from the 2026-09-29 shift on this checkout: 649 passed / 91 skipped; delta = +18 new tests, zero regression)
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src → OK
node --check web/app.js                                 → OK
backend/.venv/bin/python -m pip check                    → No broken requirements found.
python3 scripts/check_schema_ownership.py                → schema_ownership_status=pass (exit 0)
python3 scripts/check_quota_enforcement_offline.py       → exit 0
python3 scripts/check_release_status_consistency.py      → status: open, undeclared drift 0 (exit 2, only RS1)
backend/.venv/bin/python scripts/ci/check_release_policy.py → PASS
git status --porcelain / git diff --check                → only the 4 new files below; --check clean
```

## Outside-the-repository mutation probes

A copy of the canonical history, the ownership manifest, the new contract and the two
bound documents was placed in `/tmp/migration-ledger-probe` (working tree untouched) and
mutated six ways. Every mutation failed as intended; the unmutated copy passed.

```text
unmutated_copy           -> exit 0 | {"status": "pass", "errors": []}
edit_applied_file        -> exit 1 | '20260923000300_shared_rate_limits.sql: sha256 drift' present=True
add_unpinned_migration   -> exit 1 | '20260930000100_x.sql has no pinned sha256' present=True
stale_ledger_claim       -> exit 1 | 'L1_go_live_readiness_summary: repo=' present=True
recorded_hash_tamper     -> exit 1 | 'm1_baseline_reconciliation_apply' present=True
unregistered_drop        -> exit 1 | 'drop_table appears 1 time(s), registered 0' present=True
ALL_PROBES_OK
```

`tests/unit/test_migration_ledger_offline.py` additionally covers these mutations plus
duplicate versions, malformed filenames, manifest reordering, manifest canonical-history
drift, checklist max-version drift, a duplicated claim, destructive count drift, a stale
registration, comment-only keywords, contract-structure breakage, and the CLI exit codes.

## Verified facts recorded while delivering this gate

- `supabase/migrations/*.sql` = **54** files, all matching the name pattern, all pinned,
  highest version `20260923000300`, and identical to the ownership manifest in both
  membership and order.
- The two recorded production-line hashes match on disk byte for byte
  (`20260902000100` → `77c22925…`, `20260902000200` → `d6872949…`).
- Registered destructive statements: 8 files each with one `drop constraint`, plus
  `20260905000500` `truncate` (audit-events append-only trigger text) and
  `20260923000100` `delete from` (invite exception entry). No `drop table`, `drop column`,
  `drop schema`, `drop type`, or `alter column … type` anywhere in the canonical history.

## Honest limits

- Byte-level hashing assumes line endings survive checkout. The repository has no
  `.gitattributes` for `*.sql`; a checkout that normalizes CRLF would report C3 drift.
- C5 binds the documents to the repository, not to production. If a forward migration is
  applied to production without updating the two claim sites, the gate turns red — that is
  the intended prompt to re-read the live ledger and update the claim, not a production
  check.
- The dated evidence blocks (`go-no-go-checklist` §D reading `50 条`, `launch-readiness-log`
  rows) are deliberately out of scope and are listed in the contract's `excluded_surfaces`;
  they are measurements of an earlier round, and this gate does not rewrite them. Note that
  checklist §D still carries the pre-forward-batch snapshot (`50 条`, highest
  `20260922000100`) while §A row A1 carries the 09-27 measurement (54/54, highest
  `20260923000300`). The contradiction is a documentation-hygiene item for the owner of the
  checklist, not a machine-state drift, and was not changed here.
- C6 is a comment-stripped keyword scan, not a SQL parser: it cannot tell a top-level
  `truncate` from one nested in a function body, by design — both are destructive and both
  must be registered.

## Files in this delivery

| File | Role |
|---|---|
| `docs/architecture/migration-ledger-contract.json` | Contract: canonical history, name pattern, 54 pinned SHA-256 values, recorded production-line artifacts, two live ledger claims with bindings, declared + registered destructive statements, excluded surfaces. |
| `scripts/check_migration_ledger_offline.py` | Pure-standard-library offline guard (C1–C7, `--json`, `--print-pins`), exit `0` consistent / `1` drift. |
| `tests/unit/test_migration_ledger_offline.py` | 18 tests: real repository passes, plus mutation and CLI coverage. |
| `docs/release/migration-ledger-final-check-2026-09-30.md` | This evidence record. |

## Still open after this shift

| Item | State |
|---|---|
| D-9 (09-28) C13 staging smoke | Blocked: needs `SMOKE_ANON_KEY` / `SMOKE_OWNER_TOKEN` / `SMOKE_OTHER_TOKEN` plus a one-off staging write authorization. |
| D-8 (09-29) provider backup/PITR + Storage restore | Blocked: needs provider-level authorization and a downtime window. |
| D-7 (09-30) C05 production four-identity re-check | Blocked: needs staging/production credentials. Migration dimension now closed offline; RLS and log dimensions remain. |
| D-6 (10-01) open-registration review | Offline half delivered; real rate-limit / enumeration / email-confirmation measurement still needs the same staging authorization. |
| D-5 (10-02) legal wording | Gate delivered; O1/O2/O3 site-vs-legal-text blockers await the user's wording decision. |
