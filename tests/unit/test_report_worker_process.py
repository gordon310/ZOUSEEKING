"""Process-level contracts for the standalone report outbox worker."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest

from backend.app.models import QueryRequest
from backend.app.report_worker import enqueue_report_outbox
from tests.support.pg_bootstrap import bootstrap_and_migrate, configured_database_url, database_url, require_postgres_or_skip


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = configured_database_url("REPORT_WORKER_PROCESS_TEST_DATABASE_URL")
DATABASE = "zouseeking_report_worker_process_test"
OWNER_ID = UUID("00000000-0000-0000-0000-000000000a01")


@pytest.fixture
def worker_database_url() -> str:
    async def setup() -> str:
        await require_postgres_or_skip(BASE_URL)
        assert BASE_URL is not None
        await bootstrap_and_migrate(BASE_URL, DATABASE)
        return database_url(BASE_URL, DATABASE)

    return asyncio.run(setup())


async def _enqueue_job(url: str, *, suffix: int, stale_lease: bool = False) -> tuple[UUID, UUID]:
    query_id = UUID(f"00000000-0000-0000-0000-000000000b{suffix:02d}")
    job_id = UUID(f"00000000-0000-0000-0000-000000000c{suffix:02d}")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "insert into auth.users (id, email) values ($1, $2)", OWNER_ID, f"worker-{suffix}@test.invalid"
        )
        await conn.execute(
            """
            insert into public.queries
              (id, query_key, owner_user_id, prefecture, city, ward, asset_type, year, month)
            values ($1, $2, $3, '大阪府', '大阪市', '北区', '塔楼', 2026, 9)
            """,
            query_id,
            f"worker-process-{suffix}",
            OWNER_ID,
        )
        await conn.execute(
            """
            insert into public.generation_jobs (id, query_id, status, progress, current_step)
            values ($1, $2, 'pending', 5, '任务已创建')
            """,
            job_id,
            query_id,
        )
        await enqueue_report_outbox(
            conn,
            generation_job_id=job_id,
            query_id=query_id,
            owner_user_id=OWNER_ID,
            request=QueryRequest(prefecture="大阪府", city="大阪市", ward="北区", asset_type="塔楼", year=2026, month=9),
        )
        if stale_lease:
            await conn.execute(
                """
                update public.report_generation_outbox
                   set status='running', claimed_at=now() - interval '30 minutes', claim_token=gen_random_uuid()
                 where generation_job_id=$1
                """,
                job_id,
            )
    finally:
        await conn.close()
    return query_id, job_id


def _worker_environment(url: str, *, once: bool) -> dict[str, str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment["PYTHONPATH"] = str(ROOT)
    if once:
        environment["REPORT_WORKER_ONCE"] = "1"
    else:
        environment.pop("REPORT_WORKER_ONCE", None)
    return environment


async def _outbox_row(url: str, job_id: UUID) -> dict[str, object]:
    conn = await asyncpg.connect(url)
    try:
        row = await conn.fetchrow(
            "select status, attempts, last_error_code from public.report_generation_outbox where generation_job_id=$1",
            job_id,
        )
        assert row is not None
        return dict(row)
    finally:
        await conn.close()


async def _running_count(url: str) -> int:
    conn = await asyncpg.connect(url)
    try:
        return int(await conn.fetchval("select count(*) from public.report_generation_outbox where status='running'"))
    finally:
        await conn.close()


def test_standalone_worker_initializes_pool_and_completes_enqueued_job(worker_database_url: str) -> None:
    """Removing the process-level connect call makes this exit non-zero."""
    _, job_id = asyncio.run(_enqueue_job(worker_database_url, suffix=1))
    result = subprocess.run(
        [sys.executable, "-m", "backend.app.report_worker"],
        cwd=ROOT,
        env=_worker_environment(worker_database_url, once=True),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    row = asyncio.run(_outbox_row(worker_database_url, job_id))
    print(f"standalone worker exit={result.returncode} outbox={row}")
    assert result.returncode == 0, result.stderr
    assert row["status"] == "completed"


def test_sigterm_stops_idle_worker_cleanly_without_running_jobs(worker_database_url: str) -> None:
    """Removing the worker signal handler makes SIGTERM exit with signal -15."""
    process = subprocess.Popen(
        [sys.executable, "-m", "backend.app.report_worker"],
        cwd=ROOT,
        env=_worker_environment(worker_database_url, once=False),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1)
        assert process.poll() is None
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    running = asyncio.run(_running_count(worker_database_url))
    print(f"SIGTERM worker exit={process.returncode} running_rows={running} stderr={stderr!r} stdout={stdout!r}")
    assert process.returncode == 0
    assert running == 0


def test_worker_reclaims_expired_fifteen_minute_lease(worker_database_url: str) -> None:
    """Removing the running-row lease candidate leaves this stale job unprocessed."""
    _, job_id = asyncio.run(_enqueue_job(worker_database_url, suffix=2, stale_lease=True))
    result = subprocess.run(
        [sys.executable, "-m", "backend.app.report_worker"],
        cwd=ROOT,
        env=_worker_environment(worker_database_url, once=True),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    row = asyncio.run(_outbox_row(worker_database_url, job_id))
    print(f"expired lease worker exit={result.returncode} outbox={row}")
    assert result.returncode == 0, result.stderr
    assert row["status"] == "completed"
    assert row["attempts"] == 1
