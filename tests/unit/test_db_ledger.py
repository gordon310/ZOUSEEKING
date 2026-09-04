"""Tests for ``backend.app.usage.db_ledger.PostgresLedger``.

The adapter needs the real V1 schema, so the tests apply
``20260905000100`` (organizations prerequisite) and ``20260905000300``
(usage ledger) to a fresh disposable database named ``usage_ledger_test`` on
the server referenced by ``DATABASE_URL``, then exercise every public
``PostgresLedger`` method against real PostgreSQL.

* Without ``DATABASE_URL`` the whole module is skipped.
* For safety, real-database tests only run when the ``DATABASE_URL`` host is
  ``localhost`` / ``127.0.0.1`` / ``::1`` (the module never drops a database
  on a remote server).  Point ``DATABASE_URL`` at the disposable container
  when validating locally.

Kind vocabulary note: the V1 tables only accept the frozen product kinds
``query/report/stats_query/export_row/subscription_slot``, so this suite uses
those tokens (the offline enum's ``analysis/subscription/export`` members have
no column value).  ``UsageKind.QUERY`` / ``UsageKind.REPORT`` are exercised
directly to prove enum members whose value is in the CHECK set are accepted.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from backend.app.usage.db_ledger import PostgresLedger
from backend.app.usage.ledger import (
    IdempotencyConflict,
    LedgerSummary,
    QuotaExceeded,
    ReservationNotFound,
    ReservationStateError,
    Scope,
    UsageKind,
)

UTC = timezone.utc

OWNER_ID = UUID("00000000-0000-0000-0000-000000000030")
MEMBER_A = UUID("00000000-0000-0000-0000-000000000031")
MEMBER_B = UUID("00000000-0000-0000-0000-000000000032")
ORG_ID = UUID("00000000-0000-0000-0000-000000000040")

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT / "supabase" / "migrations" / "20260905000100_v1_organizations.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000300_v1_usage_ledger.sql",
]

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

pytestmark = pytest.mark.asyncio


def _db_path(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _local_server(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _is_valid_test_url(url: str) -> bool:
    return bool(url) and _local_server(url)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


async def _bootstrap_and_migrate(url: str) -> None:
    """Create usage_ledger_test on the local server and apply the V1 batch."""
    admin = await asyncpg.connect(url, database="postgres")
    try:
        await admin.execute("drop database if exists usage_ledger_test with (force)")
        await admin.execute("create database usage_ledger_test")
    finally:
        await admin.close()

    test_url = _db_path(url, "usage_ledger_test")
    conn = await asyncpg.connect(test_url)
    try:
        bootstrap = """
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
        -- Supabase exposes auth.uid() inside its initial database only; freshly
        -- created test databases must provide the stub before RLS policies that
        -- reference it can be created by the migrations below.
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
        await conn.execute(bootstrap)
        for path in MIGRATIONS:
            await conn.execute(path.read_text(encoding="utf-8"))
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Apply the V1 migrations once to a fresh usage_ledger_test database."""
    if not _is_valid_test_url(DATABASE_URL):
        pytest.skip(
            "DATABASE_URL must point at a disposable local PostgreSQL server"
            " (localhost/127.0.0.1) to run the real-Postgres ledger tests"
        )
    asyncio.run(_bootstrap_and_migrate(DATABASE_URL))
    return _db_path(DATABASE_URL, "usage_ledger_test")


@pytest_asyncio.fixture
async def test_pool(_migrated_database: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(_migrated_database)
    async with pool.acquire() as conn:
        for user_id, email in (
            (OWNER_ID, "owner@example.com"),
            (MEMBER_A, "member-a@example.com"),
            (MEMBER_B, "member-b@example.com"),
        ):
            await conn.execute(
                "insert into auth.users (id, email) values ($1, $2)"
                " on conflict (id) do nothing",
                user_id,
                email,
            )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def ledger(test_pool: asyncpg.Pool) -> PostgresLedger:
    return PostgresLedger(pool=test_pool)


@pytest_asyncio.fixture(autouse=True)
async def _wipe_tables(test_pool: asyncpg.Pool) -> None:
    async with test_pool.acquire() as conn:
        async with conn.transaction():
            # usage_events is append-only: disable its guard before truncating.
            await conn.execute(
                "alter table public.usage_events"
                " disable trigger enforce_usage_events_append_only"
            )
            await conn.execute(
                "truncate table"
                " public.usage_idempotency, public.usage_events, public.usage_quotas"
                " restart identity cascade"
            )
            await conn.execute(
                "alter table public.usage_events"
                " enable trigger enforce_usage_events_append_only"
            )


# --------------------------------------------------------------------------
# seed helpers (raw SQL set-up only; assertions always go through the ledger)
# --------------------------------------------------------------------------


async def provision_quota(
    pool: asyncpg.Pool,
    *,
    scope: Scope,
    kind: str,
    limit: int,
    period_key: str,
    consumed: int = 0,
    reserved: int = 0,
) -> None:
    """Provision a usage_quotas row the way the entitlement store would."""
    scope_key = f"user:{scope.id}" if scope.kind == "owner" else f"org:{scope.id}"
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into public.usage_quotas"
            " (scope_key, usage_kind, period_key, limit_units, consumed_units, reserved_units)"
            " values ($1, $2, $3, $4, $5, $6)"
            " on conflict (scope_key, usage_kind, period_key) do update"
            " set limit_units = excluded.limit_units,"
            "     consumed_units = excluded.consumed_units,"
            "     reserved_units = excluded.reserved_units",
            scope_key,
            kind,
            period_key,
            limit,
            consumed,
            reserved,
        )


async def count_events(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("select count(*) from public.usage_events")


async def count_idempotency(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("select count(*) from public.usage_idempotency")


# --------------------------------------------------------------------------
# period semantics
# --------------------------------------------------------------------------


async def test_day_period_uses_utc8_boundary(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    # 2026-08-31 15:59 UTC == 2026-08-31 23:59 UTC+8 (day one)
    before = await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
        request_key="day-before", actor_user_id=OWNER_ID,
        occurred_at=datetime(2026, 8, 31, 15, 59, tzinfo=UTC), period="day",
    )
    # 2026-08-31 16:00 UTC == 2026-09-01 00:00 UTC+8 (day two)
    after = await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
        request_key="day-after", actor_user_id=OWNER_ID,
        occurred_at=datetime(2026, 8, 31, 16, 0, tzinfo=UTC), period="day",
    )
    assert before.period_start.day == 31
    assert after.period_start.day == 1
    assert before.period_id != after.period_id
    assert before.status == after.status == "consumed"


async def test_month_period_and_summary_are_numeric(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 16, 0, tzinfo=UTC)  # 2026-09-01 UTC+8
    result = await ledger.consume(
        scope=scope, kind=UsageKind.REPORT, units=2, limit=3,
        request_key="month-1", actor_user_id=OWNER_ID, occurred_at=now, period="month",
    )
    summary = await ledger.summary(
        scope=scope, kind=UsageKind.REPORT, occurred_at=now, period="month"
    )
    assert isinstance(summary, LedgerSummary)
    assert (summary.consumed, summary.reserved, summary.limit) == (2, 0, 3)
    assert result.period_start.month == 9
    assert summary.period_start.month == 9


async def test_summary_of_untouched_period_is_zero(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    summary = await ledger.summary(
        scope=scope, kind="stats_query", occurred_at=now, period="day"
    )
    assert (summary.consumed, summary.reserved, summary.limit) == (0, 0, 0)


# --------------------------------------------------------------------------
# idempotency and quota
# --------------------------------------------------------------------------


async def test_consume_is_idempotent_and_rejects_fingerprint_conflicts(
    ledger, test_pool
) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    first = await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
        request_key="same-key", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    duplicate = await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
        request_key="same-key", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    assert duplicate.status == "duplicate"
    assert duplicate.event_id == first.event_id
    summary = await ledger.summary(
        scope=scope, kind=UsageKind.QUERY, occurred_at=now, period="day"
    )
    assert summary.consumed == 1
    # Only one event and one registry row exist for the pair.
    assert await count_events(test_pool) == 1
    assert await count_idempotency(test_pool) == 1

    # Same key, different parameters -> conflict.
    with pytest.raises(IdempotencyConflict):
        await ledger.consume(
            scope=scope, kind=UsageKind.QUERY, units=2, limit=5,
            request_key="same-key", actor_user_id=OWNER_ID, occurred_at=now, period="day",
        )


async def test_quota_rejection_does_not_mutate_counter_or_events(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=1,
        request_key="accepted", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )

    # units=2 gives the request a distinct fingerprint (units is part of it),
    # so this is a genuine capacity attempt rather than an identical replay.
    with pytest.raises(QuotaExceeded):
        await ledger.consume(
            scope=scope, kind=UsageKind.QUERY, units=2, limit=1,
            request_key="rejected", actor_user_id=OWNER_ID, occurred_at=now, period="day",
        )

    summary = await ledger.summary(
        scope=scope, kind=UsageKind.QUERY, occurred_at=now, period="day"
    )
    assert (summary.consumed, summary.reserved, summary.limit) == (1, 0, 1)
    assert await count_events(test_pool) == 1
    assert await count_idempotency(test_pool) == 1


async def test_consume_without_provisioned_row_and_no_limit_is_rejected(
    ledger, test_pool
) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    with pytest.raises(QuotaExceeded):
        await ledger.consume(
            scope=scope, kind=UsageKind.QUERY, units=1,
            request_key="unprovisioned", actor_user_id=OWNER_ID,
            occurred_at=now, period="day",
        )
    summary = await ledger.summary(
        scope=scope, kind=UsageKind.QUERY, occurred_at=now, period="day"
    )
    assert summary.consumed == 0


async def test_scope_isolation_owner_and_org(ledger, test_pool) -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    owner = await ledger.consume(
        scope=Scope.owner(OWNER_ID), kind=UsageKind.QUERY, units=1, limit=1,
        request_key="same-key", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    organization = await ledger.consume(
        scope=Scope.organization(ORG_ID), kind=UsageKind.QUERY, units=1, limit=1,
        request_key="same-key", actor_user_id=MEMBER_A, occurred_at=now, period="day",
    )
    assert owner.status == organization.status == "consumed"
    assert owner.event_id != organization.event_id
    assert owner.scope != organization.scope


async def test_limit_mismatch_on_existing_row_conflicts(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
        request_key="limit-1", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    with pytest.raises(IdempotencyConflict):
        await ledger.consume(
            scope=scope, kind=UsageKind.QUERY, units=1, limit=9,
            request_key="limit-2", actor_user_id=OWNER_ID, occurred_at=now, period="day",
        )


async def test_provisioned_row_is_authoritative(ledger, test_pool) -> None:
    """Without a limit argument the row's limit_units governs capacity."""
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    await provision_quota(
        test_pool, scope=scope, kind="stats_query", limit=3, period_key="2026-08-31"
    )
    result = await ledger.consume(
        scope=scope, kind="stats_query", units=1,
        request_key="provisioned-1", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    assert result.limit == 3
    summary = await ledger.summary(
        scope=scope, kind="stats_query", occurred_at=now, period="day"
    )
    assert (summary.consumed, summary.limit) == (1, 3)
    # units=3 gives a distinct fingerprint from the units=1 consume above, so
    # this is a genuine capacity attempt against the row's limit of 3.
    with pytest.raises(QuotaExceeded):
        await ledger.consume(
            scope=scope, kind="stats_query", units=3,
            request_key="provisioned-2", actor_user_id=OWNER_ID, occurred_at=now, period="day",
        )


# --------------------------------------------------------------------------
# reservations
# --------------------------------------------------------------------------


async def test_reservation_commit_uses_original_period_and_is_idempotent(
    ledger, test_pool
) -> None:
    scope = Scope.owner(OWNER_ID)
    reserve_at = datetime(2026, 8, 31, 15, 59, tzinfo=UTC)  # 2026-08-31 UTC+8
    commit_at = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)  # 2026-09-02 UTC+8

    reserved = await ledger.reserve(
        scope=scope, kind="stats_query", units=2, limit=3,
        request_key="reservation-1", actor_user_id=OWNER_ID,
        occurred_at=reserve_at, period="day",
    )
    committed = await ledger.commit(
        scope=scope, kind="stats_query", units=2, limit=3,
        request_key="commit-1", actor_user_id=OWNER_ID,
        occurred_at=commit_at, period="day", reservation_key="reservation-1",
    )
    duplicate = await ledger.commit(
        scope=scope, kind="stats_query", units=2, limit=3,
        request_key="commit-1", actor_user_id=OWNER_ID,
        occurred_at=commit_at, period="day", reservation_key="reservation-1",
    )

    assert reserved.status == "reserved"
    assert committed.status == "committed"
    # Commit lands in the original (reserve) period even across the day line.
    assert committed.period_start == reserved.period_start
    assert duplicate.status == "duplicate"
    assert duplicate.event_id == committed.event_id

    summary_reserved_day = await ledger.summary(
        scope=scope, kind="stats_query", occurred_at=reserve_at, period="day"
    )
    summary_commit_day = await ledger.summary(
        scope=scope, kind="stats_query", occurred_at=commit_at, period="day"
    )
    assert summary_reserved_day.consumed == 2
    assert summary_reserved_day.reserved == 0
    assert summary_commit_day.consumed == 0  # next UTC+8 day untouched


