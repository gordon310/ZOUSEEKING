"""Tests for ``backend.app.collection.sweeper`` (collection sweeper / QA).

Two layers:

1. Pure unit tests (no database, no network): source_key -> snapshot path
   resolution (jphouse families only, traversal-safe), on-disk snapshot hash
   verification verdicts (ok / hash mismatch / rows mismatch / missing /
   unreadable), canonical fingerprint consistency with the runner's rule
   (``collected_at`` excluded), and argument validation.

2. Real-Postgres integration tests (skipped unless ``DATABASE_URL`` points at
   a disposable localhost server, mirroring ``test_collection_worker``):
   the V1 batch (organizations + finance/audit + collection runs) is applied
   to a fresh ``collection_sweeper_test`` database, then:

   * a stale ``running`` run (started_at older than the sweep window) is
     flipped to ``failed`` with an explanatory ``error_message`` and an
     ``admin.collection.run_swept`` audit row, while a fresh ``running`` run
     and ``queued`` runs are untouched;
   * a second sweep is a no-op (recovery is idempotent);
   * ``dry_run=True`` reports candidates and writes nothing;
   * two concurrent sweepers split the batch and never double-recover;
   * snapshot hash QA verifies persisted snapshot files against recorded
     hashes (ok / tampered / missing) and skips non-file-backed source_keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from backend.app.collection.jphouse_runners import canonical_snapshot_payload
from backend.app.collection.sweeper import (
    ACTION_DRY_RUN,
    ACTION_RECOVERED,
    ACTION_SWEPT,
    VERIFY_FILE_MISSING,
    VERIFY_FILE_UNREADABLE,
    VERIFY_HASH_MISMATCH,
    VERIFY_OK,
    VERIFY_ROWS_MISMATCH,
    recover_stale_runs,
    snapshot_rel_for_source,
    verify_snapshot_file,
    verify_snapshot_hashes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT / "supabase" / "migrations" / "20260905000100_v1_organizations.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000500_v1_finance_admin_audit.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000601_collection_runs.sql",
]

DB_NAME = "collection_sweeper_test"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

pytestmark_db = pytest.mark.asyncio

# ============================================================================
# Pure unit tests (no database)
# ============================================================================


def test_snapshot_rel_for_source_maps_jphouse_families_only() -> None:
    for prefix in ("jphouse_23ku", "jphouse_osaka_wards", "jphouse_yokohama_wards"):
        assert snapshot_rel_for_source(f"{prefix}/minato") == (
            f"data/collected/jphouse_runs/{prefix}/minato.json"
        )
    # fixture runner and unknown prefixes have no file-backed snapshot.
    assert snapshot_rel_for_source("fixture/anything") is None
    assert snapshot_rel_for_source("unknown/thing") is None
    # malformed / traversal attempts never resolve to a path.
    assert snapshot_rel_for_source("jphouse_23ku") is None
    assert snapshot_rel_for_source("jphouse_23ku/a/b") is None
    assert snapshot_rel_for_source("jphouse_23ku/../evil") is None
    assert snapshot_rel_for_source("/abs/path") is None


def test_canonical_fingerprint_excludes_collected_at_only() -> None:
    base = {
        "source_key": "jphouse_23ku/minato",
        "rows": [{"metric": "rent", "value_man_yen": 12.5}],
        "rows_collected": 1,
    }
    one = dict(base, collected_at="2026-09-05T00:00:00+00:00")
    two = dict(base, collected_at="2026-09-06T12:34:56+00:00")
    assert canonical_snapshot_payload(one) == canonical_snapshot_payload(two)
    # A content change (a row value) does change the fingerprint.
    changed = dict(base, rows=[{"metric": "rent", "value_man_yen": 13.5}])
    assert canonical_snapshot_payload(one) != canonical_snapshot_payload(changed)
    digest = hashlib.sha256(canonical_snapshot_payload(one)).hexdigest()
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_verify_snapshot_file_ok_when_hash_and_rows_match(tmp_path: Path) -> None:
    snapshot = {
        "source_key": "jphouse_23ku/minato",
        "rows": [{"metric": "rent", "value_man_yen": 12.5}],
        "rows_collected": 1,
        "collected_at": "2026-09-05T00:00:00+00:00",
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(canonical_snapshot_payload(snapshot)).hexdigest()
    verdict = verify_snapshot_file(path, digest, recorded_rows=1)
    assert verdict["code"] == VERIFY_OK
    assert verdict["computed_hash"] == digest
    assert verdict["file_rows"] == 1


def test_verify_snapshot_file_detects_tamper(tmp_path: Path) -> None:
    original = {
        "source_key": "jphouse_23ku/minato",
        "rows": [{"metric": "rent", "value_man_yen": 12.5}],
        "rows_collected": 1,
    }
    digest = hashlib.sha256(canonical_snapshot_payload(original)).hexdigest()
    tampered = dict(original, rows=[{"metric": "rent", "value_man_yen": 99.9}])
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    verdict = verify_snapshot_file(path, digest, recorded_rows=1)
    assert verdict["code"] == VERIFY_HASH_MISMATCH
    assert verdict["computed_hash"] != digest


def test_verify_snapshot_file_rows_mismatch_only_without_hash(tmp_path: Path) -> None:
    snapshot = {
        "source_key": "jphouse_23ku/minato",
        "rows": [{"metric": "rent", "value_man_yen": 12.5}],
        "rows_collected": 1,
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    # No recorded hash to compare: a row-count drift still fails QA.
    verdict = verify_snapshot_file(path, None, recorded_rows=5)
    assert verdict["code"] == VERIFY_ROWS_MISMATCH


def test_verify_snapshot_file_missing_and_unreadable(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert verify_snapshot_file(missing, "ab" * 32)["code"] == VERIFY_FILE_MISSING

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert verify_snapshot_file(broken, "ab" * 32)["code"] == VERIFY_FILE_UNREADABLE

    scalar = tmp_path / "scalar.json"
    scalar.write_text('"just a string"', encoding="utf-8")
    assert verify_snapshot_file(scalar, "ab" * 32)["code"] == VERIFY_FILE_UNREADABLE


def test_recover_stale_runs_rejects_non_positive_window() -> None:
    from datetime import timedelta

    async def _call() -> None:
        await recover_stale_runs(None, stale_after=timedelta(0))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="positive"):
        asyncio.run(_call())


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
    """Create collection_sweeper_test on the local server and apply the batch."""
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
            " (localhost/127.0.0.1) to run the real-Postgres sweeper tests"
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
        # exactly like the worker / ledger integration suites.
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


async def _insert_run(
    pool: asyncpg.Pool,
    source_key: str,
    *,
    status: str,
    started_at_offset_seconds: int | None = None,
    rows_collected: int = 0,
    snapshot_hash: str | None = None,
) -> UUID:
    """Insert one run row; running rows get a started_at relative to now()."""
    async with pool.acquire() as conn:
        if status == "running" and started_at_offset_seconds is not None:
            return await conn.fetchval(
                "insert into public.collection_runs"
                " (source_key, source_type, status, rows_collected, snapshot_hash,"
                "  started_at, completed_at)"
                " values ($1, 'aggregate_authorized', $2, $3, $4,"
                "         now() + ($5 || ' seconds')::interval, null)"
                " returning id",
                source_key,
                status,
                rows_collected,
                snapshot_hash,
                str(started_at_offset_seconds),
            )
        return await conn.fetchval(
            "insert into public.collection_runs"
            " (source_key, source_type, status, rows_collected, snapshot_hash,"
            "  started_at, completed_at)"
            " values ($1, 'aggregate_authorized', $2, $3, $4, null, null)"
            " returning id",
            source_key,
            status,
            rows_collected,
            snapshot_hash,
        )


async def _fetch_run(pool: asyncpg.Pool, run_id: UUID) -> asyncpg.Record:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "select id, source_key, status, rows_collected, snapshot_hash,"
            " error_message, started_at, completed_at"
            " from public.collection_runs where id = $1",
            run_id,
        )


async def _swept_audit_rows(pool: asyncpg.Pool) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select actor_user_id, action, target_type, target_id, summary"
            " from public.audit_events where action = $1 order by occurred_at, id",
            ACTION_SWEPT,
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


@pytestmark_db
async def test_recover_stale_run_flips_to_failed_with_audit(pool: asyncpg.Pool) -> None:
    stale_id = await _insert_run(pool, "jphouse_23ku/minato", status="running",
                                 started_at_offset_seconds=-7200)  # 2h ago
    fresh_id = await _insert_run(pool, "jphouse_23ku/shinjuku", status="running",
                                 started_at_offset_seconds=-60)  # 1min ago
    queued_id = await _insert_run(pool, "jphouse_23ku/taito", status="queued")

    from datetime import timedelta

    events = await recover_stale_runs(pool, stale_after=timedelta(hours=1))
    assert len(events) == 1
    event = events[0]
    assert event.action == ACTION_RECOVERED
    assert event.run_id == str(stale_id)
    assert event.source_key == "jphouse_23ku/minato"

    stale = await _fetch_run(pool, stale_id)
    assert stale["status"] == "failed"
    assert stale["completed_at"] is not None
    assert stale["started_at"] is not None
    assert "[swept]" in (stale["error_message"] or "")
    assert len(stale["error_message"] or "") <= 2000

    # Fresh running run and queued run are untouched.
    fresh = await _fetch_run(pool, fresh_id)
    assert fresh["status"] == "running" and fresh["completed_at"] is None
    queued = await _fetch_run(pool, queued_id)
    assert queued["status"] == "queued" and queued["completed_at"] is None

    audits = await _swept_audit_rows(pool)
    assert len(audits) == 1
    assert audits[0]["target_type"] == "collection_run"
    assert audits[0]["target_id"] == str(stale_id)
    assert audits[0]["actor_user_id"] is None  # system watchdog
    assert audits[0]["summary"]["code"] == "stale_timeout"
    assert audits[0]["summary"]["status"] == "failed"


@pytestmark_db
async def test_second_sweep_is_idempotent_noop(pool: asyncpg.Pool) -> None:
    await _insert_run(pool, "jphouse_23ku/minato", status="running",
                      started_at_offset_seconds=-7200)
    from datetime import timedelta

    first = await recover_stale_runs(pool, stale_after=timedelta(hours=1))
    assert len(first) == 1
    second = await recover_stale_runs(pool, stale_after=timedelta(hours=1))
    assert second == ()
    assert len(await _swept_audit_rows(pool)) == 1


@pytestmark_db
async def test_dry_run_reports_and_writes_nothing(pool: asyncpg.Pool) -> None:
    stale_id = await _insert_run(pool, "jphouse_23ku/minato", status="running",
                                 started_at_offset_seconds=-7200)
    from datetime import timedelta

    events = await recover_stale_runs(
        pool, stale_after=timedelta(hours=1), dry_run=True
    )
    assert len(events) == 1
    assert events[0].action == ACTION_DRY_RUN
    assert events[0].run_id == str(stale_id)

    row = await _fetch_run(pool, stale_id)
    assert row["status"] == "running"
    assert await _swept_audit_rows(pool) == []


@pytestmark_db
async def test_concurrent_sweepers_never_double_recover(pool: asyncpg.Pool) -> None:
    from datetime import timedelta

    ids = [
        await _insert_run(pool, f"jphouse_23ku/ward-{i}", status="running",
                          started_at_offset_seconds=-7200)
        for i in range(3)
    ]
    # Two sweepers, each capped at 2 rows: FOR UPDATE SKIP LOCKED splits the
    # batch; together they recover exactly the 3 stale rows, never a duplicate.
    results = await asyncio.gather(
        recover_stale_runs(pool, stale_after=timedelta(hours=1), limit=2),
        recover_stale_runs(pool, stale_after=timedelta(hours=1), limit=2),
    )
    recovered = [e for batch in results for e in batch]
    assert len(recovered) == 3
    assert len({e.run_id for e in recovered}) == 3
    assert {e.run_id for e in recovered} == {str(i) for i in ids}

    for run_id in ids:
        row = await _fetch_run(pool, run_id)
        assert row["status"] == "failed"
    assert len(await _swept_audit_rows(pool)) == 3


# ---------------------------------------------------------------------------
# snapshot hash QA (integration: DB rows + fabricated data/collected tree)
# ---------------------------------------------------------------------------


def _snapshot_content(source_key: str, *, rows: int, value: float = 12.5) -> dict:
    return {
        "source_key": source_key,
        "config": "configs/jphouse_23ku/fake.json",
        "rows": [{"metric": "rent", "value_man_yen": value} for _ in range(rows)],
        "rows_collected": rows,
        "parser_version": "jphouse-local-readin-v1",
        "collected_at": "2026-09-05T00:00:00+00:00",
    }


async def _seed_succeeded(
    pool: asyncpg.Pool, source_key: str, *, rows: int = 1, digest: str
) -> UUID:
    return await _insert_run(
        pool,
        source_key,
        status="succeeded",
        rows_collected=rows,
        snapshot_hash=digest,
    )


@pytestmark_db
async def test_verify_snapshot_hashes_ok_and_missing(tmp_path: Path, pool: asyncpg.Pool) -> None:
    ok_key = "jphouse_23ku/verify-ok"
    ok_snapshot = _snapshot_content(ok_key, rows=2)
    ok_digest = hashlib.sha256(canonical_snapshot_payload(ok_snapshot)).hexdigest()
    ok_run = await _seed_succeeded(pool, ok_key, rows=2, digest=ok_digest)
    ok_path = tmp_path / "data/collected/jphouse_runs/jphouse_23ku/verify-ok.json"
    ok_path.parent.mkdir(parents=True)
    ok_path.write_text(json.dumps(ok_snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    missing_key = "jphouse_23ku/verify-missing"
    missing_digest = hashlib.sha256(
        canonical_snapshot_payload(_snapshot_content(missing_key, rows=1))
    ).hexdigest()
    missing_run = await _seed_succeeded(pool, missing_key, rows=1, digest=missing_digest)

    # A succeeded fixture run has no file-backed snapshot and is skipped.
    await _seed_succeeded(
        pool,
        "fixture/anything",
        rows=1,
        digest=hashlib.sha256(b"fixture").hexdigest(),
    )

    events = await verify_snapshot_hashes(pool, repo_root=tmp_path)
    by_run = {e.run_id: e for e in events}
    assert by_run[str(ok_run)].code == VERIFY_OK
    assert by_run[str(ok_run)].ok is True
    assert by_run[str(ok_run)].computed_hash == ok_digest
    assert by_run[str(ok_run)].snapshot_rel == (
        "data/collected/jphouse_runs/jphouse_23ku/verify-ok.json"
    )
    assert by_run[str(missing_run)].code == VERIFY_FILE_MISSING
    assert by_run[str(missing_run)].ok is False
    # fixture/anything never appears: not file-backed, out of QA scope.
    assert len(events) == 2


@pytestmark_db
async def test_verify_snapshot_hashes_detects_tamper(
    tmp_path: Path, pool: asyncpg.Pool
) -> None:
    key = "jphouse_23ku/verify-tampered"
    original = _snapshot_content(key, rows=1, value=12.5)
    digest = hashlib.sha256(canonical_snapshot_payload(original)).hexdigest()
    run_id = await _seed_succeeded(pool, key, rows=1, digest=digest)
    # The file on disk diverges from what the run recorded.
    tampered = _snapshot_content(key, rows=1, value=99.9)
    path = tmp_path / "data/collected/jphouse_runs/jphouse_23ku/verify-tampered.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")

    events = await verify_snapshot_hashes(pool, repo_root=tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event.run_id == str(run_id)
    assert event.code == VERIFY_HASH_MISMATCH
    assert event.ok is False
    assert event.recorded_hash == digest
    assert event.computed_hash != digest
