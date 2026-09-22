from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest

from backend.app import db
from backend.app import main
from backend.app.main import ReportSourceResolutionError, resolve_market_source_id
from tests.support.pg_bootstrap import (
    bootstrap_and_migrate,
    configured_database_url,
    database_url,
    require_postgres_or_skip,
)


BASE_URL = configured_database_url("REPORT_SOURCE_TEST_DATABASE_URL")


@pytest.fixture
def report_source_database_url():
    asyncio.run(require_postgres_or_skip(BASE_URL))
    return BASE_URL


@pytest.mark.asyncio
async def test_real_sources_business_key_resolves_and_missing_row_is_structured(report_source_database_url):
    database = f"report_source_{uuid4().hex[:10]}"
    target_url = database_url(report_source_database_url, database)
    await bootstrap_and_migrate(report_source_database_url, database)
    conn = await asyncpg.connect(target_url)
    try:
        from backend.app import main
        main._market_source_cache = None
        source_id = uuid4()
        await conn.execute(
            """insert into public.sources
               (id, name, source_type, url, permission_status, update_frequency, parser_version,
                source_period, limitations, data_class, observed_at, transformation_version)
               values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::public.data_class, $11, $12)""",
            source_id,
            "local test market source",
            "government_open_data",
            "https://example.test/local-market-source",
            "rights_confirmed",
            "quarterly",
            "test",
            "2025Q1",
            "local test only",
            "scraped_aggregate",
            datetime(2025, 3, 31, tzinfo=timezone.utc),
            "test",
        )
        assert await resolve_market_source_id(conn) == str(source_id)
        main._market_source_cache = None
        await conn.execute("delete from public.sources where source_type='government_open_data' and permission_status='rights_confirmed'")
        with pytest.raises(ReportSourceResolutionError) as exc_info:
            await resolve_market_source_id(conn)
        assert exc_info.value.code == "market_source_unavailable"
        assert exc_info.value.user_message == "市场数据源暂时不可用，请稍后重试。"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_report_writer_uses_source_class_and_guard_rejects_mismatch(report_source_database_url):
    """Writing the stale literal class must not defeat the source/report guard."""
    database = f"report_source_class_{uuid4().hex[:10]}"
    target_url = database_url(report_source_database_url, database)
    await bootstrap_and_migrate(report_source_database_url, database)
    owner_id = uuid4()
    query_id = uuid4()
    source_id = uuid4()
    pool = await asyncpg.create_pool(target_url, min_size=1, max_size=1)
    main.get_pool = lambda: pool
    try:
        async with pool.acquire() as conn:
            await conn.execute("insert into auth.users (id, email) values ($1, $2)", owner_id, "writer@test.invalid")
            await conn.execute(
                """insert into public.sources
                   (id, name, source_type, url, permission_status, update_frequency, parser_version,
                    source_period, limitations, data_class, observed_at, transformation_version)
                   values ($1, 'verified source', 'government_open_data', 'https://example.test/verified',
                           'rights_confirmed', 'quarterly', 'test', '2025Q1', 'test limitation',
                           'verified_observation', now(), 'test')""",
                source_id,
            )
            await conn.execute(
                """insert into public.queries
                   (id, query_key, owner_user_id, prefecture, city, ward, asset_type, year, month)
                   values ($1, 'writer-source-class', $2, '大阪府', '大阪市', '北区', '塔楼', 2026, 9)""",
                query_id, owner_id,
            )

        await main.save_report(
            str(query_id),
            str(owner_id),
            {
                "query_key": "writer-source-class", "slug": "writer-source-class", "title": "writer source class",
                "publish_month": "2026年9月", "markdown": "test", "xhs_content": "test", "rental": [],
                "sale": [], "summary": {}, "images": [], "data_sources": [], "raw_record": {},
                "report_status": "full_report", "data_class": "scraped_aggregate", "source_id": str(source_id),
                "source_period": "2025Q1", "observed_at": datetime(2025, 3, 31, tzinfo=timezone.utc),
                "transformation_version": "test", "report_version": "test", "limitations": "test limitation",
            },
        )

        async with pool.acquire() as conn:
            assert await conn.fetchval("select data_class::text from public.property_reports where query_id=$1", query_id) == "verified_observation"
            with pytest.raises(asyncpg.RaiseError, match="data_class must match its source"):
                await conn.execute(
                    "update public.property_reports set data_class='scraped_aggregate' where query_id=$1",
                    query_id,
                )
    finally:
        main.get_pool = db.get_pool
        await pool.close()
