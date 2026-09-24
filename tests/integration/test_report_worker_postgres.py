from __future__ import annotations

import asyncio
import os
from uuid import UUID

import asyncpg
import pytest

from backend.app.models import QueryRequest
from tests.support.pg_bootstrap import bootstrap_and_migrate, configured_database_url, database_url, require_postgres_or_skip


BASE_URL = configured_database_url("OUTBOX_TEST_DATABASE_URL")
DATABASE = "zouseeking_outbox_test"
QUERY_ID = UUID("00000000-0000-0000-0000-000000000901")
JOB_ID = UUID("00000000-0000-0000-0000-000000000902")


@pytest.fixture
def outbox_database_url():
    async def setup():
        await require_postgres_or_skip(BASE_URL)
        await bootstrap_and_migrate(BASE_URL, DATABASE)
        conn = await asyncpg.connect(database_url(BASE_URL, DATABASE))
        try:
            await conn.execute(
                "insert into auth.users (id, email) values ('00000000-0000-0000-0000-000000000903', 'outbox@test.invalid')"
            )
            await conn.execute(
                """
                insert into public.queries (id, query_key, owner_user_id, prefecture, city, ward, asset_type, year, month)
                values ($1, 'outbox-test', '00000000-0000-0000-0000-000000000903', '大阪府', '大阪市', '北区', '塔楼', 2026, 9)
                """,
                QUERY_ID,
            )
            await conn.execute(
                "insert into public.generation_jobs (id, query_id, status, progress, current_step) values ($1, $2, 'pending', 5, '任务已创建')",
                JOB_ID,
                QUERY_ID,
            )
            await conn.execute(
                "insert into public.report_generation_outbox (generation_job_id, query_id, idempotency_key, payload) values ($1, $2, 'outbox-test-key', '{}')",
                JOB_ID,
                QUERY_ID,
            )
        finally:
            await conn.close()
        return database_url(BASE_URL, DATABASE)

    return asyncio.run(setup())


@pytest.mark.asyncio
async def test_two_real_postgres_workers_only_one_claims_same_job(outbox_database_url):
    from backend.app.report_worker import claim_next

    pool = await asyncpg.create_pool(outbox_database_url, min_size=2, max_size=2)
    try:
        claims = await asyncio.gather(claim_next(pool), claim_next(pool))
        assert sum(claim is not None for claim in claims) == 1
        row = await pool.fetchrow("select status, attempts from public.report_generation_outbox where idempotency_key='outbox-test-key'")
        assert dict(row) == {"status": "running", "attempts": 1}
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_real_postgres_completion_is_idempotent(outbox_database_url):
    from backend.app.report_worker import claim_next, complete_claim

    pool = await asyncpg.create_pool(outbox_database_url, min_size=1, max_size=1)
    try:
        claim = await claim_next(pool)
        assert claim is not None
        assert await complete_claim(pool, claim) is True
        assert await complete_claim(pool, claim) is False
        row = await pool.fetchrow("select status, attempts from public.report_generation_outbox where idempotency_key='outbox-test-key'")
        assert dict(row) == {"status": "completed", "attempts": 1}
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_replay_after_lease_expiry_does_not_duplicate_report(outbox_database_url):
    from backend.app.report_worker import claim_next, complete_claim

    pool = await asyncpg.create_pool(outbox_database_url, min_size=1, max_size=1)
    try:
        first_claim = await claim_next(pool)
        assert first_claim is not None
        await pool.execute(
            "update public.report_generation_outbox set claimed_at=now() - interval '16 minutes' where id=$1",
            first_claim.outbox_id,
        )
        replay_claim = await claim_next(pool)
        assert replay_claim is not None
        assert replay_claim.generation_job_id == JOB_ID
        assert replay_claim.attempts == 2
        assert await complete_claim(pool, replay_claim) is True
        row = await pool.fetchrow(
            "select count(*) over (), status, attempts from public.report_generation_outbox where generation_job_id=$1",
            JOB_ID,
        )
        assert row is not None
        assert dict(row) == {"count": 1, "status": "completed", "attempts": 2}
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_reenqueue_is_idempotent(outbox_database_url):
    from backend.app.report_worker import claim_next, complete_claim, enqueue_report_outbox

    pool = await asyncpg.create_pool(outbox_database_url, min_size=1, max_size=1)
    try:
        claim = await claim_next(pool)
        assert claim is not None
        assert await complete_claim(pool, claim) is True
        async with pool.acquire() as conn:
            await enqueue_report_outbox(
                conn,
                generation_job_id=JOB_ID,
                query_id=QUERY_ID,
                owner_user_id=UUID("00000000-0000-0000-0000-000000000903"),
                request=QueryRequest(prefecture="大阪府", city="大阪市", ward="北区", asset_type="塔楼", year=2026, month=9),
            )
        row = await pool.fetchrow(
            "select count(*) over (), status, attempts from public.report_generation_outbox where generation_job_id=$1",
            JOB_ID,
        )
        assert row is not None
        assert dict(row) == {"count": 1, "status": "completed", "attempts": 1}
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_completed_row_is_never_reclaimed(outbox_database_url):
    from backend.app.report_worker import claim_next, complete_claim

    pool = await asyncpg.create_pool(outbox_database_url, min_size=1, max_size=1)
    try:
        claim = await claim_next(pool)
        assert claim is not None
        assert await complete_claim(pool, claim) is True
        assert await claim_next(pool) is None
    finally:
        await pool.close()
