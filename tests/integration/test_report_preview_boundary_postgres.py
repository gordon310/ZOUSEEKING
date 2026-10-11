"""Report column permissions and invoker-view checks on disposable local SQL."""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from tests.support.pg_bootstrap import (
    bootstrap_and_migrate, configured_database_url, database_url,
    require_postgres_or_skip,
)

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = configured_database_url("REPORT_PREVIEW_TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def preview_database_url():
    asyncio.run(require_postgres_or_skip(BASE_URL))
    name = f"report_preview_{uuid4().hex[:10]}"
    asyncio.run(bootstrap_and_migrate(BASE_URL, name))
    url = database_url(BASE_URL, name)

    async def grant_supabase_test_roles():
        conn = await asyncpg.connect(url)
        try:
            # Match managed Supabase role capabilities inside this local fixture.
            await conn.execute("alter role service_role bypassrls")
            await conn.execute("grant usage on schema auth, public to anon, authenticated, service_role")
        finally:
            await conn.close()

    asyncio.run(grant_supabase_test_roles())
    return url


@pytest.mark.parametrize("script", [
    "tests/security/test_rls_report_preview_boundary.sql",
    "tests/security/test_rls_member_read_views.sql",
    "tests/security/test_rls_private_projects.sql",
])
def test_report_preview_sql_contract(preview_database_url, script):
    async def run():
        conn = await asyncpg.connect(preview_database_url)
        try:
            await conn.execute((ROOT / script).read_text(encoding="utf-8"))
        finally:
            await conn.close()
    asyncio.run(run())
