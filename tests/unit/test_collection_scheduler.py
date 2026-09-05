"""Tests for ``backend.app.collection.scheduler`` (P1.3 scheduler unit 1).

Two layers, mirroring ``test_collection_worker.py``:

1. Pure unit tests (no database): source discovery from a fabricated config
   tree, the due/in-flight/window decision as a pure function of
   ``(state, now)`` with an injected clock, and the invariant that every
   source the scheduler would feed resolves to a registered runner.

2. Real-Postgres integration tests (skipped unless ``DATABASE_URL`` points at
   a disposable localhost server, same convention as the worker / ledger /
   admin suites): migration 20260905000601 is applied to a fresh
   ``collection_scheduler_test`` database, then the feed behaviour is checked
   against real PostgreSQL - fresh source queued, double-feed inserts zero
   duplicates, failed runs advance the window, cancelled runs do not, an
   in-flight run blocks a re-feed, and ``--dry-run`` semantics write nothing.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest
import pytest_asyncio

from backend.app.collection.scheduler import (
    ACTION_DUE_LATER,
    ACTION_QUEUED,
    ACTION_SKIPPED,
    FAMILY_BY_PREFIX,
    FAMILY_CADENCE,
    FEED_SOURCE_TYPE,
    CollectionSchedulerError,
    REASON_DUE,
    REASON_IN_FLIGHT,
    REASON_NO_HISTORY,
    REASON_WITHIN_CADENCE,
    SCHEDULED_FAMILIES,
    SchedulableSource,
    ScheduledFamily,
    decide,
    decide_all,
    decision_to_json,
    discover_sources,
    feed_due,
    fetch_state,
    plan_due,
    run_feed,
)
from backend.app.collection.worker import resolve_runner

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260905000601_collection_runs.sql",
]

DB_NAME = "collection_scheduler_test"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

pytestmark_db = pytest.mark.asyncio

NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# Pure unit tests (no database)
# ============================================================================


def _tmp_source(tmp_path: Path, stem: str, prefix: str = "famA") -> SchedulableSource:
    return SchedulableSource(source_key=f"{prefix}/{stem}", prefix=prefix, stem=stem)


def test_discover_sources_enumerates_config_stems_sorted(tmp_path: Path) -> None:
    (tmp_path / "configs/famA").mkdir(parents=True)
    (tmp_path / "configs/famB").mkdir(parents=True)
    for stem in ("zeta", "alpha", "mid"):
        (tmp_path / "configs/famA" / f"{stem}.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs/famB" / "only.json").write_text("{}", encoding="utf-8")
    # a non-json file and a subdir must be ignored
    (tmp_path / "configs/famA" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "configs/famA" / "sub").mkdir()

    families = (
        ScheduledFamily(prefix="famA", config_dir_rel="configs/famA"),
        ScheduledFamily(prefix="famB", config_dir_rel="configs/famB"),
    )
    found = discover_sources(families, repo_root=tmp_path)

    assert [s.source_key for s in found] == [
        "famA/alpha",
        "famA/mid",
        "famA/zeta",
        "famB/only",
    ]
    assert all(s.cadence == FAMILY_CADENCE for s in found)


def test_discover_sources_prefix_filter(tmp_path: Path) -> None:
    (tmp_path / "configs/famA").mkdir(parents=True)
    (tmp_path / "configs/famB").mkdir(parents=True)
    (tmp_path / "configs/famA" / "a1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "configs/famB" / "b1.json").write_text("{}", encoding="utf-8")

    families = (
        ScheduledFamily(prefix="famA", config_dir_rel="configs/famA"),
        ScheduledFamily(prefix="famB", config_dir_rel="configs/famB"),
    )
    only_a = discover_sources(families, prefix="famA", repo_root=tmp_path)
    assert [s.source_key for s in only_a] == ["famA/a1"]
    empty = discover_sources(families, prefix="nope", repo_root=tmp_path)
    assert empty == ()


def test_discover_sources_empty_dir_is_not_an_error(tmp_path: Path) -> None:
    (tmp_path / "configs/famA").mkdir(parents=True)
    families = (ScheduledFamily(prefix="famA", config_dir_rel="configs/famA"),)
    assert discover_sources(families, repo_root=tmp_path) == ()


def test_discover_sources_missing_config_dir_raises(tmp_path: Path) -> None:
    families = (ScheduledFamily(prefix="famA", config_dir_rel="configs/famA"),)
    with pytest.raises(CollectionSchedulerError, match="missing"):
        discover_sources(families, repo_root=tmp_path)


def test_real_repo_discovery_covers_every_jphouse_ward_config() -> None:
    sources = discover_sources()
    by_prefix: dict[str, list[SchedulableSource]] = {}
    for src in sources:
        by_prefix.setdefault(src.prefix, []).append(src)

    # The schedulable universe is exactly the three jphouse ward families
    # (fixture is not schedulable and never appears).
    assert set(FAMILY_BY_PREFIX) == {
        "jphouse_23ku",
        "jphouse_osaka_wards",
        "jphouse_yokohama_wards",
    }
    assert set(by_prefix) == set(FAMILY_BY_PREFIX)

    for family in SCHEDULED_FAMILIES:
        config_dir = REPO_ROOT / family.config_dir_rel
        expected_stems = sorted(p.stem for p in config_dir.glob("*.json"))
        actual = [s.stem for s in by_prefix[family.prefix]]
        assert actual == expected_stems
        assert all(
            s.source_key == f"{family.prefix}/{s.stem}" for s in by_prefix[family.prefix]
        )
    assert len(sources) == sum(len(v) for v in by_prefix.values())


def test_every_schedulable_source_resolves_to_a_runner() -> None:
    # A feed may never target a source_key the worker cannot execute: each
    # discovered source must resolve under the real runner registry.
    for source in discover_sources():
        runner = resolve_runner(source.source_key)
        assert asyncio.iscoroutinefunction(runner), source.source_key


def _state(key: str, *, last: datetime | None = None, inflight: bool = False):
    from backend.app.collection.scheduler import SourceState

    return SourceState(source_key=key, last_terminal_at=last, has_inflight=inflight)


def test_decide_no_history_queues_immediately() -> None:
    src = _tmp_source("x", "ward")
    decision = decide(src, _state("famA/ward"), now=NOW)
    assert decision.action == ACTION_QUEUED
    assert decision.reason == REASON_NO_HISTORY
    assert decision.last_terminal_at is None


def test_decide_inflight_guard_wins_even_when_due() -> None:
    src = _tmp_source("x", "ward")
    old = NOW - timedelta(days=30)
    decision = decide(
        src, _state("famA/ward", last=old, inflight=True), now=NOW
    )
    assert decision.action == ACTION_SKIPPED
    assert decision.reason == REASON_IN_FLIGHT
    assert decision.last_terminal_at == old


def test_decide_within_cadence_is_due_later() -> None:
    src = _tmp_source("x", "ward")
    recent = NOW - timedelta(days=3)
    decision = decide(src, _state("famA/ward", last=recent), now=NOW)
    assert decision.action == ACTION_DUE_LATER
    assert decision.reason == REASON_WITHIN_CADENCE
    assert decision.last_terminal_at == recent


def test_decide_past_cadence_is_due() -> None:
    src = _tmp_source("x", "ward")
    old = NOW - timedelta(days=8)
    decision = decide(src, _state("famA/ward", last=old), now=NOW)
    assert decision.action == ACTION_QUEUED
    assert decision.reason == REASON_DUE
    assert decision.last_terminal_at == old


def test_decide_exact_cadence_boundary_is_due() -> None:
    # now - last == cadence must count as due (>= comparison).
    src = _tmp_source("x", "ward")
    boundary = NOW - FAMILY_CADENCE
    decision = decide(src, _state("famA/ward", last=boundary), now=NOW)
    assert decision.action == ACTION_QUEUED
    assert decision.reason == REASON_DUE


def test_decide_defaults_clock_to_real_utc_now() -> None:
    from backend.app.collection.scheduler import default_now

    now = default_now()
    assert now.tzinfo is not None and now.utcoffset().total_seconds() == 0
    # a source with no history is due under any sane clock
    decision = decide(_tmp_source("x", "ward"), _state("famA/ward"), now=now)
    assert decision.action == ACTION_QUEUED


def test_decide_rejects_naive_now() -> None:
    src = _tmp_source("x", "ward")
    naive = datetime(2026, 9, 5, 12, 0, 0)
    with pytest.raises(CollectionSchedulerError, match="timezone"):
        decide(src, _state("famA/ward"), now=naive)


def test_decide_all_absent_state_is_no_history() -> None:
    sources = (
        _tmp_source("x", "a", prefix="famA"),
        _tmp_source("x", "b", prefix="famA"),
    )
    # only source "a" has any state
    decisions = decide_all(
        sources,
        {"famA/a": _state("famA/a", last=NOW - timedelta(days=2))},
        now=NOW,
    )
    by_key = {d.source_key: d for d in decisions}
    assert by_key["famA/a"].action == ACTION_DUE_LATER
    assert by_key["famA/b"].action == ACTION_QUEUED
    assert by_key["famA/b"].reason == REASON_NO_HISTORY


def test_decision_to_json_is_flat_no_pii() -> None:
    src = _tmp_source("x", "ward")
    plain = decision_to_json(decide(src, _state("famA/ward"), now=NOW))
    assert plain == {"source_key": "famA/ward", "action": "queued", "reason": "no_history"}

    dry = decision_to_json(
        decide(src, _state("famA/ward"), now=NOW), dry_run=True
    )
    assert dry["dry_run"] is True

    late = decision_to_json(
        decide(
            src,
            _state("famA/ward", last=NOW - timedelta(days=2)),
            now=NOW,
        )
    )
    assert late["action"] == ACTION_DUE_LATER
    assert late["last_terminal_at"].startswith("2026-09-03")


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
    """Create collection_scheduler_test and apply the 00601 migration."""
    admin = await asyncpg.connect(url, database="postgres")
    try:
        await admin.execute(f"drop database if exists {DB_NAME} with (force)")
        await admin.execute(f"create database {DB_NAME}")
    finally:
        await admin.close()

    conn = await asyncpg.connect(_db_path(url, DB_NAME))
    try:
        # Supabase-role/bootstrap scaffolding 00601 requires.
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
            " (localhost/127.0.0.1) to run the real-Postgres scheduler tests"
        )
    asyncio.run(_bootstrap_and_migrate(DATABASE_URL))
    return _db_path(DATABASE_URL, DB_NAME)


@pytest_asyncio.fixture
async def pool(_migrated_database: str):
    pg_pool = await asyncpg.create_pool(_migrated_database)
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "truncate table public.collection_runs restart identity cascade"
        )
    yield pg_pool
    await pg_pool.close()


async def _insert_run(
    pool: asyncpg.Pool,
    source_key: str,
    status: str = "succeeded",
    *,
    created_at: datetime | None = None,
) -> None:
    async with pool.acquire() as conn:
        if created_at is None:
            await conn.execute(
                "insert into public.collection_runs (source_key, source_type, status)"
                " values ($1, $2, $3)",
                source_key,
                FEED_SOURCE_TYPE,
                status,
            )
        else:
            await conn.execute(
                "insert into public.collection_runs"
                " (source_key, source_type, status, created_at)"
                " values ($1, $2, $3, $4)",
                source_key,
                FEED_SOURCE_TYPE,
                status,
                created_at,
            )


async def _queued_count(pool: asyncpg.Pool, source_key: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "select count(*) from public.collection_runs"
            " where source_key = $1 and status = 'queued'",
            source_key,
        )


async def _row(pool: asyncpg.Pool, source_key: str) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "select source_key, source_type, status, operator_user_id"
            " from public.collection_runs"
            " where source_key = $1 order by created_at desc limit 1",
            source_key,
        )


def _src(source_key: str, prefix: str = "famA") -> SchedulableSource:
    stem = source_key.split("/", 1)[1]
    return SchedulableSource(source_key=source_key, prefix=prefix, stem=stem)


async def _feed_due(
    pool: asyncpg.Pool,
    sources: Sequence[SchedulableSource],
    *,
    now: datetime | None = None,
) -> tuple:
    """Invoke ``feed_due`` over a pooled connection.

    ``feed_due`` takes a :class:`asyncpg.Connection` (it owns the transaction
    scope); the integration tests hold a :class:`asyncpg.Pool`, so acquire one
    connection per call exactly like the CLI's ``run_feed`` does.
    """

    async with pool.acquire() as conn:
        return await feed_due(conn, sources, now=now)


async def _plan_due(
    pool: asyncpg.Pool,
    sources: Sequence[SchedulableSource],
    *,
    now: datetime | None = None,
) -> tuple:
    """Invoke ``plan_due`` over a pooled connection (read-only dry run)."""

    async with pool.acquire() as conn:
        return await plan_due(conn, sources, now=now)


@pytestmark_db
async def test_feed_fresh_source_inserts_aggregate_authorized_queued(
    pool: asyncpg.Pool,
) -> None:
    sources = (_src("jphouse_23ku/shibuya", prefix="jphouse_23ku"),)
    decisions = await _feed_due(pool, sources, now=NOW)

    assert [d.action for d in decisions] == [ACTION_QUEUED]
    assert decisions[0].reason == REASON_NO_HISTORY
    assert await _queued_count(pool, "jphouse_23ku/shibuya") == 1

    row = await _row(pool, "jphouse_23ku/shibuya")
    assert row is not None
    assert row["status"] == "queued"
    assert row["source_type"] == FEED_SOURCE_TYPE == "aggregate_authorized"
    assert row["operator_user_id"] is None  # a service feed, not an operator


@pytestmark_db
async def test_feed_twice_back_to_back_inserts_zero_duplicates(
    pool: asyncpg.Pool,
) -> None:
    sources = (_src("jphouse_23ku/shibuya", prefix="jphouse_23ku"),)
    first = await _feed_due(pool, sources, now=NOW)
    second = await _feed_due(pool, sources, now=NOW)

    assert first[0].action == ACTION_QUEUED
    assert second[0].action == ACTION_SKIPPED
    assert second[0].reason == REASON_IN_FLIGHT
    assert await _queued_count(pool, "jphouse_23ku/shibuya") == 1


@pytestmark_db
async def test_feed_due_after_window_elapsed(pool: asyncpg.Pool) -> None:
    await _insert_run(
        pool,
        "jphouse_23ku/shibuya",
        "succeeded",
        created_at=NOW - timedelta(days=8),
    )
    decisions = await _feed_due(pool, (_src("jphouse_23ku/shibuya", "jphouse_23ku"),), now=NOW)
    assert decisions[0].action == ACTION_QUEUED
    assert decisions[0].reason == REASON_DUE
    assert await _queued_count(pool, "jphouse_23ku/shibuya") == 1


@pytestmark_db
async def test_feed_within_window_is_due_later_and_writes_nothing(
    pool: asyncpg.Pool,
) -> None:
    await _insert_run(
        pool,
        "jphouse_23ku/shibuya",
        "succeeded",
        created_at=NOW - timedelta(days=3),
    )
    decisions = await _feed_due(pool, (_src("jphouse_23ku/shibuya", "jphouse_23ku"),), now=NOW)
    assert decisions[0].action == ACTION_DUE_LATER
    assert decisions[0].reason == REASON_WITHIN_CADENCE
    assert await _queued_count(pool, "jphouse_23ku/shibuya") == 0


@pytestmark_db
async def test_failed_run_advances_window(pool: asyncpg.Pool) -> None:
    # A failed attempt 3 days ago is still "recent": no re-feed storm.
    await _insert_run(
        pool,
        "jphouse_23ku/shibuya",
        "failed",
        created_at=NOW - timedelta(days=3),
    )
    decisions = await _feed_due(pool, (_src("jphouse_23ku/shibuya", "jphouse_23ku"),), now=NOW)
    assert decisions[0].action == ACTION_DUE_LATER

    # A failed attempt 8 days ago means the weekly window has passed.
    # (Separate source: the failed@3d row above would otherwise be the
    # latest terminal attempt for shibuya and keep it inside the window.)
    await _insert_run(
        pool,
        "jphouse_23ku/setagaya",
        "failed",
        created_at=NOW - timedelta(days=8),
    )
    decisions = await _feed_due(pool, (_src("jphouse_23ku/setagaya", "jphouse_23ku"),), now=NOW)
    assert decisions[0].action == ACTION_QUEUED
    assert decisions[0].reason == REASON_DUE


@pytestmark_db
async def test_cancelled_run_does_not_advance_window(pool: asyncpg.Pool) -> None:
    # A cancelled run is not a collection attempt: source stays due (no history).
    await _insert_run(
        pool,
        "jphouse_23ku/shibuya",
        "cancelled",
        created_at=NOW - timedelta(days=2),
    )
    decisions = await _feed_due(pool, (_src("jphouse_23ku/shibuya", "jphouse_23ku"),), now=NOW)
    assert decisions[0].action == ACTION_QUEUED
    assert decisions[0].reason == REASON_NO_HISTORY


@pytestmark_db
async def test_running_run_blocks_refeed_of_stale_source(pool: asyncpg.Pool) -> None:
    # Old history says the source is due, but a worker currently owns a run.
    await _insert_run(
        pool,
        "jphouse_23ku/shibuya",
        "succeeded",
        created_at=NOW - timedelta(days=30),
    )
    await _insert_run(
        pool,
        "jphouse_23ku/shibuya",
        "running",
        created_at=NOW - timedelta(hours=1),
    )
    decisions = await _feed_due(pool, (_src("jphouse_23ku/shibuya", "jphouse_23ku"),), now=NOW)
    assert decisions[0].action == ACTION_SKIPPED
    assert decisions[0].reason == REASON_IN_FLIGHT
    assert await _queued_count(pool, "jphouse_23ku/shibuya") == 0


@pytestmark_db
async def test_plan_due_is_dry_run_and_writes_nothing(pool: asyncpg.Pool) -> None:
    sources = (
        _src("jphouse_23ku/shibuya", "jphouse_23ku"),
        _src("jphouse_23ku/setagaya", "jphouse_23ku"),
    )
    decisions = await _plan_due(pool, sources, now=NOW)
    assert {d.action for d in decisions} == {ACTION_QUEUED}
    assert await _queued_count(pool, "jphouse_23ku/shibuya") == 0
    assert await _queued_count(pool, "jphouse_23ku/setagaya") == 0


@pytestmark_db
async def test_feed_batch_inserts_all_due_in_one_transaction(
    pool: asyncpg.Pool,
) -> None:
    sources = (
        _src("jphouse_23ku/shibuya", "jphouse_23ku"),
        _src("jphouse_osaka_wards/kita", "jphouse_osaka_wards"),
        _src("jphouse_yokohama_wards/naka", "jphouse_yokohama_wards"),
    )
    decisions = await _feed_due(pool, sources, now=NOW)
    assert {d.action for d in decisions} == {ACTION_QUEUED}
    for source in sources:
        assert await _queued_count(pool, source.source_key) == 1


@pytestmark_db
async def test_run_feed_dry_run_prefix_filter_discovery(pool: asyncpg.Pool) -> None:
    # Whole-family dry run against the real repo: every 23ku ward is "queued
    # (would queue)" because the table is empty, and nothing is written.
    decisions = await run_feed(pool, now=NOW, prefix="jphouse_23ku", dry_run=True)
    assert decisions
    assert all(d.source_key.startswith("jphouse_23ku/") for d in decisions)
    assert all(d.action == ACTION_QUEUED for d in decisions)
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "select count(*) from public.collection_runs where status = 'queued'"
        )
    assert total == 0
