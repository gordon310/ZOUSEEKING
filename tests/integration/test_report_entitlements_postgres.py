"""Real PostgreSQL evidence for report-specific access and atomic C Plus billing.

The configured server must be disposable and local. The suite creates a uniquely
named database, applies every canonical migration, and drops only that database.
All records are synthetic fixtures; no provider/network generation is performed.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException

from backend.app import main
from backend.app.auth import AuthUser, optional_user, require_user
from backend.app.models import QueryRequest
from tests.support.pg_bootstrap import (
    bootstrap_and_migrate,
    configured_database_url,
    database_url,
    require_postgres_or_skip,
)

PRIVATE_TEXT = "fixture-private-report-payload"


@pytest.fixture(scope="module")
def report_entitlement_database_url():
    base = configured_database_url("REPORT_ENTITLEMENT_TEST_DATABASE_URL", "TEST_DATABASE_URL")
    asyncio.run(require_postgres_or_skip(base))
    database = f"report_entitlements_{uuid4().hex[:12]}"
    asyncio.run(bootstrap_and_migrate(base, database))
    try:
        yield database_url(base, database)
    finally:
        async def cleanup():
            conn = await asyncpg.connect(base, database="postgres")
            try:
                await conn.execute(f"drop database {database} with (force)")
            finally:
                await conn.close()
        asyncio.run(cleanup())


async def seed_report(pool, owner, *, month=1, status="full_report"):
    request = QueryRequest(prefecture="大阪府", city="大阪市", ward="北区", asset_type="塔楼", year=2026, month=month)
    key = f"{owner}::{main.query_key(request.prefecture, request.city, request.ward, request.asset_type, request.year, request.month)}"
    query_id, job_id = uuid4(), uuid4()
    await pool.execute(
        """insert into public.queries
           (id, query_key, owner_user_id, prefecture, city, ward, asset_type, year, month, status)
           values($1,$2,$3,$4,$5,$6,$7,$8,$9,'completed')""",
        query_id, key, owner, request.prefecture, request.city, request.ward,
        request.asset_type, request.year, request.month,
    )
    await pool.execute(
        """insert into public.generation_jobs(id,query_id,status,progress,current_step)
           values($1,$2,'completed',100,'fixture complete')""", job_id, query_id,
    )
    await pool.execute(
        """insert into public.property_reports
           (query_id,owner_user_id,query_key,slug,title,publish_month,markdown,xhs_content,
            sale,rental,images,raw_record,summary,data_sources,report_status,data_class,
            source_period,observed_at,transformation_version,report_version,limitations)
           values($1,$2,$3,$4,'Synthetic access fixture','2026-01',$5,$5,
                  $6::jsonb,'[]','[]',$7::jsonb,'{"title":"Public summary"}','[]',$8,
                  'synthetic_fixture','2026-01',now(),'test-v1','test-v1','Synthetic fixture only')""",
        query_id, owner, key, uuid4().hex, PRIVATE_TEXT,
        json.dumps([{"layout": "1LDK", "amount_yen": 12345678}]),
        json.dumps({"secret": PRIVATE_TEXT}), status,
    )
    return SimpleNamespace(key=key, request=request, query_id=query_id, job_id=job_id)


@pytest_asyncio.fixture
async def scenario(report_entitlement_database_url, monkeypatch):
    pool = await asyncpg.create_pool(report_entitlement_database_url, min_size=2, max_size=12)
    monkeypatch.setattr(main, "get_pool", lambda: pool)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RELEASE_PHASE", "consumer_launch")
    monkeypatch.setenv("QUERY_RATE_LIMIT_PER_HOUR", "1000")
    owner, other = uuid4(), uuid4()
    await pool.execute("insert into auth.users(id) values($1),($2)", owner, other)
    await pool.execute(
        """insert into public.user_profiles(user_id,membership_tier)
           values($1,'c_plus'),($2,'free')
           on conflict(user_id) do update set membership_tier=excluded.membership_tier""", owner, other,
    )
    await pool.execute(
        """insert into public.pricing_plans
           (plan_code,name,monthly_query_limit,monthly_report_quota,subscription_slots,export_rows_monthly)
           values('c_plus','Synthetic C Plus',100,1,0,0)
           on conflict(plan_code) do nothing"""
    )
    await pool.execute(
        """insert into public.plan_entitlements(plan_code,metric,period,limit_units)
           values('c_plus','report','month',1)
           on conflict(plan_code,metric,period) where active do update set limit_units=1"""
    )
    report = await seed_report(pool, owner)
    state = SimpleNamespace(pool=pool, owner=owner, other=other, report=report, user=owner)
    previous_overrides = main.app.dependency_overrides.copy()

    async def optional_auth():
        return AuthUser(state.user, "fixture@example.test", "Fixture") if state.user else None

    async def required_auth():
        user = await optional_auth()
        if user is None:
            raise HTTPException(401, "authentication required")
        return user

    main.app.dependency_overrides[optional_user] = optional_auth
    main.app.dependency_overrides[require_user] = required_auth
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://fixture.test") as client:
            state.client = client
            yield state
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous_overrides)
        await pool.close()


async def subscribe(s, *, status="active", start=None, end=None, null_period=False):
    now = datetime.now(timezone.utc)
    return await s.pool.fetchval(
        """insert into public.subscriptions
           (user_id,product_code,price_version,currency,amount_minor,status,current_period_start,current_period_end)
           values($1,'c_plus_monthly',1,'JPY',100,$2,$3,$4) returning id""",
        s.owner, status,
        None if null_period else start or now - timedelta(days=1),
        None if null_period else end or now + timedelta(days=1),
    )


async def seed_quota(s, *, consumed=0, reserved=0, limit=1, period=None):
    await s.pool.execute(
        """insert into public.usage_quotas(scope_key,usage_kind,period_key,limit_units,consumed_units,reserved_units)
           values($1,'report',$2,$3,$4,$5)
           on conflict(scope_key,usage_kind,period_key) do update set
             limit_units=excluded.limit_units,consumed_units=excluded.consumed_units,reserved_units=excluded.reserved_units""",
        f"user:{s.owner}", period or main._current_month_key(), limit, consumed, reserved,
    )


async def seed_event(s, *, prefix="report:", owner=None, actor="owner", key=None, operation="consume", kind="report", period="2000-01"):
    event_owner = s.owner if owner is None else owner
    event_actor = s.owner if actor == "owner" else actor
    return await s.pool.fetchval(
        """insert into public.usage_events
           (scope_key,usage_kind,operation,units,period_key,idempotency_key,fingerprint,actor_user_id)
           values($1,$2,$3,1,$4,$5,$6,$7) returning id""",
        f"user:{event_owner}", kind, operation, period, uuid4().hex,
        prefix + (s.report.key if key is None else key), event_actor,
    )


async def event_count(s):
    return await s.pool.fetchval("select count(*) from public.usage_events where scope_key=$1", f"user:{s.owner}")


def assert_locked(response, *, embedded=False):
    assert response.status_code == 200, response.text
    report = response.json()["report"] if embedded else response.json()
    assert report is not None
    assert report["locked"] is True
    assert report["unlocked"] is False
    assert not main.LOCKED_REPORT_FIELDS.intersection(report)
    assert PRIVATE_TEXT not in response.text
    assert "12345678" not in response.text


async def assert_all_owner_surfaces(s, *, unlocked):
    responses = [
        (await s.client.post("/api/query", json=s.report.request.model_dump()), True),
        (await s.client.get(f"/api/jobs/{s.report.job_id}"), True),
        (await s.client.get(f"/api/reports/{s.report.key}"), False),
    ]
    for response, embedded in responses:
        if unlocked:
            assert response.status_code == 200, response.text
            report = response.json()["report"] if embedded else response.json()
            assert report["unlocked"] is True
            assert report["markdown"] == PRIVATE_TEXT
        else:
            assert_locked(response, embedded=embedded)
    assert responses[0][0].json()["cached"] is True
    download = await s.client.get(f"/api/reports/{s.report.key}/download")
    assert download.status_code == (200 if unlocked else 403), download.text
    assert (PRIVATE_TEXT in download.text) is unlocked


@pytest.mark.asyncio
@pytest.mark.parametrize("subscription", [False, True])
async def test_unused_balance_never_unlocks_cached_poll_get_or_export(scenario, subscription):
    s = scenario
    if subscription:
        await subscribe(s)
    await seed_quota(s)
    await assert_all_owner_surfaces(s, unlocked=False)
    assert await event_count(s) == 0
    assert await s.pool.fetchval("select consumed_units from public.usage_quotas where scope_key=$1", f"user:{s.owner}") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["report:", "c-plus-report:"])
@pytest.mark.parametrize("actor", ["owner", None])
async def test_historical_consumption_survives_zero_balance_expiry_and_month_rollover(scenario, prefix, actor):
    s = scenario
    await seed_event(s, prefix=prefix, actor=actor, period="2000-01")
    await seed_quota(s, consumed=1)
    await subscribe(s, status="canceled", start=datetime(2000, 1, 1, tzinfo=timezone.utc), end=datetime(2000, 2, 1, tzinfo=timezone.utc))
    await s.pool.execute("update public.user_profiles set membership_tier='free' where user_id=$1", s.owner)
    await assert_all_owner_surfaces(s, unlocked=True)
    assert await main._consume_c_plus_report_quota(s.owner, s.report.key) is True
    assert await event_count(s) == 1
    assert await s.pool.fetchval("select consumed_units from public.usage_quotas where scope_key=$1", f"user:{s.owner}") == 1


@pytest.mark.asyncio
async def test_paid_order_unlocks_only_exact_owned_report_without_consuming_credit(scenario):
    s = scenario
    await s.pool.execute(
        """insert into public.payment_orders
           (order_no,owner_user_id,product_code,price_version,currency,amount_minor,status,provider,subject_id)
           values($1,$2,'risk_report_single',1,'JPY',100,'paid','stripe',$3)""", uuid4().hex, s.owner, s.report.key,
    )
    await assert_all_owner_surfaces(s, unlocked=True)
    assert await main._consume_c_plus_report_quota(s.owner, s.report.key) is True
    assert await event_count(s) == 0
    another = await seed_report(s.pool, s.owner, month=2)
    assert_locked(await s.client.get(f"/api/reports/{another.key}"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["owner", "actor", "report", "kind", "operation", "prefix"])
async def test_unrelated_usage_event_cannot_unlock_report(scenario, mismatch):
    s = scenario
    options = {
        "owner": {"owner": s.other}, "actor": {"actor": s.other},
        "report": {"key": s.report.key + "-other"}, "kind": {"kind": "query"},
        "operation": {"operation": "reserve"}, "prefix": {"prefix": "unrelated:"},
    }[mismatch]
    await seed_event(s, **options)
    await assert_all_owner_surfaces(s, unlocked=False)


@pytest.mark.asyncio
async def test_anonymous_and_other_owner_never_receive_paid_payload(scenario):
    s = scenario
    await seed_event(s)
    for user, private_status in [(None, 401), (s.other, 404)]:
        s.user = user
        assert_locked(await s.client.get(f"/api/reports/{s.report.key}"))
        for path in [f"/api/jobs/{s.report.job_id}", f"/api/reports/{s.report.key}/download"]:
            response = await s.client.get(path)
            assert response.status_code == private_status
            assert PRIVATE_TEXT not in response.text
    assert await main._consume_c_plus_report_quota(s.other, s.report.key) is False
    assert await s.pool.fetchval("select count(*) from public.usage_events where scope_key=$1", f"user:{s.other}") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("subscription_state", ["missing", "expired", "future", "canceled", "null_period"])
async def test_stale_profile_and_noncurrent_subscription_cannot_spend_report_credit(scenario, subscription_state):
    s = scenario
    now = datetime.now(timezone.utc)
    if subscription_state == "expired":
        await subscribe(s, start=now - timedelta(days=2), end=now - timedelta(days=1))
    elif subscription_state == "future":
        await subscribe(s, start=now + timedelta(days=1), end=now + timedelta(days=2))
    elif subscription_state == "canceled":
        await subscribe(s, status="canceled")
    elif subscription_state == "null_period":
        await subscribe(s, null_period=True)
    await seed_quota(s)
    assert await main._consume_c_plus_report_quota(s.owner, s.report.key) is False
    assert await event_count(s) == 0
    await assert_all_owner_surfaces(s, unlocked=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity", ["zero", "consumed", "reserved"])
async def test_no_available_capacity_leaves_generated_report_locked_without_exception(scenario, capacity):
    s = scenario
    await subscribe(s)
    if capacity == "zero":
        await s.pool.execute("update public.plan_entitlements set limit_units=0 where plan_code='c_plus' and metric='report' and active")
    await seed_quota(s, consumed=int(capacity == "consumed"), reserved=int(capacity == "reserved"))
    assert await main._consume_c_plus_report_quota(s.owner, s.report.key) is False
    assert await event_count(s) == 0
    await assert_all_owner_surfaces(s, unlocked=False)


@pytest.mark.asyncio
async def test_concurrent_same_report_consumes_one_credit_and_retries_stay_unlocked(scenario):
    s = scenario
    await subscribe(s)
    results = await asyncio.gather(*(main._consume_c_plus_report_quota(s.owner, s.report.key) for _ in range(12)))
    assert results == [True] * 12
    assert await event_count(s) == 1
    quota = await s.pool.fetchrow("select consumed_units,reserved_units,limit_units from public.usage_quotas where scope_key=$1 and usage_kind='report'", f"user:{s.owner}")
    assert dict(quota) == {"consumed_units": 1, "reserved_units": 0, "limit_units": 1}
    assert await s.pool.fetchval("select count(*) from public.usage_idempotency where scope_key=$1", f"user:{s.owner}") == 1
    await assert_all_owner_surfaces(s, unlocked=True)
    assert await event_count(s) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", range(3))
async def test_two_reports_competing_for_last_credit_unlock_exactly_one(scenario, attempt):
    s = scenario
    await subscribe(s)
    another = await seed_report(s.pool, s.owner, month=2)
    results = await asyncio.gather(
        main._consume_c_plus_report_quota(s.owner, s.report.key),
        main._consume_c_plus_report_quota(s.owner, another.key),
    )
    assert sorted(results) == [False, True]
    assert await event_count(s) == 1
    assert await s.pool.fetchval("select consumed_units from public.usage_quotas where scope_key=$1", f"user:{s.owner}") == 1
    for report, unlocked in zip([s.report, another], results):
        response = await s.client.get(f"/api/reports/{report.key}")
        assert response.status_code == 200
        assert response.json()["unlocked"] is unlocked
        assert (PRIVATE_TEXT in response.text) is unlocked


@pytest.mark.asyncio
async def test_active_personal_subscription_consumes_personal_quota_despite_org_membership(scenario):
    s = scenario
    await subscribe(s)
    org = await s.pool.fetchval("insert into public.organizations(name,created_by_user_id) values('Synthetic organization',$1) returning id", s.owner)
    await s.pool.execute("insert into public.organization_members(organization_id,user_id,role) values($1,$2,'owner')", org, s.owner)
    await s.pool.execute(
        """insert into public.subscriptions
           (organization_id,product_code,price_version,currency,amount_minor,status,current_period_start,current_period_end)
           values($1,'b_data_pro_monthly',1,'JPY',100,'active',now()-interval '1 day',now()+interval '1 day')""", org,
    )
    assert await main._consume_c_plus_report_quota(s.owner, s.report.key) is True
    assert await event_count(s) == 1
    assert await s.pool.fetchval("select count(*) from public.usage_events where scope_key=$1", f"org:{org}") == 0
    await assert_all_owner_surfaces(s, unlocked=True)


@pytest.mark.asyncio
async def test_insufficient_report_never_consumes_credit(scenario):
    s = scenario
    await subscribe(s)
    incomplete = await seed_report(s.pool, s.owner, month=2, status="insufficient_data")
    assert await main._consume_c_plus_report_quota(s.owner, incomplete.key) is False
    assert await event_count(s) == 0


@pytest.mark.asyncio
async def test_full_generation_completes_when_last_credit_is_already_used(scenario, monkeypatch):
    s = scenario
    await subscribe(s)
    await seed_quota(s, consumed=1)
    source = await s.pool.fetchval(
        """insert into public.sources
           (name,source_type,url,permission_status,data_class,source_period,observed_at,transformation_version,limitations)
           values('Synthetic source','government_open_data',$1,'rights_confirmed','synthetic_fixture',
                  '2026-01',now(),'test-v1','Synthetic fixture only') returning id""", f"https://example.test/fixture/{uuid4()}",
    )
    row = await s.pool.fetchrow("select * from public.property_reports where query_key=$1", s.report.key)
    built = main.row_to_report(row)
    snapshot = SimpleNamespace(sale_period="2026-01")
    monkeypatch.setattr(main, "load_snapshots", lambda: [])
    monkeypatch.setattr(main, "match_snapshot", lambda *args: snapshot)
    monkeypatch.setattr(main, "build_sale_report", lambda *args, **kwargs: dict(built))

    async def source_id(conn):
        return str(source)

    monkeypatch.setattr(main, "resolve_market_source_id", source_id)
    await main.run_generation_job(str(s.report.job_id), str(s.report.query_id), str(s.owner), s.report.request)
    job = await s.pool.fetchrow("select status,progress,error_message from public.generation_jobs where id=$1", s.report.job_id)
    assert dict(job) == {"status": "completed", "progress": 100, "error_message": None}
    assert await s.pool.fetchval("select status from public.queries where id=$1", s.report.query_id) == "completed"
    assert await event_count(s) == 0
    await assert_all_owner_surfaces(s, unlocked=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["owner", "report", "product", "pending", "refunded"])
async def test_unrelated_or_unpaid_order_never_grants_access(scenario, mismatch):
    s = scenario
    await s.pool.execute(
        """insert into public.payment_orders
           (order_no,owner_user_id,product_code,price_version,currency,amount_minor,status,provider,subject_id)
           values($1,$2,$3,1,'JPY',100,$4,'stripe',$5)""",
        uuid4().hex,
        s.other if mismatch == "owner" else s.owner,
        "c_plus_monthly" if mismatch == "product" else "risk_report_single",
        mismatch if mismatch in {"pending", "refunded"} else "paid",
        s.report.key + "-other" if mismatch == "report" else s.report.key,
    )
    await assert_all_owner_surfaces(s, unlocked=False)
    assert await event_count(s) == 0


@pytest.mark.asyncio
async def test_idempotency_marker_without_consumption_is_not_an_unlock(scenario):
    s = scenario
    await s.pool.execute(
        """insert into public.usage_idempotency(scope_key,usage_kind,operation,idempotency_key,fingerprint)
           values($1,'report','consume',$2,$2)""", f"user:{s.owner}", f"report:{s.report.key}",
    )
    await assert_all_owner_surfaces(s, unlocked=False)
    assert await event_count(s) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership_mismatch", ["query", "report"])
@pytest.mark.parametrize("evidence", ["payment", "consumption"])
async def test_inconsistent_query_and_report_owners_never_unlock(scenario, ownership_mismatch, evidence):
    s = scenario
    if evidence == "consumption":
        await seed_event(s)
    else:
        await s.pool.execute(
            """insert into public.payment_orders
               (order_no,owner_user_id,product_code,price_version,currency,amount_minor,status,provider,subject_id)
               values($1,$2,'risk_report_single',1,'JPY',100,'paid','stripe',$3)""",
            uuid4().hex, s.owner, s.report.key,
        )
    if ownership_mismatch == "query":
        await s.pool.execute("update public.queries set owner_user_id=$1 where id=$2", s.other, s.report.query_id)
    else:
        await s.pool.execute("update public.property_reports set owner_user_id=$1 where query_id=$2", s.other, s.report.query_id)
    assert_locked(await s.client.get(f"/api/reports/{s.report.key}"))
    download = await s.client.get(f"/api/reports/{s.report.key}/download")
    assert download.status_code == 404
    assert PRIVATE_TEXT not in download.text
    assert await main._consume_c_plus_report_quota(s.owner, s.report.key) is False
    assert await event_count(s) == int(evidence == "consumption")