async def test_release_returns_capacity_and_state_transitions_are_safe(
    ledger, test_pool
) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    await ledger.reserve(
        scope=scope, kind="export_row", units=1, limit=1,
        request_key="reservation-2", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    released = await ledger.release(
        scope=scope, kind="export_row", units=1, limit=1,
        request_key="release-1", actor_user_id=OWNER_ID,
        occurred_at=now, period="day", reservation_key="reservation-2",
    )
    assert released.status == "released"
    summary = await ledger.summary(
        scope=scope, kind="export_row", occurred_at=now, period="day"
    )
    assert summary.reserved == 0

    # Same release replayed -> duplicate; a new release -> state error.
    duplicate = await ledger.release(
        scope=scope, kind="export_row", units=1, limit=1,
        request_key="release-1", actor_user_id=OWNER_ID,
        occurred_at=now, period="day", reservation_key="reservation-2",
    )
    assert duplicate.status == "duplicate"
    with pytest.raises(ReservationStateError):
        await ledger.release(
            scope=scope, kind="export_row", units=1, limit=1,
            request_key="release-2", actor_user_id=OWNER_ID,
            occurred_at=now, period="day", reservation_key="reservation-2",
        )

    # Committing an already-released reservation is also a state error.
    with pytest.raises(ReservationStateError):
        await ledger.commit(
            scope=scope, kind="export_row", units=1, limit=1,
            request_key="commit-after-release", actor_user_id=OWNER_ID,
            occurred_at=now, period="day", reservation_key="reservation-2",
        )


async def test_unknown_reservation_and_units_mismatch(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    with pytest.raises(ReservationNotFound):
        await ledger.commit(
            scope=scope, kind=UsageKind.QUERY, units=1, limit=1,
            request_key="commit-ghost", actor_user_id=OWNER_ID,
            occurred_at=now, period="day", reservation_key="no-such-reservation",
        )

    await ledger.reserve(
        scope=scope, kind=UsageKind.QUERY, units=2, limit=5,
        request_key="reservation-3", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    with pytest.raises(IdempotencyConflict):
        await ledger.commit(
            scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
            request_key="commit-wrong-units", actor_user_id=OWNER_ID,
            occurred_at=now, period="day", reservation_key="reservation-3",
        )


async def test_release_without_active_reservation_not_found(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    with pytest.raises(ReservationNotFound):
        await ledger.release(
            scope=scope, kind=UsageKind.QUERY, units=1, limit=1,
            request_key="release-ghost", actor_user_id=OWNER_ID,
            occurred_at=now, period="day", reservation_key="ghost",
        )


# --------------------------------------------------------------------------
# append-only / atomicity
# --------------------------------------------------------------------------


async def test_events_are_append_only(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    result = await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
        request_key="append-1", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    async with test_pool.acquire() as conn:
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "update public.usage_events set units = 99 where id = $1", result.event_id
            )
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "delete from public.usage_events where id = $1", result.event_id
            )


async def test_quota_rows_reflect_consumed_and_reserved(ledger, test_pool) -> None:
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    await ledger.consume(
        scope=scope, kind=UsageKind.QUERY, units=3, limit=10,
        request_key="count-1", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )
    await ledger.reserve(
        scope=scope, kind=UsageKind.QUERY, units=2, limit=10,
        request_key="count-2", actor_user_id=OWNER_ID, occurred_at=now, period="day",
    )

    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "select consumed_units, reserved_units, limit_units from public.usage_quotas"
            " where scope_key = $1 and usage_kind = 'query' and period_key = '2026-08-31'",
            f"user:{OWNER_ID}",
        )
    assert (row["consumed_units"], row["reserved_units"], row["limit_units"]) == (3, 2, 10)


# --------------------------------------------------------------------------
# concurrency: shared org quota must never oversell
# --------------------------------------------------------------------------


async def test_eight_way_concurrent_consume_limit_one_org_scope(
    ledger, test_pool
) -> None:
    """Eight *distinct* members race for the last org-shared unit.

    Distinct actors produce distinct fingerprints (the actor is part of the
    fingerprint), so this is a genuine capacity race in the V1 registry model
    (the spec's shared B-side quota).  Exactly one member wins.
    """
    scope = Scope.organization(ORG_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    actors = [MEMBER_A, MEMBER_B] + [uuid4() for _ in range(6)]
    async with test_pool.acquire() as conn:
        await conn.executemany(
            "insert into auth.users (id, email) values ($1, $2)"
            " on conflict (id) do nothing",
            [(actor, f"race-{i}@example.com") for i, actor in enumerate(actors)],
        )

    def attempt(index: int):
        async def _run() -> str:
            try:
                await ledger.consume(
                    scope=scope, kind=UsageKind.QUERY, units=1, limit=1,
                    request_key=f"race-{index}", actor_user_id=actors[index],
                    occurred_at=now, period="day",
                )
                return "accepted"
            except QuotaExceeded:
                return "quota"
            except Exception:
                return "error"
        return _run()

    outcomes = await asyncio.gather(*[attempt(i) for i in range(8)])
    assert outcomes.count("accepted") == 1
    assert outcomes.count("quota") == 7
    summary = await ledger.summary(
        scope=scope, kind=UsageKind.QUERY, occurred_at=now, period="day"
    )
    assert (summary.consumed, summary.limit) == (1, 1)


async def test_identical_concurrent_requests_dedupe_to_one_consume(
    ledger, test_pool
) -> None:
    """The same logical request racing under *different* keys consumes once.

    The V1 registry records one fingerprint per (scope, kind, operation), so
    identical concurrent requests (same actor, units, kind, period) are
    deduplicated to a single metered consume even when they carry different
    idempotency keys.  This is stricter than the offline model (which keys by
    request_key only) and is documented as the V1 dedup contract.
    """
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    def attempt(index: int):
        async def _run() -> str:
            result = await ledger.consume(
                scope=scope, kind=UsageKind.QUERY, units=1, limit=5,
                request_key=f"identical-{index}", actor_user_id=OWNER_ID,
                occurred_at=now, period="day",
            )
            return result.status
        return _run()

    outcomes = await asyncio.gather(*[attempt(i) for i in range(8)])
    assert outcomes.count("consumed") == 1
    assert outcomes.count("duplicate") == 7
    summary = await ledger.summary(
        scope=scope, kind=UsageKind.QUERY, occurred_at=now, period="day"
    )
    assert (summary.consumed, summary.limit) == (1, 5)
    assert await count_events(test_pool) == 1


async def test_same_key_concurrent_replay_returns_duplicate(ledger, test_pool) -> None:
    """A retry that lands while the original is still in flight is safe."""
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    def attempt(_index: int):
        async def _run() -> str:
            result = await ledger.consume(
                scope=scope, kind=UsageKind.QUERY, units=1, limit=1,
                request_key="shared-key", actor_user_id=OWNER_ID,
                occurred_at=now, period="day",
            )
            return result.status
        return _run()

    outcomes = await asyncio.gather(*[attempt(i) for i in range(4)])
    assert outcomes.count("consumed") == 1
    assert outcomes.count("duplicate") == 3
    summary = await ledger.summary(
        scope=scope, kind=UsageKind.QUERY, occurred_at=now, period="day"
    )
    assert (summary.consumed, summary.limit) == (1, 1)
