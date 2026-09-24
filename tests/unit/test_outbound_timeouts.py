import random
from urllib.error import HTTPError

import pytest

from backend.app import timeouts


def test_transient_errors_are_limited_to_transport_and_retryable_statuses():
    assert timeouts.is_transient(TimeoutError())
    assert timeouts.is_transient(ConnectionResetError())
    assert timeouts.is_transient(HTTPError("https://example.test", 429, "", {}, None))
    assert timeouts.is_transient(HTTPError("https://example.test", 503, "", {}, None))
    assert not timeouts.is_transient(ValueError())
    assert not timeouts.is_transient(HTTPError("https://example.test", 404, "", {}, None))


def test_backoff_is_seed_reproducible_and_within_jitter_band():
    first = [timeouts.compute_backoff_attempt_seconds(attempt, random.Random(0)) for attempt in range(1, 5)]
    second = [timeouts.compute_backoff_attempt_seconds(attempt, random.Random(0)) for attempt in range(1, 5)]
    assert first == second
    assert first == sorted(first)
    for attempt, value in enumerate(first, start=1):
        base = timeouts.BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        assert base * 0.5 <= value <= base * 1.5


def test_fetch_retries_transient_failure_then_returns_result():
    calls = []

    def urlopen_callable(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise TimeoutError()
        return "result"

    assert timeouts.fetch_with_retry(urlopen_callable, "request", sleep=lambda _: None) == "result"
    assert len(calls) == 2


def test_fetch_does_not_retry_non_transient_and_raises_original_error():
    calls = []

    def urlopen_callable(request, timeout):
        calls.append((request, timeout))
        raise ValueError("bad request")

    with pytest.raises(ValueError, match="bad request"):
        timeouts.fetch_with_retry(urlopen_callable, "request", sleep=lambda _: None)
    assert len(calls) == 1


def test_fetch_raises_last_error_after_attempt_limit():
    calls = []

    def urlopen_callable(request, timeout):
        calls.append((request, timeout))
        raise TimeoutError(str(len(calls)))

    with pytest.raises(TimeoutError, match="2"):
        timeouts.fetch_with_retry(urlopen_callable, "request", max_attempts=2, sleep=lambda _: None)
    assert len(calls) == 2
