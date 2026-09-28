# Quota Enforcement Final Check — 2026-09-28

## Scope checked

The offline guard checks seven registered quota call sites, nine registered
call edges, modules importing `consume_current_entitlement`, the contract
metric set against `METER_MAP`, and contract structure.

It does not check whether a runtime request actually reaches a call site,
database atomicity or concurrent behavior, real staging or production quota
consumption, migration ledgers, or the line numbers cited in `AGENTS.md`. The
guard intentionally does not depend on line numbers.

This check did not connect to production, use credentials, write to a database
or object store, or deploy anything.

## Required self-check commands

### `python3 scripts/check_quota_enforcement_offline.py`

Raw output:

```text
PASS C1 query-create
PASS C1 c-plus-report
PASS C1 analysis-meter
PASS C1 personal-export
PASS C1 org-export
PASS C1 region-stats
PASS C1 intake-preview
PASS C2 edge-query-route
PASS C2 edge-report-job
PASS C2 edge-analysis-route
PASS C2 edge-personal-export-route
PASS C2 edge-org-export-route
PASS C2 edge-region-stats-get
PASS C2 edge-region-stats-trend
PASS C2 edge-intake-preview-depends
PASS C2 edge-intake-convert-depends
PASS C3 module coverage
PASS C4 metric set
PASS C5 contract structure
```

Conclusion: passed.

### `python3 scripts/check_quota_enforcement_offline.py --json`

Raw output:

```json
{"status": "PASS", "errors": [], "checks": ["C1 query-create", "C1 c-plus-report", "C1 analysis-meter", "C1 personal-export", "C1 org-export", "C1 region-stats", "C1 intake-preview", "C2 edge-query-route", "C2 edge-report-job", "C2 edge-analysis-route", "C2 edge-personal-export-route", "C2 edge-org-export-route", "C2 edge-region-stats-get", "C2 edge-region-stats-trend", "C2 edge-intake-preview-depends", "C2 edge-intake-convert-depends", "C3 module coverage", "C4 metric set", "C5 contract structure"]}
```

Conclusion: passed.

### `python3 -m pytest tests/unit/test_quota_enforcement_offline.py -q`

Raw output:

```text
/opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest
```

Conclusion: not passed because the invoked `python3` environment does not
provide pytest.

### `python3 -m compileall -q scripts`

Raw output:

```text
```

Conclusion: passed (exit status 0 with no output).

## Supplemental offline unit-test evidence

Command:

```text
backend/.venv/bin/python -m pytest tests/unit/test_quota_enforcement_offline.py -q
```

Raw output:

```text
........                                                                 [100%]
8 passed in 0.66s
```

Conclusion: passed using the repository virtual environment. The tests cover
the real repository and all seven required mutations through `check_repo`.

## Independent acceptance (Hermes, 2026-09-28 night shift)

Evidence collected by the reviewer, not reported by the implementing session:

| Check | Command | Result |
| --- | --- | --- |
| Guard, human output | `python3 scripts/check_quota_enforcement_offline.py` | 19/19 `PASS`, exit 0 |
| Guard, machine output | `python3 scripts/check_quota_enforcement_offline.py --json` | `{"status": "PASS", "errors": []}` |
| New unit tests | `PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit/test_quota_enforcement_offline.py -q` | `8 passed` |
| Regression | `PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit tests/architecture -q` | `597 passed, 91 skipped` (baseline 589 + 8, zero regression) |
| Interpreter portability (CI runs 3.12) | guard executed under CPython 3.14.7 / 3.11.16 / 3.9.6 | exit 0 on all three |
| Contract fidelity | on-disk JSON vs the dispatched contract block | byte-identical |
| Repo hygiene | `git status --porcelain`, `git diff --check` | only the four new files; no modifications, no whitespace errors |

Independent mutation probes (nine, run against an out-of-repo copy so the
working tree was never mutated): unmutated copy passes; contract metric
drift, source metric drift, removed entitlement call, unregistered importer
module, removed direct-call edge, metric outside `METER_MAP`, duplicate
contract id, and removed `Depends` provider binding each failed with the
expected coordinate named. The guard therefore rejects each class of
regression it claims to reject.

Coverage caveat confirmed by the reviewer: the new unit test is executed by
the existing `python-pytest` release-gate job (`python -m pytest -q`), so no
workflow edit was needed; the guard script is a repository tool, not a
separately recorded gate check. As before, this evidence proves static
structure only — it does not prove runtime execution, database atomicity,
concurrency, or real staging/production quota consumption.
