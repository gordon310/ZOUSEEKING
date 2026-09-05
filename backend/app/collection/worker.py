"""Collection worker executor: claim -> run -> record, with audit.

Advances ``public.collection_runs`` (migration 20260905000601) one row at a
time:

* ``claim_next`` atomically claims the oldest ``queued`` run inside a single
  transaction (``select ... for update skip locked`` then an update to
  ``running`` + ``started_at``).  Concurrent workers never double-claim a run:
  the second worker either blocks on the row lock until the first commits and
  then no longer sees a ``queued`` row, or it skips the locked row entirely.
* ``run_once`` claims one run, resolves its runner from the source_key prefix
  registry, executes it, then records the terminal state plus an append-only
  ``audit_events`` row inside one transaction:

  * runner success  -> status ``succeeded``, ``rows_collected`` +
    ``snapshot_hash`` + ``completed_at``, audit
    ``admin.collection.run_succeeded``;
  * runner failure  -> status ``failed``, ``error_message`` (truncated to 2000
    chars, raw text lives only on the run row - never in the audit summary),
    ``completed_at``, audit ``admin.collection.run_failed``.

  An uncaught exception from the runner is converted to ``failed`` exactly like
  a raised error, so a run is never left hanging in ``running``.  The terminal
  UPDATE is guarded by ``where status = 'running'``: if an operator cancelled
  the run while the runner was executing, the worker's write is a no-op and
  ``run_once`` reports ``status='cancelled'`` (the operator's decision wins).

Runner protocol
---------------
A runner is an async callable ``run(source_key: str, source_type: str) ->
CollectionOutcome`` returning collected ``rows`` and a lowercase-hex sha256
``snapshot_hash`` (raw snapshots are never stored on the run row; see the
migration comment).  Runners raise to report failure; ``run_once`` records the
error.

Registration
------------
``RUNNER_REGISTRY`` maps a source_key prefix to a runner *factory* (a
zero-argument callable returning a Runner) so real runners can be parameterised
by config in a later unit.  The longest matching prefix wins.

* ``fixture`` - built-in deterministic runner for tests/self-checks.
* ``jphouse_23ku/``, ``jphouse_osaka_wards/``, ``jphouse_yokohama_wards/`` -
  real collection runners wired to ``configs/jphouse_23ku/<ward>.json`` etc.
  arrive in the next unit; until they are registered such source_keys fail
  explicitly with ``code='no_runner'`` instead of crashing the worker.

Access contract: the worker talks to ``collection_runs`` / ``audit_events``
over the trusted (service-role/superuser) pool exactly like the back-office
API; both tables are internal-domain with RLS enabled and no anon policy.
Audit rows are written with a NULL actor (system worker).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping, Optional, Union, cast
from uuid import UUID

import asyncpg

# Hard cap matching the migration's internal-domain posture: error text is
# diagnostic, stored on the run row only, and never mirrored into the audit
# summary (audit carries a redacted digest - no exception stacks).
ERROR_MESSAGE_LIMIT = 2000

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Terminal audit actions (append-only log, NULL actor = system worker).
ACTION_SUCCEEDED = "admin.collection.run_succeeded"
ACTION_FAILED = "admin.collection.run_failed"

# Cancellation races: terminal UPDATE target when another trusted writer
# (operator cancel) flipped the row while the runner was executing.
STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True)
class CollectionOutcome:
    """What a runner produces for one executed run."""

    rows: int
    snapshot_hash: Optional[str] = None


@dataclass(frozen=True)
class ClaimedRun:
    """One atomically claimed queued run (id + identity + source_type)."""

    run_id: UUID
    source_key: str
    source_type: str


class CollectionRunError(RuntimeError):
    """Runner/registry failure with a stable machine code.

    ``run_once`` maps ``code`` into the failed report and (optionally) the
    audit summary so operators can filter without parsing free text.
    """

    code = "runner_error"

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class NoRunnerError(CollectionRunError):
    """No registered runner prefix matches the run's source_key."""

    code = "no_runner"


Runner = Callable[[str, str], Awaitable[CollectionOutcome]]
RunnerFactory = Callable[[], Runner]
# A registry entry may be either the runner itself or a zero-arg factory.
RunnerLike = Union[Runner, RunnerFactory]


# ---------------------------------------------------------------------------
# fixture runner (deterministic, for tests and manual self-checks)
# ---------------------------------------------------------------------------


def fixture_outcome(source_key: str, source_type: str) -> CollectionOutcome:
    """Deterministic rows/hash for the ``fixture`` runner.

    Pure function of the run identity so two executions of the same queued run
    agree and the suite can assert exact values.  rows is derived from the
    identity length; snapshot_hash is sha256 of the identity seed.
    """
    seed = f"fixture-collection:{source_key}:{source_type}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    rows = 1 + (len(source_key) + len(source_type)) % 90
    return CollectionOutcome(rows=rows, snapshot_hash=digest)


