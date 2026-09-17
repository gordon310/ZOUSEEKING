"""Real local-PostgreSQL coverage for regional-statistics filtering."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import asyncpg
import pytest

from backend.app import db
from backend.app.auth import AuthUser
from backend.app.region_stats_routes import DbRegionStatsStore, region_stats
from tests.support.pg_bootstrap import bootstrap_and_migrate, database_url, is_local_server


BASE_URL = os.getenv("REGION_STATS_TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:55432/postgres")
TEST_DB = "zouseeking_region_stats_test"
USER_ID = UUID("00000000-0000-0000-0000-000000000030")
SOURCE_ID = UUID("bf4b6d56-f7ed-4e66-b599-3900e22001d6")


@pytest.fixture(scope="module")
def region_stats_database():
    if not is_local_server(BASE_URL):
        pytest.fail("REGION_STATS_TEST_DATABASE_URL must point at a disposable local PostgreSQL server")
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
                    values($1, $2, '東京都', '港区', $3, '中古マンション等', '公寓', $4, 100, $4, '2025Q1', 2025, '{}'::jsonb)""",
                    SOURCE_ID, f"region-stats-{index}", ward, 1000000 + index * 100000,
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
            for ward in (None, "", "   ", "__not_subdivided__"):
                results.append(await region_stats("東京都", "港区", "公寓", 2025, 1, ward, user, store))
            filtered = await region_stats("東京都", "港区", "公寓", 2025, 1, "麻布", user, store)
            apartment = await region_stats("東京都", "港区", "公寓", 2025, 1, None, user, store)
            tower = await region_stats("東京都", "港区", "塔楼", 2025, 1, None, user, store)
            return results, filtered, apartment, tower
        finally:
            await db.pool.close()
            db.pool = old_pool

    results, filtered, apartment, tower = asyncio.run(exercise())
    assert [result["sample_size"] for result in results] == [6, 6, 6, 6]
    assert filtered["sample_size"] == 5
    assert filtered["median_unit_price_jpy_per_sqm"] == 1200000
    assert tower["sample_size"] == apartment["sample_size"]
    assert tower["median_unit_price_jpy_per_sqm"] == apartment["median_unit_price_jpy_per_sqm"]
    assert tower["disclosure"] == {"code": "tower_merged_into_apartment"}
