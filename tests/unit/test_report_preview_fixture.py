"""Role setup stays portable without weakening the real SQL security tests."""

import asyncio
from unittest.mock import AsyncMock, call

import asyncpg
import pytest

from tests.integration.test_report_preview_boundary_postgres import grant_supabase_test_roles


CAPABILITY_QUERY = "select rolbypassrls from pg_roles where rolname = 'service_role'"
SCHEMA_GRANT = "grant usage on schema auth, public to anon, authenticated, service_role"


def test_existing_bypassrls_role_is_not_altered():
    conn = AsyncMock()
    conn.fetchval.return_value = True

    async def reject_reserved_role_alteration(statement):
        if statement.lower().startswith("alter role"):
            raise asyncpg.InsufficientPrivilegeError("role service_role is reserved")

    conn.execute.side_effect = reject_reserved_role_alteration

    asyncio.run(grant_supabase_test_roles(conn))

    conn.fetchval.assert_awaited_once_with(CAPABILITY_QUERY)
    conn.execute.assert_awaited_once_with(SCHEMA_GRANT)


def test_plain_postgres_role_is_configured_and_verified():
    conn = AsyncMock()
    conn.fetchval.side_effect = [False, True]

    asyncio.run(grant_supabase_test_roles(conn))

    assert conn.mock_calls == [
        call.fetchval(CAPABILITY_QUERY),
        call.execute("alter role service_role bypassrls"),
        call.fetchval(CAPABILITY_QUERY),
        call.execute(SCHEMA_GRANT),
    ]


def test_role_configuration_authorization_failure_is_not_swallowed():
    conn = AsyncMock()
    conn.fetchval.return_value = False
    denied = asyncpg.InsufficientPrivilegeError("role service_role is reserved")
    conn.execute.side_effect = denied

    with pytest.raises(asyncpg.InsufficientPrivilegeError) as exc:
        asyncio.run(grant_supabase_test_roles(conn))

    assert exc.value is denied
    conn.execute.assert_awaited_once_with("alter role service_role bypassrls")


def test_ineffective_role_configuration_fails_explicitly():
    conn = AsyncMock()
    conn.fetchval.side_effect = [False, False]

    with pytest.raises(RuntimeError, match="requires service_role BYPASSRLS"):
        asyncio.run(grant_supabase_test_roles(conn))

    conn.execute.assert_awaited_once_with("alter role service_role bypassrls")


def test_missing_service_role_fails_explicitly():
    conn = AsyncMock()
    conn.fetchval.return_value = None

    with pytest.raises(RuntimeError, match="requires the service_role database role"):
        asyncio.run(grant_supabase_test_roles(conn))

    conn.execute.assert_not_awaited()
