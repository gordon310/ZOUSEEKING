"""Live quota transactions against an explicitly configured disposable PostgreSQL.

Run with QUOTA_TEST_DATABASE_URL pointing to localhost; all fixture data is
synthetic and isolated in zouseeking_current_quota_test.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest

from backend.app.auth import AuthUser
from backend.app.usage import quota
from backend.app.usage.ledger import QuotaExceeded
from tests.support.pg_bootstrap import (
    bootstrap_and_migrate, configured_database_url, database_url,
    require_postgres_or_skip,
)

BASE_URL = configured_database_url("QUOTA_TEST_DATABASE_URL")
TEST_DB = "zouseeking_current_quota_test"


@pytest.fixture(scope="module")
def quota_database():
    asyncio.run(require_postgres_or_skip(BASE_URL))
    asyncio.run(bootstrap_and_migrate(BASE_URL, TEST_DB))
    url = database_url(BASE_URL, TEST_DB)

    async def seed():
        conn = await asyncpg.connect(url)
        try:
            for plan in ("free_c", "c_plus"):
                await conn.execute(
                    """insert into public.pricing_plans
                       (plan_code, name, audience, monthly_query_limit, monthly_report_quota, subscription_slots, export_rows_monthly)
                       values($1, $1, 'c', 0, 0, 0, 0)""", plan,
                )
            await conn.execute(
                """insert into public.plan_entitlements(plan_code, metric, period, limit_units)
                   values('free_c', 'query', 'day', 3),
                         ('c_plus', 'query', 'month', 100),
                         ('c_plus', 'report', 'month', 1)"""
            )
        finally:
            await conn.close()

    asyncio.run(seed())
    return url


async def make_user(conn, *, tier="c_plus", status="active", end="future", start="past"):
    user = AuthUser(uuid4(), "", "")
    await conn.execute("insert into auth.users(id, email) values($1, $2)", user.user_id, f"{user.user_id}@fixture.invalid")
    await conn.execute("update public.user_profiles set membership_tier=$2, audience='c' where user_id=$1", user.user_id, tier)
    if status:
        await conn.execute(
            """insert into public.subscriptions
               (user_id, product_code, price_version, currency, amount_minor, status,
                current_period_start, current_period_end)
               values($1, 'c_plus_monthly', 1, 'JPY', 990, $2,
                 case when $4='future' then now() + interval '1 day' else now() - interval '1 day' end,
                 case when $3='future' then now() + interval '60 days'
                      when $3='expired' then now() - interval '1 day' else null end)""",
            user.user_id, status, end, start,
        )
    return user


async def consume(conn, user, key="one", *, metric="report", fingerprint=None):
    async with conn.transaction():
        return await quota.consume_current_entitlement(
            conn, user=user, metric=metric, units=1,
            idempotency_key=f"{metric}:{key}",
            fingerprint=fingerprint or f"{metric}:{key}",
        )


async def counts(conn, user):
    return tuple(await conn.fetchrow(
        """select
           (select count(*) from public.usage_events where scope_key=$1) as events,
           (select count(*) from public.usage_idempotency where scope_key=$1) as keys,
           (select coalesce(sum(consumed_units),0) from public.usage_quotas where scope_key=$1) as consumed""",
        f"user:{user.user_id}",
    ))


@pytest.mark.parametrize("tier,period_length", [("free", 10), ("c_plus", 7)])
def test_query_and_preview_share_plan_period_and_counter(quota_database, tier, period_length):
    async def run():
        conn = await asyncpg.connect(quota_database)
        try:
            user = await make_user(conn, tier=tier)
            first = await consume(conn, user, metric="query")
            second = await consume(conn, user, metric="free_preview")
            assert first.period_key == second.period_key
            assert len(second.period_key) == period_length
            assert (first.used, second.used) == (1, 2)
            assert await counts(conn, user) == (2, 2, 2)
        finally:
            await conn.close()
    asyncio.run(run())


def test_free_query_daily_quota_resets_at_utc8_boundary(quota_database, monkeypatch):
    async def run():
        conn = await asyncpg.connect(quota_database)
        original = quota.current_period_key
        try:
            user = await make_user(conn, tier="free", status=None)
            before = datetime(2026, 9, 30, 15, 59, tzinfo=timezone.utc)
            monkeypatch.setattr(quota, "current_period_key", lambda value, period: original(before, period))
            for key in ("one", "two", "three"):
                assert (await consume(conn, user, key, metric="query")).period_key == "2026-09-30"
            with pytest.raises(QuotaExceeded):
                await consume(conn, user, "four", metric="query")
            after = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
            monkeypatch.setattr(quota, "current_period_key", lambda value, period: original(after, period))
            result = await consume(conn, user, "four", metric="query")
            assert (result.period_key, result.used) == ("2026-10-01", 1)
        finally:
            await conn.close()
    asyncio.run(run())


@pytest.mark.parametrize("status,end,start", [
    (None, "future", "past"), ("canceled", "future", "past"),
    ("past_due", "future", "past"), ("active", "expired", "past"),
    ("trialing", "expired", "past"), ("active", "null", "past"),
    ("active", "future", "future"),
])
def test_stale_plus_profile_does_not_grant_report_credit(quota_database, status, end, start):
    async def run():
        conn = await asyncpg.connect(quota_database)
        try:
            user = await make_user(conn, status=status, end=end, start=start)
            with pytest.raises(QuotaExceeded):
                await consume(conn, user)
            assert await counts(conn, user) == (0, 0, 0)
        finally:
            await conn.close()
    asyncio.run(run())


def test_trialing_subscription_with_stale_free_profile_gets_personal_credit(quota_database):
    async def run():
        conn = await asyncpg.connect(quota_database)
        try:
            user = await make_user(conn, tier="free", status="trialing")
            result = await consume(conn, user)
            assert (result.status, result.used, result.limit) == ("consumed", 1, 1)
        finally:
            await conn.close()
    asyncio.run(run())


def test_report_retry_after_rollover_and_expiry_is_not_charged_again(quota_database, monkeypatch):
    async def run():
        conn = await asyncpg.connect(quota_database)
        try:
            user = await make_user(conn)
            monkeypatch.setattr(quota, "current_period_key", lambda value, period: "2026-09")
            await consume(conn, user)
            monkeypatch.setattr(quota, "current_period_key", lambda value, period: "2026-10")
            await conn.execute("update public.subscriptions set status='canceled', current_period_end=now()-interval '1 day' where user_id=$1", user.user_id)
            result = await consume(conn, user)
            assert (result.status, result.period_key, result.used) == ("duplicate", "2026-09", 1)
            assert await counts(conn, user) == (1, 1, 1)
            assert await conn.fetchval("select count(*) from public.usage_quotas where scope_key=$1 and period_key='2026-10'", f"user:{user.user_id}") == 0
        finally:
            await conn.close()
    asyncio.run(run())


@pytest.mark.parametrize("limit,reserved", [(0, 0), (1, 1)])
def test_zero_or_reserved_report_quota_writes_no_consume(quota_database, limit, reserved):
    async def run():
        conn = await asyncpg.connect(quota_database)
        try:
            user = await make_user(conn)
            async with conn.transaction():
                await conn.execute("update public.plan_entitlements set limit_units=$1 where plan_code='c_plus' and metric='report'", limit)
                if reserved:
                    await conn.execute(
                        """insert into public.usage_quotas(scope_key, usage_kind, period_key, limit_units, reserved_units)
                           values($1, 'report', $2, 1, 1)""",
                        f"user:{user.user_id}", quota.current_period_key(datetime.now(timezone.utc), "month"),
                    )
                with pytest.raises(QuotaExceeded):
                    await consume(conn, user)
                assert await counts(conn, user) == (0, 0, 0)
                await conn.execute("update public.plan_entitlements set limit_units=1 where plan_code='c_plus' and metric='report'")
        finally:
            await conn.close()
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["distinct_reports", "same_report", "same_fingerprint", "key_conflict"])
def test_concurrent_last_credit_and_idempotency_constraints(quota_database, scenario):
    async def run():
        pool = await asyncpg.create_pool(quota_database, min_size=2, max_size=8)
        try:
            async with pool.acquire() as conn:
                user = await make_user(conn)
            async def request(index):
                key = "one" if scenario in ("same_report", "key_conflict") else str(index)
                fingerprint = "one" if scenario in ("same_report", "same_fingerprint") else str(index)
                async with pool.acquire() as conn:
                    try:
                        result = await consume(conn, user, key, fingerprint=fingerprint)
                        return result.status
                    except QuotaExceeded:
                        return "quota_exceeded"
                    except ValueError:
                        return "conflict"
            results = await asyncio.gather(*(request(index) for index in range(8)))
            assert results.count("consumed") == 1
            if scenario == "distinct_reports":
                assert results.count("quota_exceeded") == 7
            elif scenario == "key_conflict":
                assert results.count("conflict") == 7
            else:
                assert results.count("duplicate") == 7
            async with pool.acquire() as conn:
                assert await counts(conn, user) == (1, 1, 1)
        finally:
            await pool.close()
    asyncio.run(run())


def test_new_report_month_uses_new_bucket_but_prior_report_does_not(quota_database, monkeypatch):
    async def run():
        conn = await asyncpg.connect(quota_database)
        try:
            user = await make_user(conn)
            monkeypatch.setattr(quota, "current_period_key", lambda value, period: "2026-09")
            await consume(conn, user, "september")
            monkeypatch.setattr(quota, "current_period_key", lambda value, period: "2026-10")
            replay = await consume(conn, user, "september")
            october = await consume(conn, user, "october")
            assert (replay.status, replay.period_key) == ("duplicate", "2026-09")
            assert (october.status, october.period_key, october.used) == ("consumed", "2026-10", 1)
            assert await counts(conn, user) == (2, 2, 2)
        finally:
            await conn.close()
    asyncio.run(run())