async def _fixture_run(source_key: str, source_type: str) -> CollectionOutcome:
    return fixture_outcome(source_key, source_type)


def _fixture_factory() -> Runner:
    return cast(Runner, _fixture_run)


# source_key prefix -> runner factory.  The longest matching prefix wins.
# Real collection runners mapped from configs/jphouse_23ku/<ward>.json,
# configs/jphouse_osaka_wards/*.json, configs/jphouse_yokohama_wards/*.json
# are registered here by the NEXT unit (one factory per prefix, reading the
# matching config to drive the live collector); until then their source_keys
# fail with code='no_runner'.
RUNNER_REGISTRY: dict[str, RunnerFactory] = {"fixture": _fixture_factory}


def resolve_runner(
    source_key: str,
    *,
    registry: Optional[Mapping[str, RunnerLike]] = None,
) -> Runner:
    """Resolve the runner for ``source_key`` by longest registered prefix.

    Raises :class:`NoRunnerError` (code ``no_runner``) when no prefix matches,
    so an unregistered real source_key produces an explicit failed run rather
    than a worker crash.
    """
    reg: Mapping[str, RunnerLike] = RUNNER_REGISTRY if registry is None else registry
    prefixes = [prefix for prefix in reg if source_key.startswith(prefix)]
    if not prefixes:
        known = ", ".join(sorted(reg)) or "(none)"
        raise NoRunnerError(
            f"[no_runner] no runner registered for source_key {source_key!r}"
            f" (registered prefixes: {known})"
        )
    entry = reg[max(prefixes, key=len)]
    # Allow registering either the async runner itself or a zero-arg factory.
    if inspect.iscoroutinefunction(entry):
        return cast(Runner, entry)
    runner = cast(RunnerFactory, entry)()
    if not callable(runner):
        raise CollectionRunError(
            f"[no_runner] runner factory for {source_key!r} produced no callable",
            code="no_runner",
        )
    return runner


# ---------------------------------------------------------------------------
# claiming
# ---------------------------------------------------------------------------


async def claim_next(pool: asyncpg.Pool) -> Optional[ClaimedRun]:
    """Atomically claim the oldest ``queued`` run, or return None.

    One transaction: ``select ... for update skip locked`` pins the oldest
    queued row so concurrent workers either block until this commit (then see
    it as ``running``) or skip the locked row - exactly one claimer wins.
    Safe across multiple worker processes/connections; never claim the same
    row twice (verified by the concurrency test in tests/unit/).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "select id, source_key, source_type"
                " from public.collection_runs"
                " where status = 'queued'"
                " order by created_at asc, id asc"
                " limit 1"
                " for update skip locked"
            )
            if row is None:
                return None
            await conn.execute(
                "update public.collection_runs"
                " set status = 'running', started_at = now()"
                " where id = $1",
                row["id"],
            )
    return ClaimedRun(
        run_id=row["id"], source_key=row["source_key"], source_type=row["source_type"]
    )


# ---------------------------------------------------------------------------
# outcome validation / error formatting
# ---------------------------------------------------------------------------


def _normalize_outcome(outcome: object) -> CollectionOutcome:
    """Sanitise a runner result so a bad value cannot wedge the run row.

    A too-long/odd-shaped snapshot_hash or negative row count would violate the
    table constraints and roll the final UPDATE back, leaving the run stuck in
    ``running`` - instead such results are treated as runner failures.
    """
    if not isinstance(outcome, CollectionOutcome):
        raise CollectionRunError(
            f"runner returned {type(outcome).__name__}, expected CollectionOutcome"
        )
    rows = outcome.rows
    try:
        rows_int = int(rows)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CollectionRunError(
            f"runner returned non-integer rows_collected: {rows!r}"
        ) from exc
    if rows_int < 0:
        raise CollectionRunError(
            f"runner returned negative rows_collected: {rows_int}"
        )
    raw_hash = outcome.snapshot_hash
    snapshot_hash: Optional[str] = None
    if raw_hash is not None:
        text = str(raw_hash).strip().lower()
        if not _HEX64.match(text):
            raise CollectionRunError(
                "runner snapshot_hash must be 64 lowercase hex chars"
            )
        snapshot_hash = text
    return CollectionOutcome(rows=rows_int, snapshot_hash=snapshot_hash)


def _error_text(exc: BaseException) -> str:
    text = str(exc) or ""
    return (text[:ERROR_MESSAGE_LIMIT]) if text else exc.__class__.__name__


def _truncate(message: str) -> str:
    return message[:ERROR_MESSAGE_LIMIT]


# ---------------------------------------------------------------------------
# terminal recording (run row + audit in one transaction)
# ---------------------------------------------------------------------------


async def _write_terminal_state(
    pool: asyncpg.Pool,
    run_id: UUID,
    *,
    status: str,
    action: str,
    rows_collected: int,
    snapshot_hash: Optional[str],
    error_message: Optional[str],
    summary: dict,
) -> bool:
    """Flip a claimed (running) run to its terminal state + write its audit row.

    Guarded by ``where status = 'running'`` so a run cancelled by an operator
    while the runner executed is never overwritten by the worker.  Returns
    False when the row was no longer running (cancellation race) - no audit
    row is written in that case because no worker outcome was recorded.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                "update public.collection_runs"
                " set status = $2, rows_collected = $3, snapshot_hash = $4,"
                "     error_message = $5, completed_at = now()"
                " where id = $1 and status = 'running'"
                " returning id",
                run_id,
                status,
                rows_collected,
                snapshot_hash,
                error_message,
            )
            if updated is None:
                return False
            await conn.execute(
                "insert into public.audit_events"
                " (action, target_type, target_id, summary)"
                " values ($1, 'collection_run', $2, $3::jsonb)",
                action,
                str(run_id),
                json.dumps(summary, ensure_ascii=False),
            )
    return True


