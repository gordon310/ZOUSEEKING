"""Trusted consent receipts remain append-only and concurrent retries are idempotent."""
import asyncio
import json
from uuid import uuid4

import asyncpg
import pytest

from backend.app.services import policy_consent
from tests.support.pg_bootstrap import bootstrap_and_migrate, configured_database_url, database_url, require_postgres_or_skip


@pytest.mark.asyncio
async def test_current_consent_keeps_history_and_concurrent_retries_write_once(monkeypatch):
    base = configured_database_url()
    await require_postgres_or_skip(base)
    database = f"policy_consent_{uuid4().hex[:12]}"
    await bootstrap_and_migrate(base, database)
    pool = await asyncpg.create_pool(database_url(base, database), min_size=1, max_size=4)
    monkeypatch.setattr(policy_consent, "get_pool", lambda: pool)
    owner, other = uuid4(), uuid4()
    try:
        async with pool.acquire() as conn:
            await conn.execute("insert into auth.users(id) values($1),($2)", owner, other)
            old_id = await conn.fetchval(
                "insert into public.audit_events(actor_user_id,action,target_type,target_id,summary) "
                "values($1,'privacy.policy.accepted','privacy_policy','privacy-2026-08',$2::jsonb) returning id",
                owner, json.dumps({"privacy_policy_version": "privacy-2026-08", "terms_version": "terms-2026-08"}),
            )
            original = dict(await conn.fetchrow("select * from public.audit_events where id=$1", old_id))
        store = policy_consent.PolicyConsentStore()
        assert not await store.status(owner)
        await asyncio.gather(*(store.accept(owner) for _ in range(8)))
        assert await store.status(owner)
        assert not await store.status(other)
        async with pool.acquire() as conn:
            assert await conn.fetchval("select count(*) from public.audit_events where actor_user_id=$1", owner) == 2
            assert dict(await conn.fetchrow("select * from public.audit_events where id=$1", old_id)) == original
            current = await conn.fetchrow("select occurred_at,summary from public.audit_events where actor_user_id=$1 and target_id='privacy-2026-10'", owner)
            assert current['occurred_at'].tzinfo is not None
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await conn.execute("update public.audit_events set summary='{}' where id=$1", old_id)
    finally:
        await pool.close()
        admin = await asyncpg.connect(base, database="postgres")
        try:
            await admin.execute(f"drop database {database} with (force)")
        finally:
            await admin.close()
