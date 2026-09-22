"""Real local-PostgreSQL coverage for regional-statistics filtering."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest

from backend.app import db
from backend.app.auth import AuthUser
from backend.app.main import app
from backend.app.region_stats_routes import DbRegionStatsStore, get_region_stats_store, region_stats, region_stats_trend
from backend.app.services.provenance import REQUIRED_STATISTIC_FIELDS
from backend.app.auth import require_user
from backend.app.usage.quota import current_period_key
from tests.support.pg_bootstrap import (
    bootstrap_and_migrate,
    configured_database_url,
    database_url,
    require_postgres_or_skip,
)


BASE_URL = configured_database_url("REGION_STATS_TEST_DATABASE_URL")
TEST_DB = "zouseeking_region_stats_test"
USER_ID = UUID("00000000-0000-0000-0000-000000000030")
SOURCE_ID = UUID("bf4b6d56-f7ed-4e66-b599-3900e22001d6")
TREND_SOURCE_ID = UUID("35f1c934-f164-4a9d-bcb5-72a7ae902206")


@pytest.fixture(scope="module")
def region_stats_database():
    asyncio.run(require_postgres_or_skip(BASE_URL))
    asyncio.run(bootstrap_and_migrate(BASE_URL, TEST_DB))
    target_url = database_url(BASE_URL, TEST_DB)

    async def seed():
        conn = await asyncpg.connect(target_url)
        try:
            await conn.execute("insert into auth.users(id, email) values($1, $2)", USER_ID, "region-stats@test.invalid")
            org_id = await conn.fetchval("insert into public.organizations(name, created_by_user_id) values('Stats Test', $1) returning id", USER_ID)
            await conn.execute("insert into public.organization_members(organization_id, user_id, role) values($1, $2, 'member')", org_id, USER_ID)
            await conn.execute(
                """update public.sources
                   set name='regional statistics fixture source', source_type='government_open_data',
                       url='https://example.test/region-stats-fixture', permission_status='rights_confirmed',
                       update_frequency='quarterly', parser_version='test',
                       source_period='source registry entry verified 2026-09-15',
                       limitations='Fixture source limitation.', license='Fixture source license.',
                       data_class='verified_observation', observed_at=$2,
                       transformation_version='mlit-fixture-2025Q1'
                   where id=$1""",
                SOURCE_ID, datetime(2025, 4, 1, tzinfo=timezone.utc),
            )
            await conn.execute(
                """insert into public.sources
                   (id, name, source_type, url, permission_status, update_frequency, parser_version,
                    source_period, limitations, license, data_class, observed_at, transformation_version)
                   values ($1, 'synthetic fixture trend source', 'government_open_data',
                           'https://fixtures.invalid/region-trend', 'unverified', 'test', 'fixture',
                           'fixture-only', 'Synthetic fixture; never market evidence.', 'Fixture-only',
                           'synthetic_fixture', $2, 'trend-fixture-v1')""",
                TREND_SOURCE_ID, datetime(2026, 9, 22, tzinfo=timezone.utc),
            )
            await conn.execute(
                """update public.user_profiles
                   set membership_tier='b_data_pro', audience='b'
                   where user_id=$1""", USER_ID,
            )
            await conn.execute(
                """insert into public.pricing_plans
                   (plan_code, name, monthly_query_limit, monthly_report_quota, subscription_slots, export_rows_monthly, audience)
                   values ('b_data_pro', 'Fixture B Data Pro', 500, 0, 10, 10000, 'b')"""
            )
            await conn.execute(
                """insert into public.plan_entitlements(plan_code, metric, limit_units, period, active)
                   values ('b_data_pro', 'stats_query', 100, 'month', true)"""
            )
            for index, ward in enumerate(("麻布", "麻布", "麻布", "麻布", "麻布", "赤坂")):
                await conn.execute(
                    """insert into public.mlit_transactions
                    (source_id, source_record_key, prefecture, city, ward, asset_kind, asset_type,
                     price_jpy, area_sqm, unit_price_jpy_per_sqm, trade_quarter, trade_year, raw,
                     data_class, source_url, retrieved_at, source_period, transformation_version,
                     rights_status, rights_confirmed, limitations, missing_value_policy)
                    values($1, $2, '东京都', '港区', $3, '中古マンション等', '公寓', $4, 100, $4, '2025Q1', 2025, '{}'::jsonb,
                           'verified_observation', 'https://example.test/region-stats-fixture', $5, '2025Q1',
                           'mlit-fixture-2025Q1', 'rights_confirmed', 'yes', 'Fixture transaction limitation.',
                           'exclude_missing_or_nonpositive_unit_price')""",
                    SOURCE_ID, f"region-stats-{index}", ward, 1000000 + index * 100000,
                    datetime(2025, 4, 1, tzinfo=timezone.utc),
                )
            for period, sample_count, base_price in (("2025Q4", 5, 1_000_000), ("2026Q1", 6, 1_200_000), ("2026Q2", 4, 1_400_000)):
                for index in range(sample_count):
                    await conn.execute(
                        """insert into public.mlit_transactions
                        (source_id, source_record_key, prefecture, city, ward, asset_kind, asset_type,
                         price_jpy, area_sqm, unit_price_jpy_per_sqm, trade_quarter, trade_year, raw,
                         data_class, source_url, retrieved_at, source_period, transformation_version,
                         rights_status, rights_confirmed, limitations, missing_value_policy)
                        values($1, $2, '夹具都道府县', '夹具市', '夹具区', '中古マンション等', '公寓',
                               $3, 100, $3, $4, $5, '{"fixture":true}'::jsonb,
                               'synthetic_fixture', 'https://fixtures.invalid/region-trend', $6, $4,
                               'trend-fixture-v1', 'not_applicable', 'not_applicable',
                               'Synthetic fixture; never market evidence.', 'exclude_missing_or_nonpositive_unit_price')""",
                        TREND_SOURCE_ID, f"trend-fixture-{period}-{index}", base_price + index * 1_000, period,
                        int(period[:4]), datetime(2026, 9, 22, tzinfo=timezone.utc),
                    )
            await conn.execute(
                """insert into public.rent_reference_stats
                (source_key, source_label, prefecture, city, ward, geo_level, scope_label,
                 rent_jpy_per_sqm_month, rent_jpy_per_sqm_month_excl_zero, survey_year,
                 survey_label, source_url, license_label, fetched_at, data_class, retrieved_at,
                 source_period, transformation_version, rights_status, rights_confirmed, limitations,
                 missing_value_policy)
                values ('estat_housing_land_122_4', '令和5年住宅・土地統計調査 第122-4表',
                        '东京都', '港区', '__not_subdivided__', 'city', '民営借家・借家(専用住宅)',
                        1700, 1809, 2023, '令和5年(2023)',
                        'https://www.e-stat.go.jp/', 'e-Stat利用規約（出典明記・加工して作成）', now(),
                        'verified_observation', now(), '2023', 'estat-fixture-2023', 'rights_confirmed', 'yes',
                        'Fixture rent limitation.', 'exclude_zero_rent')"""
            )
            await conn.execute(
                """insert into public.rent_reference_stats
                (source_key, source_label, prefecture, city, ward, geo_level, scope_label,
                 building_type, structure_type, rent_jpy_per_sqm_month,
                 rent_jpy_per_sqm_month_excl_zero, survey_year, survey_label,
                 source_url, license_label, fetched_at, data_class, retrieved_at, source_period,
                 transformation_version, rights_status, rights_confirmed, limitations, missing_value_policy)
                values ('estat_housing_land_122_5', '令和5年住宅・土地統計調査 第122-5表',
                        '东京都', '港区', '__not_subdivided__', 'city',
                        '借家(専用住宅)・共同住宅・非木造', '共同住宅', '非木造',
                        2100, 2111, 2023, '令和5年(2023)',
                        'https://www.e-stat.go.jp/', 'e-Stat利用規約（出典明記・加工して作成）', now(),
                        'verified_observation', now(), '2023', 'estat-fixture-2023', 'rights_confirmed', 'yes',
                        'Fixture rent limitation.', 'exclude_zero_rent')"""
            )
        finally:
            await conn.close()

    asyncio.run(seed())
    yield target_url


def test_real_postgres_ward_normalization_and_filtering(region_stats_database):
    store = DbRegionStatsStore()
    user = AuthUser(USER_ID, "region-stats@test.invalid", "Member")

    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        try:
            results = []
            results = []
            for prefecture, city in (("东京都", "港区"), ("東京都", "港区")):
                results.append(await region_stats(prefecture, city, "公寓", 2025, 1, None, user, store))
            return results
        finally:
            await db.pool.close()
            db.pool = old_pool

    results = asyncio.run(exercise())
    assert results[0]["sample_size"] > 0
    assert results[1]["sample_size"] == results[0]["sample_size"]
    assert results[0]["rent_reference"]["source_key"] == "estat_housing_land_122_5"
    assert results[0]["rent_reference"]["rent_jpy_per_sqm_month"] == 2111
    # The supporting source row contains registry prose; the metric must expose
    # the actual period of its transaction rows instead.
    assert results[0]["source_period"] == "2025Q1"
    assert "source registry entry verified" not in results[0]["source_period"]


def test_real_postgres_trend_response_is_chronological_provenance_complete_and_metered(region_stats_database):
    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        try:
            user = AuthUser(USER_ID, "region-stats@test.invalid", "Fixture Member")
            response = await region_stats_trend("夹具都道府县", "夹具市", "公寓", "夹具区", None, None, user, DbRegionStatsStore())
            async with db.pool.acquire() as conn:
                usage_events = await conn.fetchval(
                    """select count(*) from public.usage_events
                       where actor_user_id=$1 and usage_kind='stats_query' and operation='consume'
                         and idempotency_key like 'region-trend:%'""", USER_ID
                )
            return response, usage_events
        finally:
            await db.pool.close()
            db.pool = old_pool

    response, usage_events = asyncio.run(exercise())
    assert response["status"] == "ok"
    assert response["period_count"] == 2
    assert [item["period"] for item in response["periods"]] == ["2025Q4", "2026Q1"]
    assert response["excluded_periods"] == [{"period": "2026Q2", "reason": "insufficient_sample", "sample_size": 4}]
    assert response["comparability"]["consistent"] is True
    assert usage_events == 1
    for item in response["periods"]:
        assert set(REQUIRED_STATISTIC_FIELDS) <= item.keys()
        assert item["data_class"] == "synthetic_fixture"
        assert item["source_url"] == "https://fixtures.invalid/region-trend"


def test_real_postgres_single_and_trend_reject_the_same_unconfigured_stats_quota(region_stats_database):
    """No subscription plus no entitlement is rejected equally by both paths."""
    user_id = uuid4()

    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        app.dependency_overrides[require_user] = lambda: AuthUser(user_id, "unconfigured@test.invalid", "Member")
        app.dependency_overrides[get_region_stats_store] = lambda: DbRegionStatsStore()
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("insert into auth.users(id, email) values($1, $2)", user_id, "unconfigured@test.invalid")
                org_id = await conn.fetchval(
                    "insert into public.organizations(name, created_by_user_id) values('Unconfigured quota', $1) returning id", user_id
                )
                await conn.execute(
                    "insert into public.organization_members(organization_id, user_id, role) values($1, $2, 'member')", org_id, user_id
                )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                single = await client.get("/api/org/region-stats", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓", "year": 2025, "quarter": 1})
                trend = await client.get("/api/org/region-stats/trend", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓"})
            return single, trend
        finally:
            app.dependency_overrides.clear()
            await db.pool.close()
            db.pool = old_pool

    single, trend = asyncio.run(exercise())
    assert single.status_code == trend.status_code == 429
    assert single.json() == trend.json() == {"error": {"code": "quota_exceeded", "message": "统计额度已用尽。"}}


def test_real_postgres_single_and_trend_each_record_a_stats_query_consumption(region_stats_database):
    """Both allowed paths consume one auditable stats_query unit."""
    user_id = uuid4()

    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        app.dependency_overrides[require_user] = lambda: AuthUser(user_id, "metered@test.invalid", "Member")
        app.dependency_overrides[get_region_stats_store] = lambda: DbRegionStatsStore()
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("insert into auth.users(id, email) values($1, $2)", user_id, "metered@test.invalid")
                await conn.execute("update public.user_profiles set membership_tier='b_data_pro', audience='b' where user_id=$1", user_id)
                org_id = await conn.fetchval(
                    "insert into public.organizations(name, created_by_user_id) values('Metered quota', $1) returning id", user_id
                )
                await conn.execute(
                    "insert into public.organization_members(organization_id, user_id, role) values($1, $2, 'member')", org_id, user_id
                )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                single = await client.get("/api/org/region-stats", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓", "year": 2025, "quarter": 1})
                trend = await client.get("/api/org/region-stats/trend", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓"})
            async with db.pool.acquire() as conn:
                events = await conn.fetch(
                    "select usage_kind, operation, units from public.usage_events where actor_user_id=$1 order by created_at", user_id
                )
            return single, trend, [dict(event) for event in events]
        finally:
            app.dependency_overrides.clear()
            await db.pool.close()
            db.pool = old_pool

    single, trend, events = asyncio.run(exercise())
    assert single.status_code == trend.status_code == 200
    assert events == [
        {"usage_kind": "stats_query", "operation": "consume", "units": 1},
        {"usage_kind": "stats_query", "operation": "consume", "units": 1},
    ]


def test_real_postgres_single_and_trend_reject_the_same_exhausted_stats_quota(region_stats_database):
    """A fully consumed quota produces the same public 429 response on both paths."""
    user_id = uuid4()

    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        app.dependency_overrides[require_user] = lambda: AuthUser(user_id, "exhausted@test.invalid", "Member")
        app.dependency_overrides[get_region_stats_store] = lambda: DbRegionStatsStore()
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("insert into auth.users(id, email) values($1, $2)", user_id, "exhausted@test.invalid")
                await conn.execute("update public.user_profiles set membership_tier='b_data_pro', audience='b' where user_id=$1", user_id)
                org_id = await conn.fetchval(
                    "insert into public.organizations(name, created_by_user_id) values('Exhausted quota', $1) returning id", user_id
                )
                await conn.execute(
                    "insert into public.organization_members(organization_id, user_id, role) values($1, $2, 'member')", org_id, user_id
                )
                await conn.execute(
                    """insert into public.usage_quotas(scope_key, usage_kind, period_key, limit_units, consumed_units)
                       values($1, 'stats_query', $2, 100, 100)""",
                    f"user:{user_id}", current_period_key(datetime.now(timezone.utc), "month"),
                )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                single = await client.get("/api/org/region-stats", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓", "year": 2025, "quarter": 1})
                trend = await client.get("/api/org/region-stats/trend", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓"})
            return single, trend
        finally:
            app.dependency_overrides.clear()
            await db.pool.close()
            db.pool = old_pool

    single, trend = asyncio.run(exercise())
    assert single.status_code == trend.status_code == 429
    assert single.json() == trend.json() == {"error": {"code": "quota_exceeded", "message": "统计额度已用尽。"}}


def test_real_postgres_region_stats_endpoint_degrades_when_options_file_is_unavailable(region_stats_database, monkeypatch, tmp_path):
    monkeypatch.setattr("backend.app.region_names.FIELD_OPTIONS_PATH", tmp_path / "missing-field-options.json")
    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "region-stats@test.invalid", "Member")
        app.dependency_overrides[get_region_stats_store] = lambda: DbRegionStatsStore()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get(
                    "/api/org/region-stats",
                    params={"prefecture": "东京都", "city": "港区", "ward": "麻布", "asset_type": "公寓", "year": 2025, "quarter": 1},
                )
        finally:
            app.dependency_overrides.clear()
            await db.pool.close()
            db.pool = old_pool

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert response.json()["sample_size"] == 5
    assert response.json()["rent_reference"]["source_key"] == "estat_housing_land_122_5"


def test_real_postgres_frontend_asset_types_return_complete_200_responses(region_stats_database):
    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "region-stats@test.invalid", "Member")
        app.dependency_overrides[get_region_stats_store] = lambda: DbRegionStatsStore()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                responses = []
                for asset_type in ("塔楼", "公寓", "一户建"):
                    responses.append(await client.get(
                        "/api/org/region-stats",
                        params={"prefecture": "东京都", "city": "港区", "asset_type": asset_type, "year": 2025, "quarter": 1},
                    ))
                return responses
        finally:
            app.dependency_overrides.clear()
            await db.pool.close()
            db.pool = old_pool

    responses = asyncio.run(exercise())
    assert [response.status_code for response in responses] == [200, 200, 200]
    for response, asset_type in zip(responses, ("塔楼", "公寓", "一户建")):
        payload = response.json()
        assert payload["asset_type"] == asset_type
        assert {"status", "sample_size", "period", "sources", "license"} <= payload.keys()
        if payload["sample_size"] == 0:
            assert payload["status"] == "insufficient_sample"
            assert {"data_class", "source_url", "retrieved_at", "source_period"}.isdisjoint(payload)
        else:
            assert {"data_class", "source_url", "retrieved_at", "source_period", "limitations"} <= payload.keys()


def test_real_postgres_rent_value_is_read_again_after_database_update(region_stats_database):
    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        try:
            store = DbRegionStatsStore()
            user = AuthUser(USER_ID, "region-stats@test.invalid", "Member")
            before = await region_stats("东京都", "港区", "公寓", 2025, 1, None, user, store)
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """update public.rent_reference_stats
                       set rent_jpy_per_sqm_month_excl_zero=1999
                       where source_key='estat_housing_land_122_5' and prefecture='东京都' and city='港区'"""
                )
            after = await region_stats("东京都", "港区", "公寓", 2025, 1, None, user, store)
            return before, after
        finally:
            await db.pool.close()
            db.pool = old_pool

    before, after = asyncio.run(exercise())
    assert before["rent_reference"]["rent_jpy_per_sqm_month"] == 2111
    assert after["rent_reference"]["rent_jpy_per_sqm_month"] == 1999
    assert after["rent_to_price_ratio"]["gross_value"] != before["rent_to_price_ratio"]["gross_value"]


def test_region_stats_provenance_is_re_read_from_database_after_update(region_stats_database):
    """Changing supporting records must change the next published envelope.

    This fails if the response falls back to the former placeholder
    ``database_imported_at`` or a hard-coded transformation version.
    """
    source_id = UUID("8ec49fe2-0ae0-4529-a44d-813548ab7980")
    original_retrieved_at = datetime(2026, 9, 10, 1, 2, 3, tzinfo=timezone.utc)
    changed_retrieved_at = datetime(2026, 9, 19, 4, 5, 6, tzinfo=timezone.utc)
    original_version = "mlit-import-2026-09-10"
    changed_version = "mlit-import-provenance-canary-2026-09-19"

    async def exercise():
        old_pool = db.pool
        db.pool = await asyncpg.create_pool(region_stats_database, min_size=1, max_size=2)
        try:
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """insert into public.sources
                       (id, name, source_type, url, permission_status, update_frequency, parser_version,
                        source_period, limitations, license, data_class, observed_at, transformation_version)
                       values ($1, 'provenance canary source', 'government_open_data',
                               'https://example.test/provenance-canary', 'rights_confirmed', 'quarterly', 'test',
                               '2025Q1', 'Database-backed limitation canary.', 'Database-backed license canary.',
                               'verified_observation', $2, $3)""",
                    source_id, original_retrieved_at, original_version,
                )
                await conn.execute(
                    """insert into public.mlit_transactions
                       (source_id, source_record_key, prefecture, city, ward, asset_kind, asset_type,
                        price_jpy, area_sqm, unit_price_jpy_per_sqm, trade_quarter, trade_year, raw,
                        data_class, source_url, retrieved_at, source_period, transformation_version,
                        rights_status, rights_confirmed, limitations, missing_value_policy)
                       values ($1, 'provenance-canary-1', '大阪府', '大阪市', '北区', '中古マンション等', '公寓',
                               900000, 100, 9000, '2025Q1', 2025, '{}'::jsonb,
                               'verified_observation', 'https://example.test/provenance-canary', $2, '2025Q1', $3,
                               'rights_confirmed', 'yes', 'Transaction fallback limitation.',
                               'exclude_missing_or_nonpositive_unit_price')""",
                    source_id, original_retrieved_at, original_version,
                )
            store = DbRegionStatsStore()
            user = AuthUser(USER_ID, "region-stats@test.invalid", "Member")
            before = await region_stats("大阪府", "大阪市", "公寓", 2025, 1, "北区", user, store)
            async with db.pool.acquire() as conn:
                await conn.execute(
                    "update public.mlit_transactions set retrieved_at=$1 where source_id=$2",
                    changed_retrieved_at, source_id,
                )
                await conn.execute(
                    "update public.sources set transformation_version=$1 where id=$2",
                    changed_version, source_id,
                )
            after = await region_stats("大阪府", "大阪市", "公寓", 2025, 1, "北区", user, store)
            print("provenance-before", before["retrieved_at"], before["transformation_version"])
            print("provenance-after", after["retrieved_at"], after["transformation_version"])
            return before, after
        finally:
            await db.pool.close()
            db.pool = old_pool

    before, after = asyncio.run(exercise())
    assert before["retrieved_at"] == original_retrieved_at
    assert before["transformation_version"] == original_version
    assert after["retrieved_at"] == changed_retrieved_at
    assert after["transformation_version"] == changed_version
    assert after["license"]["name"] == "Database-backed license canary."
    assert after["limitations"] == "Database-backed limitation canary."
    assert "database_imported_at" not in json.dumps(after, default=str)
