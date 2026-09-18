from __future__ import annotations

from pathlib import Path

from backend.app.report_worker import (
    MAX_ATTEMPTS,
    backoff_seconds,
    classify_failure,
    claim_sql,
)


def test_claim_sql_is_one_atomic_update_returning_statement() -> None:
    normalized = " ".join(claim_sql().lower().split())
    assert normalized.startswith("with candidate as (")
    assert "for update skip locked" in normalized
    assert "update public.report_generation_outbox" in normalized
    assert "returning" in normalized
    assert normalized.count("select id") == 1


def test_retry_backoff_is_bounded_and_attempts_are_capped() -> None:
    assert MAX_ATTEMPTS == 3
    assert [backoff_seconds(attempt) for attempt in (1, 2, 3, 4)] == [5, 30, 300, 300]


def test_failure_classification_hides_raw_exception_text() -> None:
    failure = classify_failure(TimeoutError("secret database password"))
    assert failure.code == "dependency_timeout"
    assert failure.retryable is True
    assert failure.public_message == "报告生成依赖暂时不可用，请稍后重试。"
    assert "secret" not in failure.public_message


def test_unknown_failure_is_permanent_and_safe() -> None:
    failure = classify_failure(RuntimeError("private payload"))
    assert failure.code == "report_generation_failed"
    assert failure.retryable is False
    assert failure.public_message == "报告生成失败，请稍后重试。"
    assert "private" not in failure.public_message
