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


async def grant_supabase_test_roles(conn: asyncpg.Connection) -> None:
    capability_query = "select rolbypassrls from pg_roles where rolname = 'service_role'"
    bypasses_rls = await conn.fetchval(capability_query)
    if bypasses_rls is None:
        raise RuntimeError("report preview fixture requires the service_role database role")
    if not bypasses_rls:
        # Plain PostgreSQL bootstrap creates an unprivileged role. Managed
        # Supabase already enables BYPASSRLS and forbids altering this role.
        # Let authorization errors fail setup rather than skip RLS assertions.
        await conn.execute("alter role service_role bypassrls")
        if await conn.fetchval(capability_query) is not True:
            raise RuntimeError("report preview fixture requires service_role BYPASSRLS")
    await conn.execute("grant usage on schema auth, public to anon, authenticated, service_role")


@pytest.fixture(scope="module")
def preview_database_url():
    asyncio.run(require_postgres_or_skip(BASE_URL))
    name = f"report_preview_{uuid4().hex[:10]}"
    asyncio.run(bootstrap_and_migrate(BASE_URL, name))
    url = database_url(BASE_URL, name)

    async def configure_test_roles():
        conn = await asyncpg.connect(url)
        try:
            await grant_supabase_test_roles(conn)
        finally:
            await conn.close()

    asyncio.run(configure_test_roles())
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