# ---------------------------------------------------------------------------
# single worker round
# ---------------------------------------------------------------------------

async def run_once(
    pool: asyncpg.Pool,
    *,
    registry: Optional[Mapping[str, RunnerLike]] = None,
) -> Optional[dict]:
    """Claim one queued run and execute it to a terminal state.

    Returns None when there is nothing queued; otherwise a report dict::

        {
            "run_id": str, "source_key": str, "source_type": str,
            "status": "succeeded" | "failed" | "cancelled",
            "rows": int, "snapshot_hash": str | None,
            "code": None | "no_runner" | "runner_error",
            "error_message": None | str,   # failed runs, <= 2000 chars
        }

    ``cancelled`` is only produced by a cancellation race during execution
    (nothing was recorded).  Any exception escaping a runner - expected or
    not - becomes ``failed`` with audit ``admin.collection.run_failed``; a run
    is never left hanging in ``running``.
    """
    claim = await claim_next(pool)
    if claim is None:
        return None

    base = {
        "run_id": str(claim.run_id),
        "source_key": claim.source_key,
        "source_type": claim.source_type,
    }

    try:
        runner = resolve_runner(claim.source_key, registry=registry)
        outcome = _normalize_outcome(await runner(claim.source_key, claim.source_type))
    except NoRunnerError as exc:
        code, message = exc.code, _truncate(_error_text(exc))
    except CollectionRunError as exc:
        code, message = exc.code, _truncate(_error_text(exc))
    except Exception as exc:  # noqa: BLE001 - uncaught runner errors go to failed
        code, message = "runner_error", _truncate(_error_text(exc))
    else:
        recorded = await _write_terminal_state(
            pool,
            claim.run_id,
            status="succeeded",
            action=ACTION_SUCCEEDED,
            rows_collected=outcome.rows,
            snapshot_hash=outcome.snapshot_hash,
            error_message=None,
            summary={
                "source_key": claim.source_key,
                "status": "succeeded",
                "rows": outcome.rows,
            },
        )
        if not recorded:
            return {**base, "status": STATUS_CANCELLED, "rows": 0,
                    "snapshot_hash": None, "code": None, "error_message": None}
        return {
            **base,
            "status": "succeeded",
            "rows": outcome.rows,
            "snapshot_hash": outcome.snapshot_hash,
            "code": None,
            "error_message": None,
        }

    recorded = await _write_terminal_state(
        pool,
        claim.run_id,
        status="failed",
        action=ACTION_FAILED,
        rows_collected=0,
        snapshot_hash=None,
        error_message=message,
        summary={
            "source_key": claim.source_key,
            "status": "failed",
            "rows": 0,
            "code": code,
        },
    )
    if not recorded:
        return {**base, "status": STATUS_CANCELLED, "rows": 0,
                "snapshot_hash": None, "code": None, "error_message": None}
    return {
        **base,
        "status": "failed",
        "rows": 0,
        "snapshot_hash": None,
        "code": code,
        "error_message": message,
    }


# Re-export for introspection/typing use by entrypoints and tests.
__all__ = [
    "ACTION_FAILED",
    "ACTION_SUCCEEDED",
    "ClaimedRun",
    "CollectionOutcome",
    "CollectionRunError",
    "ERROR_MESSAGE_LIMIT",
    "NoRunnerError",
    "RUNNER_REGISTRY",
    "Runner",
    "RunnerFactory",
    "RunnerLike",
    "STATUS_CANCELLED",
    "claim_next",
    "fixture_outcome",
    "resolve_runner",
    "run_once",
]
