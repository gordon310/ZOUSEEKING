"""Real local-PostgreSQL coverage for regional-statistics filtering."""

from __future__ import annotations

import asyncio
from uuid import UUID

import asyncpg
import httpx
import pytest

from backend.app import db
from backend.app.auth import AuthUser
from backend.app.main import app
from backend.app.region_stats_routes import DbRegionStatsStore, get_region_stats_store, region_stats
from backend.app.auth import require_user
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
            for index, ward in enumerate(("麻布", "麻布", "麻布", "麻布", "麻布", "赤坂")):
                await conn.execute(
                    """insert into public.mlit_transactions
                    (source_id, source_record_key, prefecture, city, ward, asset_kind, asset_type,
                     price_jpy, area_sqm, unit_price_jpy_per_sqm, trade_quarter, trade_year, raw)
                    values($1, $2, '东京都', '港区', $3, '中古マンション等', '公寓', $4, 100, $4, '2025Q1', 2025, '{}'::jsonb)""",
                    SOURCE_ID, f"region-stats-{index}", ward, 1000000 + index * 100000,
                )
            await conn.execute(
                """insert into public.rent_reference_stats
                (source_key, source_label, prefecture, city, ward, geo_level, scope_label,
                 rent_jpy_per_sqm_month, rent_jpy_per_sqm_month_excl_zero, survey_year,
                 survey_label, source_url, license_label, fetched_at)
                values ('estat_housing_land_122_4', '令和5年住宅・土地統計調査 第122-4表',
                        '东京都', '港区', '__not_subdivided__', 'city', '民営借家・借家(専用住宅)',
                        1700, 1809, 2023, '令和5年(2023)',
                        'https://www.e-stat.go.jp/', 'e-Stat利用規約（出典明記・加工して作成）', now())"""
            )
            await conn.execute(
                """insert into public.rent_reference_stats
                (source_key, source_label, prefecture, city, ward, geo_level, scope_label,
                 building_type, structure_type, rent_jpy_per_sqm_month,
                 rent_jpy_per_sqm_month_excl_zero, survey_year, survey_label,
                 source_url, license_label, fetched_at)
                values ('estate_housing_land_122_5', '令和5年住宅・土地統計調査 第122-5表',
                        '东京都', '港区', '__not_subdivided__', 'city',
                        '借家(専用住宅)・共同住宅・非木造', '共同住宅', '非木造',
                        2100, 2111, 2023, '令和5年(2023)',
                        'https://www.e-stat.go.jp/', 'e-Stat利用規約（出典明記・加工して作成）', now())"""
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
    assert results[0]["rent_reference"]["source_key"] == "estate_housing_land_122_5"
    assert results[0]["rent_reference"]["rent_jpy_per_sqm_month"] == 2111


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
                       where source_key='estate_housing_land_122_5' and prefecture='东京都' and city='港区'"""
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
