"""Shared outbound timeout, retry, and cancellation contract."""

from __future__ import annotations

import asyncio
import errno
import math
import os
import random
import socket
import time
from urllib.error import HTTPError


class OutboundTimeoutConfigError(RuntimeError):
    """An outbound timeout environment setting is invalid."""


def _configured_positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise OutboundTimeoutConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise OutboundTimeoutConfigError(f"{name} must be a positive number")
    return value


def _configured_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise OutboundTimeoutConfigError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise OutboundTimeoutConfigError(f"{name} must be a positive integer")
    return value


def _configured_status_codes() -> frozenset[int]:
    raw = os.getenv("OUTBOUND_TRANSIENT_STATUS_CODES", "408,425,429,500,502,503,504")
    try:
        values = frozenset(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise OutboundTimeoutConfigError("OUTBOUND_TRANSIENT_STATUS_CODES must be comma-separated status codes") from exc
    if not values or any(value < 100 or value > 599 for value in values):
        raise OutboundTimeoutConfigError("OUTBOUND_TRANSIENT_STATUS_CODES must be comma-separated status codes")
    return values


DEFAULT_OUTBOUND_TIMEOUT_SECONDS = _configured_positive_float("OUTBOUND_TIMEOUT_SECONDS", 8.0)
TRANSIENT_STATUS_CODES = _configured_status_codes()
MAX_ATTEMPTS = _configured_positive_int("OUTBOUND_MAX_ATTEMPTS", 2)
BACKOFF_BASE_SECONDS = _configured_positive_float("OUTBOUND_BACKOFF_BASE_SECONDS", 0.25)
_CONNECTION_ERRNOS = frozenset({errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET, errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT})


def outbound_timeout(value: float | None = None) -> float:
    """Use the shared default only when a caller did not supply its own timeout."""
    return DEFAULT_OUTBOUND_TIMEOUT_SECONDS if value is None else value


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in TRANSIENT_STATUS_CODES
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError)):
        return True
    return isinstance(exc, OSError) and exc.errno in _CONNECTION_ERRNOS


def compute_backoff_attempt_seconds(attempt: int, rng: random.Random | None = None) -> float:
    if attempt < 1:
        raise ValueError("attempt must be positive")
    generator = rng if rng is not None else random
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 1) * generator.uniform(0.5, 1.5)


def fetch_with_retry(urlopen_callable, request, *, timeout: float | None = None, max_attempts: int | None = None, sleep=time.sleep, rng: random.Random | None = None):
    """Run an idempotent urllib operation with bounded retries for transient errors."""
    attempts = MAX_ATTEMPTS if max_attempts is None else max_attempts
    if attempts < 1:
        raise ValueError("max_attempts must be positive")
    effective_timeout = outbound_timeout(timeout)
    for attempt in range(1, attempts + 1):
        try:
            return urlopen_callable(request, timeout=effective_timeout)
        except BaseException as exc:
            if attempt == attempts or not is_transient(exc):
                raise
            sleep(compute_backoff_attempt_seconds(attempt, rng))
    raise RuntimeError("unreachable")


async def abortable_sleep(delay_seconds: float) -> None:
    """Cancellation propagates directly to async callers waiting to retry."""
    await asyncio.sleep(delay_seconds)
