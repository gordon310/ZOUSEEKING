from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import asyncpg
import pytest

from backend.app.rate_limit import consume_shared_rate_limit


@pytest.mark.asyncio
async def test_two_independent_postgres_connections_share_one_rate_limit_window() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    subject = "f" * 64
    action = "integration_shared_limit"
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    connections = [await asyncpg.connect(database_url) for _ in range(4)]
    first = connections[0]
    try:
        await first.execute("delete from public.shared_rate_limits where subject_hash=$1 and action=$2", subject, action)
        results = await asyncio.gather(
            *(consume_shared_rate_limit(connection, subject, action, 3, now) for connection in connections),
        )
        stored = await first.fetchval(
            "select request_count from public.shared_rate_limits where subject_hash=$1 and action=$2 and window_started_at=$3",
            subject, action, now,
        )
        assert sorted(value for value in results if value is not None) == [1, 2, 3]
        assert results.count(None) == 1
        assert stored == 3
    finally:
        await first.execute("delete from public.shared_rate_limits where subject_hash=$1 and action=$2", subject, action)
        for connection in connections:
            await connection.close()
