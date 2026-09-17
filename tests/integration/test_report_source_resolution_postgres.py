from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest

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
