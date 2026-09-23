from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.rate_limit import RateLimitStoreUnavailable, consume_shared_rate_limit


class _Connection:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.result


@pytest.mark.asyncio
async def test_shared_rate_limit_uses_atomic_postgres_counter_contract() -> None:
    connection = _Connection({"request_count": 2})
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)

    count = await consume_shared_rate_limit(
        connection,
        subject_hash="a" * 64,
        action="consumer_registration",
        limit=5,
        now=now,
    )

    assert count == 2
    query, args = connection.calls[0]
    assert "insert into public.shared_rate_limits" in query
    assert "on conflict (subject_hash, action, window_started_at) do update" in query
    assert "request_count < $5" in query
    assert args == ("a" * 64, "consumer_registration", now, now + timedelta(hours=1), 5)


@pytest.mark.asyncio
async def test_shared_rate_limit_fails_closed_when_postgres_is_unavailable() -> None:
    class _Unavailable:
        async def fetchrow(self, *_args):
            raise OSError("database unavailable")

    with pytest.raises(RateLimitStoreUnavailable):
        await consume_shared_rate_limit(
            _Unavailable(), "a" * 64, "consumer_registration", 5,
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
