# Report job queue contract

## Scope and non-claims

This is the repository contract for durable report-generation queue behavior.
It documents implemented behavior and tests; it is not a production-readiness,
security, statistical-representativeness, or production-exercise statement.
Any production-side claim needs current, separately approved evidence and is
`NEEDS_PROD_EVIDENCE`.

## Single authoritative consumer

The sole report executor is `backend/app/report_worker.py`. The authority is
deliberately narrow: other processes and request threads must not execute a
report.

- A production-source call scan is guarded by
  `test_only_the_report_worker_executes_generation_jobs`: the only call of
  `run_generation_job` is `backend/app/report_worker.py:241`; its definition
  at `backend/app/main.py:624` is not a call.
- `deploy/docker-compose.prod.yml:41-49` defines `report-worker` with
  `command: [python, -m, app.report_worker]`.
- `docs/architecture/authoritative-boundaries.json` records
  `background_execution` as `postgres_job_outbox_single_worker`.

## State machine

| State | Meaning | Writer and condition | Allowed next states |
| --- | --- | --- | --- |
| `pending` | Due, unclaimed work. | Insert/default: `supabase/migrations/20260918000400_report_generation_outbox.sql:8-20`; re-enqueue non-completed row: `backend/app/report_worker.py:75-105`; retry propagation: `backend/app/report_worker.py:155-203`. | `running` |
| `running` | A worker holds a claim lease. | Atomic claim: `backend/app/report_worker.py:47-72`, for due `pending`/`retryable` work or an expired running lease. | `running` (expired lease replay), `retryable`, `completed`, `failed` |
| `retryable` | Safe classified transient failure awaits its due time. | `record_failure`, only when retryable and attempts remain: `backend/app/report_worker.py:155-203`. | `running` |
| `completed` | A claim completed through its matching token. | `complete_claim` conditional update: `backend/app/report_worker.py:127-140`. | `completed` (idempotent re-enqueue preserves it) |
| `failed` | Terminal classified failure. | `record_failure` when permanent or attempts exhausted: `backend/app/report_worker.py:155-203`. | `pending` only through the existing explicit re-enqueue path; otherwise terminal |

The schema vocabulary is constrained by the `check (status in ('pending',
'running', 'retryable', 'completed', 'failed'))` in the migration above.

## Claim contract

`claim_sql()` is one atomic statement (`backend/app/report_worker.py:47-72`):
it selects a candidate with `for update skip locked` and updates that same row
to `running`. It considers only `attempts < max_attempts`. A running row can be
replayed only after a 15 minutes lease condition:
`status='running' and claimed_at < now() - interval '15 minutes'`.

Every claim writes a new `claim_token`. Completion and failure updates require
both the outbox ID and that token, so an older worker cannot finalize a row
after a newer claimant owns it.

## Retry, backoff, and terminal failure

`MAX_ATTEMPTS=3` and `BACKOFF_SECONDS=(5, 30, 300)` are defined at
`backend/app/report_worker.py:24-25`. `classify_failure`
(`backend/app/report_worker.py:147-153`) treats timeout, OS/dependency
connection failures, and `market_source_unavailable` as retryable; other
failures are permanent. `record_failure` then permits retry only while the
claim has attempts remaining.

Only a safe classified code and a redacted public message are stored in
`last_error_code` and `last_error_message`; raw exception text must not be
stored or exposed. The logging contract separately verifies this boundary.

## Idempotency and replay

There are three distinct idempotency boundaries:

1. `idempotency_key text not null unique` in
   `20260918000400_report_generation_outbox.sql` deduplicates a logical queue
   key.
2. `unique (generation_job_id)` makes one job map to one outbox row. The
   `enqueue_report_outbox` `on conflict (generation_job_id)` path is the
   current re-enqueue behavior; it retains `completed` rather than returning it
   to `pending` (`backend/app/report_worker.py:75-105`).
3. `complete_claim` updates only `id=$1 and status='running' and
   claim_token=$2` (`backend/app/report_worker.py:127-140`), protecting a
   replay from a stale claimant.

