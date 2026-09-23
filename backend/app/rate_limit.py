"""Shared PostgreSQL rate limiting for abuse-sensitive API boundaries.

The database counter is the cross-instance coordination point.  Storage errors
are deliberately surfaced to callers so protected actions can fail closed.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta


class RateLimitStoreUnavailable(RuntimeError):
    """The shared counter could not be consulted; do not allow the action."""


def abuse_subject_hash(scope: str, subject: str) -> str:
    salt = os.getenv("ABUSE_HASH_SALT", "").strip()
    if not salt and os.getenv("ENVIRONMENT", "").lower() == "test":
        salt = "test-only-abuse-salt"
    if not salt:
        raise RateLimitStoreUnavailable("ABUSE_HASH_SALT is not configured")
    return hmac.new(salt.encode("utf-8"), f"{scope}:{subject}".encode("utf-8"), hashlib.sha256).hexdigest()


def configured_limit(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RateLimitStoreUnavailable(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RateLimitStoreUnavailable(f"{name} must be a positive integer")
    return value


async def consume_shared_rate_limit(connection, subject_hash: str, action: str, limit: int, now: datetime) -> int | None:
    window_started_at = now.replace(minute=0, second=0, microsecond=0)
    try:
        row = await connection.fetchrow(
            """
            insert into public.shared_rate_limits
              (subject_hash, action, window_started_at, request_count, expires_at)
            values ($1, $2, $3, 1, $4)
            on conflict (subject_hash, action, window_started_at) do update set
              request_count = public.shared_rate_limits.request_count + 1,
              expires_at = excluded.expires_at
            where public.shared_rate_limits.request_count < $5
            returning request_count
            """,
            subject_hash,
            action,
            window_started_at,
            window_started_at + timedelta(hours=1),
            limit,
        )
    except Exception as exc:
        raise RateLimitStoreUnavailable("shared rate-limit storage unavailable") from exc
    return int(row["request_count"]) if row else None
