"""Tests for ``backend.app.collection.worker`` (collection worker executor).

Two layers:

1. Pure unit tests (no database, no network): source_key-prefix runner
   resolution, longest-prefix match, ``no_runner`` on unregistered keys,
   fixture-runner determinism and outcome validation.

2. Real-Postgres integration tests (skipped unless ``DATABASE_URL`` points at
   a disposable localhost server, mirroring ``test_admin_api`` /
   ``test_db_ledger`` conventions): the V1 batch (organizations prerequisite
   + finance/audit + collection runs) is applied to a fresh
   ``collection_worker_test`` database, then the full queue lifecycle is
   exercised against real PostgreSQL:

   * two concurrent workers claiming one queued run - exactly one wins;
   * enqueue -> ``run_once`` success records rows/hash/completed_at + the
     ``admin.collection.run_succeeded`` audit row;
   * a runner exception / unregistered source_key -> ``failed`` with
     error_message (<= 2000 chars) + ``admin.collection.run_failed`` audit,
     and no run is ever left hanging in ``running``;
   * nothing queued -> ``claim_next``/``run_once`` return None;
   * a run cancelled mid-execution is never overwritten by the worker.

The runner executed here is the deterministic in-process ``fixture`` runner
(or a deliberately failing stub) - no live collection script is ever invoked.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from backend.app.collection.worker import (
    ACTION_FAILED,
    ACTION_SUCCEEDED,
    ClaimedRun,
    CollectionOutcome,
    CollectionRunError,
    NoRunnerError,
    RUNNER_REGISTRY,
    claim_next,
    fixture_outcome,
    resolve_runner,
    run_once,
)
from backend.app.collection.worker import _normalize_outcome

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT / "supabase" / "migrations" / "20260905000100_v1_organizations.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000500_v1_finance_admin_audit.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000601_collection_runs.sql",
]

DB_NAME = "collection_worker_test"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

pytestmark_db = pytest.mark.asyncio

# ============================================================================
# Pure unit tests (no database)
# ============================================================================


def test_fixture_outcome_is_deterministic_and_well_formed() -> None:
    first = fixture_outcome("fixture/ward-a", "official_open")
    second = fixture_outcome("fixture/ward-a", "official_open")
    other = fixture_outcome("fixture/ward-b", "official_open")
    assert first == second
    assert first.rows == 1 + (len("fixture/ward-a") + len("official_open")) % 90
    assert first.rows > 0
    assert len(first.snapshot_hash or "") == 64
    assert all(c in "0123456789abcdef" for c in first.snapshot_hash or "")
    # identity is part of the seed: a different source_key hashes differently
    assert first.snapshot_hash != other.snapshot_hash


def test_fixture_runner_resolves_via_registry_prefix() -> None:
    runner = resolve_runner("fixture/anything")
    assert asyncio.iscoroutinefunction(runner)


def test_resolve_runner_picks_longest_matching_prefix() -> None:
    calls = []

    async def _ab_runner(source_key: str, source_type: str) -> CollectionOutcome:
        calls.append(source_key)
        return CollectionOutcome(rows=1)

    registry = {
        "a": _ab_runner,  # short prefix also matches, must lose to "ab"
        "ab": lambda: _ab_runner,
    }
    runner = resolve_runner("ab/ward", registry=registry)
    assert runner is _ab_runner
    assert calls == []


def test_resolve_runner_registered_async_runner_used_directly() -> None:
    async def _direct(source_key: str, source_type: str) -> CollectionOutcome:
        return CollectionOutcome(rows=2)

    assert resolve_runner("x/y", registry={"x": _direct}) is _direct


def test_default_registry_includes_real_jphouse_prefixes() -> None:
    # The real config-family runners (jphouse_runners.py) are registered into
    # RUNNER_REGISTRY when worker.py is imported.
    for prefix in ("jphouse_23ku", "jphouse_osaka_wards", "jphouse_yokohama_wards"):
        assert prefix in RUNNER_REGISTRY
        runner = resolve_runner(f"{prefix}/ward")
        assert asyncio.iscoroutinefunction(runner)


def test_unregistered_source_key_raises_no_runner() -> None:
    # A source_key that matches no registered prefix fails explicitly.
    with pytest.raises(NoRunnerError) as excinfo:
        resolve_runner("unknown/source")
    assert excinfo.value.code == "no_runner"
    # configs/jphouse_worker exists but is NOT a registered collection family.
    with pytest.raises(NoRunnerError):
        resolve_runner("jphouse_worker/anything")


def test_normalize_outcome_rejects_bad_runner_results() -> None:
    assert _normalize_outcome(CollectionOutcome(rows=3, snapshot_hash="ab" * 32)) == (
        CollectionOutcome(rows=3, snapshot_hash="ab" * 32)
    )
    with pytest.raises(CollectionRunError, match="negative"):
        _normalize_outcome(CollectionOutcome(rows=-1))
    with pytest.raises(CollectionRunError, match="64 lowercase hex"):
        _normalize_outcome(CollectionOutcome(rows=1, snapshot_hash="zz" * 32))
    with pytest.raises(CollectionRunError, match="64 lowercase hex"):
        _normalize_outcome(CollectionOutcome(rows=1, snapshot_hash="abc"))
    with pytest.raises(CollectionRunError, match="non-integer"):
        _normalize_outcome(CollectionOutcome(rows="many"))  # type: ignore[arg-type]
    with pytest.raises(CollectionRunError, match="expected CollectionOutcome"):
        _normalize_outcome("not-an-outcome")  # type: ignore[arg-type]


def test_resolve_runner_accepts_uppercase_hash_by_lowercasing() -> None:
    outcome = _normalize_outcome(CollectionOutcome(rows=1, snapshot_hash=("AB" * 32)))
    assert outcome.snapshot_hash == "ab" * 32


# ============================================================================
# Real-Postgres integration (skipped unless a disposable local server is set)
# ============================================================================


def _db_path(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _local_server(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


async def _bootstrap_and_migrate(url: str) -> None:
    """Create collection_worker_test on the local server and apply the batch."""
    admin = await asyncpg.connect(url, database="postgres")
    try:
        await admin.execute(f"drop database if exists {DB_NAME} with (force)")
        await admin.execute(f"create database {DB_NAME}")
    finally:
        await admin.close()

    conn = await asyncpg.connect(_db_path(url, DB_NAME))
    try:
        # Supabase-role/bootstrap scaffolding the V1 migrations require.
        await conn.execute(
            """
            do $$
            begin
              if to_regrole('anon') is null then execute 'create role anon nologin'; end if;
              if to_regrole('authenticated') is null then execute 'create role authenticated nologin'; end if;
              if to_regrole('service_role') is null then execute 'create role service_role nologin'; end if;
            end $$;
            create schema if not exists auth;
            create table if not exists auth.users (
              id uuid primary key,
              email text
            );
            create or replace function auth.uid() returns uuid
            language sql stable as $$
              select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
            $$;
            create or replace function public.set_updated_at()
            returns trigger language plpgsql as $$
            begin
              new.updated_at = now();
              return new;
            end
            $$;
            """
        )
        for path in MIGRATIONS:
            await conn.execute(path.read_text(encoding="utf-8"))
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    if not _local_server(DATABASE_URL):
        pytest.skip(
            "DATABASE_URL must point at a disposable local PostgreSQL server"
            " (localhost/127.0.0.1) to run the real-Postgres worker tests"
        )
    asyncio.run(_bootstrap_and_migrate(DATABASE_URL))
    return _db_path(DATABASE_URL, DB_NAME)


_AUDIT_TRIGGERS = (
    "audit_events_no_update",
    "audit_events_no_delete",
    "audit_events_no_truncate",
)


@pytest_asyncio.fixture
async def pool(_migrated_database: str):
    pg_pool = await asyncpg.create_pool(_migrated_database)
    async with pg_pool.acquire() as conn:
        # audit_events is append-only; disable its guards before truncating,
        # exactly like the ledger / admin integration suites.
        for trigger in _AUDIT_TRIGGERS:
            await conn.execute(
                f"alter table public.audit_events disable trigger {trigger}"
            )
        await conn.execute(
            "truncate table public.audit_events, public.collection_runs"
            " restart identity cascade"
        )
        for trigger in _AUDIT_TRIGGERS:
            await conn.execute(
                f"alter table public.audit_events enable trigger {trigger}"
            )
    yield pg_pool
    await pg_pool.close()


async def _enqueue(
    pool: asyncpg.Pool,
    source_key: str,
    source_type: str = "official_open",
    *,
    created_at_offset: str | None = None,
) -> UUID:
    async with pool.acquire() as conn:
        if created_at_offset is None:
            return await conn.fetchval(
                "insert into public.collection_runs (source_key, source_type)"
                " values ($1, $2) returning id",
                source_key,
                source_type,
            )
        return await conn.fetchval(
            "insert into public.collection_runs"
            " (source_key, source_type, created_at)"
            " values ($1, $2, now() + ($3 || ' seconds')::interval)"
            " returning id",
            source_key,
            source_type,
            created_at_offset,
        )


async def _fetch_run(pool: asyncpg.Pool, run_id: UUID) -> asyncpg.Record:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "select id, source_key, source_type, status, rows_collected,"
            " snapshot_hash, error_message, started_at, completed_at"
            " from public.collection_runs where id = $1",
            run_id,
        )


async def _audit_rows(pool: asyncpg.Pool, action: str, target_id: UUID) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select actor_user_id, action, target_type, target_id, summary"
            " from public.audit_events"
            " where action = $1 and target_id = $2"
            " order by occurred_at, id",
            action,
            str(target_id),
        )
    return [
        {
            "actor_user_id": row["actor_user_id"],
            "action": row["action"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "summary": json.loads(row["summary"]),
        }
        for row in rows
    ]


async def _running_count(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "select count(*) from public.collection_runs where status = 'running'"
        )


@pytestmark_db
async def test_concurrent_claims_only_one_worker_wins(pool: asyncpg.Pool) -> None:
    run_id = await _enqueue(pool, "fixture/ward-a")
    # Two worker rounds claim concurrently over the same pool: FOR UPDATE SKIP
    # LOCKED + the running-status update inside one transaction guarantee a
    # single winner regardless of scheduling order.
    results = await asyncio.gather(claim_next(pool), claim_next(pool))
    claims = [r for r in results if r is not None]
    assert len(claims) == 1
    assert results.count(None) == 1
    assert isinstance(claims[0], ClaimedRun)
    assert claims[0].run_id == run_id
    assert claims[0].source_key == "fixture/ward-a"

    row = await _fetch_run(pool, run_id)
    assert row["status"] == "running"
    assert row["started_at"] is not None
    # A claimed (running) run is never re-claimed by a later worker.
    assert await claim_next(pool) is None


@pytestmark_db
async def test_claim_picks_oldest_queued_run(pool: asyncpg.Pool) -> None:
    old_id = await _enqueue(pool, "fixture/old", created_at_offset="-60")
    await _enqueue(pool, "fixture/new", created_at_offset="0")
    claim = await claim_next(pool)
    assert claim is not None and claim.run_id == old_id


@pytestmark_db
async def test_run_once_success_records_rows_hash_and_audit(
    pool: asyncpg.Pool,
) -> None:
    run_id = await _enqueue(pool, "fixture/ward-a", "official_open")
    expected = fixture_outcome("fixture/ward-a", "official_open")

    report = await run_once(pool)

    assert report is not None
    assert report["run_id"] == str(run_id)
    assert report["status"] == "succeeded"
    assert report["rows"] == expected.rows
    assert report["snapshot_hash"] == expected.snapshot_hash
    assert report["code"] is None and report["error_message"] is None

    row = await _fetch_run(pool, run_id)
    assert row["status"] == "succeeded"
    assert row["rows_collected"] == expected.rows
    assert str(row["snapshot_hash"]).strip() == expected.snapshot_hash
    assert row["error_message"] is None
    assert row["started_at"] is not None
    assert row["completed_at"] is not None
    assert row["completed_at"] >= row["started_at"]

    audit = await _audit_rows(pool, ACTION_SUCCEEDED, run_id)
    assert len(audit) == 1
    assert audit[0]["actor_user_id"] is None  # system worker
    assert audit[0]["target_type"] == "collection_run"
    assert audit[0]["summary"] == {
        "source_key": "fixture/ward-a",
        "status": "succeeded",
        "rows": expected.rows,
    }
    assert await _audit_rows(pool, ACTION_FAILED, run_id) == []
    assert await _running_count(pool) == 0


@pytestmark_db
async def test_run_once_runner_error_marks_failed_with_audit(
    pool: asyncpg.Pool,
) -> None:
    async def _boom(source_key: str, source_type: str) -> CollectionOutcome:
        raise RuntimeError("snapshot read timeout: upstream http 503")

    run_id = await _enqueue(pool, "fixture/ward-b", "partner")

    report = await run_once(pool, registry={"fixture": lambda: _boom})

    assert report is not None
    assert report["status"] == "failed"
    assert report["code"] == "runner_error"
    assert report["error_message"] == "snapshot read timeout: upstream http 503"
    assert report["rows"] == 0 and report["snapshot_hash"] is None

    row = await _fetch_run(pool, run_id)
    assert row["status"] == "failed"
    assert row["rows_collected"] == 0
    assert row["snapshot_hash"] is None
    assert row["error_message"] == "snapshot read timeout: upstream http 503"
    assert row["started_at"] is not None and row["completed_at"] is not None
    assert await _running_count(pool) == 0  # never left hanging in running

    audit = await _audit_rows(pool, ACTION_FAILED, run_id)
    assert len(audit) == 1
    assert audit[0]["summary"] == {
        "source_key": "fixture/ward-b",
        "status": "failed",
        "rows": 0,
        "code": "runner_error",
    }
    # raw error text is diagnostic-only and never mirrored into audit
    assert "timeout" not in json.dumps(audit[0]["summary"])


@pytestmark_db
async def test_run_once_error_message_truncated_to_limit(
    pool: asyncpg.Pool,
) -> None:
    async def _verbose(source_key: str, source_type: str) -> CollectionOutcome:
        raise RuntimeError("x" * 3000)

    run_id = await _enqueue(pool, "fixture/ward-c")
    report = await run_once(pool, registry={"fixture": lambda: _verbose})

    assert report is not None and report["status"] == "failed"
    assert len(report["error_message"] or "") == 2000
    row = await _fetch_run(pool, run_id)
    assert len(row["error_message"] or "") == 2000


@pytestmark_db
async def test_run_once_unregistered_source_key_fails_no_runner(
    pool: asyncpg.Pool,
) -> None:
    # Real 23ku/Osaka/Yokohama source_keys have no runner in this unit; the
    # worker must record an explicit failed run, not crash.
    run_id = await _enqueue(pool, "unknown/source", "authorized_csv")

    report = await run_once(pool)  # default registry: fixture prefix only

    assert report is not None
    assert report["status"] == "failed"
    assert report["code"] == "no_runner"
    assert "no_runner" in (report["error_message"] or "")
    assert "unknown/source" in (report["error_message"] or "")

    row = await _fetch_run(pool, run_id)
    assert row["status"] == "failed"
    assert "no_runner" in (row["error_message"] or "")
    assert await _running_count(pool) == 0

    audit = await _audit_rows(pool, ACTION_FAILED, run_id)
    assert len(audit) == 1
    assert audit[0]["summary"]["code"] == "no_runner"


@pytestmark_db
async def test_run_once_nothing_queued_returns_none(pool: asyncpg.Pool) -> None:
    assert await claim_next(pool) is None
    assert await run_once(pool) is None
    # no audit rows were invented for a round with nothing to do
    async with pool.acquire() as conn:
        assert await conn.fetchval("select count(*) from public.audit_events") == 0


@pytestmark_db
async def test_two_concurrent_run_once_rounds_claim_disjoint_runs(
    pool: asyncpg.Pool,
) -> None:
    first_id = await _enqueue(pool, "fixture/c1")
    second_id = await _enqueue(pool, "fixture/c2")

    reports = await asyncio.gather(run_once(pool), run_once(pool))

    assert sorted(r["run_id"] for r in reports if r) == sorted(
        [str(first_id), str(second_id)]
    )
    assert all(r["status"] == "succeeded" for r in reports if r)
    for run_id in (first_id, second_id):
        row = await _fetch_run(pool, run_id)
        assert row["status"] == "succeeded"
        assert await _audit_rows(pool, ACTION_SUCCEEDED, run_id) != []
    assert await _running_count(pool) == 0


@pytestmark_db
async def test_cancelled_run_is_never_overwritten_by_worker(
    pool: asyncpg.Pool,
) -> None:
    # A runner stub that simulates an operator cancelling the run while the
    # (claimed) runner is executing.
    async def _cancelling_runner(
        source_key: str, source_type: str
    ) -> CollectionOutcome:
        async with pool.acquire() as conn:
            await conn.execute(
                "update public.collection_runs"
                " set status = 'cancelled', completed_at = now()"
                " where source_key = $1 and status = 'running'",
                source_key,
            )
        return fixture_outcome(source_key, source_type)

    run_id = await _enqueue(pool, "fixture/ward-x")
    report = await run_once(pool, registry={"fixture": lambda: _cancelling_runner})

    assert report is not None
    assert report["status"] == "cancelled"
    assert report["code"] is None

    row = await _fetch_run(pool, run_id)
    assert row["status"] == "cancelled"  # operator decision wins
    assert row["completed_at"] is not None
    assert row["rows_collected"] == 0  # worker outcome was not recorded
    assert await _audit_rows(pool, ACTION_SUCCEEDED, run_id) == []
    assert await _audit_rows(pool, ACTION_FAILED, run_id) == []
    assert await _running_count(pool) == 0