After a lease expires, a replay receives a new token and can complete, without
creating a second report outbox row. This is demonstrated by
`test_replay_after_lease_expiry_does_not_duplicate_report`.

Known migration/ADR difference: the outbox migration creates the table but
does not backfill historical jobs, while ADR-0001 describes legacy jobs as
being taken over through an idempotency key. Current `main.py` returns `wait`
for a historical `pending`/`running` job with no outbox row near
`cached_report_action` (`backend/app/main.py:240` and use at `:766`). The
observed affected count is 0. If one is found, the manual disposition is to
requeue it through the authorized application path so it creates the one
outbox row; this contract neither adds a backfill migration nor changes ADR-0001.

## Cancellation

`test_sigterm_stops_idle_worker_cleanly_without_running_jobs`
(`tests/unit/test_report_worker_process.py:136`) verifies SIGTERM shutdown for
an idle worker: it exits cleanly and leaves no running rows in that test. It is
not evidence of cancelling an already claimed, in-flight report; lease expiry
and replay remain the implemented crash-recovery path. There is no
client-facing cancellation entry point in this release; recorded as a known
gap.

## Observability

`tests/unit/test_report_worker_logging.py` defines the structured worker
logging contract. Events are `report_claimed`, `report_lease_reclaimed`,
`report_completed`, and `report_failed`; their safe fields include `job_id`,
and, where applicable, `outbox_id`, `query_id`, `attempts`, `lease_expired`,
`duration_ms`, `error_code`, `retryable`, and `error_type`. Every event also
uses the shared `ts`, `level`, `service`, and `event` envelope. See
[`production-reliability.md`](../production-reliability.md) for redaction,
correlation, alerting, and known production evidence gaps.

## Legacy-executor guarantee

`backend/app/main.py:run_generation_job` is an implementation callable, not a
production-traffic entry point. The queue worker is its sole production caller.
The static guards are
`test_only_the_report_worker_executes_generation_jobs` and
`test_no_request_path_executes_generation_jobs`; the latter asserts no
`BackgroundTasks.add_task(run_generation_job)` call and locks the sole
`add_task(` baseline to `backend/app/routes/intake.py` calling
`cleanup_expired_sessions`.

## Evidence index

| Test file | Test | Assertion | Real database required |
| --- | --- | --- | --- |
| `tests/integration/test_report_worker_postgres.py` | `test_two_real_postgres_workers_only_one_claims_same_job` | Two claimers produce one running claim. | Yes |
| `tests/integration/test_report_worker_postgres.py` | `test_real_postgres_completion_is_idempotent` | Matching completion is one-time. | Yes |
| `tests/integration/test_report_worker_postgres.py` | `test_replay_after_lease_expiry_does_not_duplicate_report` | Expired-lease replay completes one row at attempt 2. | Yes |
| `tests/integration/test_report_worker_postgres.py` | `test_reenqueue_is_idempotent` | Re-enqueue preserves one completed row. | Yes |
| `tests/integration/test_report_worker_postgres.py` | `test_completed_row_is_never_reclaimed` | Completed work is not claimable. | Yes |
| `tests/unit/test_report_worker_process.py` | `test_standalone_worker_initializes_pool_and_completes_enqueued_job` | Separate worker process completes queued work. | Yes |
| `tests/unit/test_report_worker_process.py` | `test_sigterm_stops_idle_worker_cleanly_without_running_jobs` | Idle SIGTERM exit is clean. | Yes |
| `tests/unit/test_report_worker_process.py` | `test_worker_reclaims_expired_fifteen_minute_lease` | A 15-minute expired lease is reclaimed. | Yes |
| `tests/unit/test_report_worker.py` | worker claim/failure tests | Atomic claim SQL, bounded backoff, and safe failure classification. | No |
| `tests/unit/test_report_worker_logging.py` | worker logging tests | Structured events and exception redaction. | No |
| `tests/architecture/test_report_job_queue_contract.py` | `test_only_the_report_worker_executes_generation_jobs` | Only the worker calls the executor. | No |
| `tests/architecture/test_report_job_queue_contract.py` | `test_no_request_path_executes_generation_jobs` | No report `BackgroundTasks`; intake is the sole baseline. | No |
