from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.usage.ledger import (
    UTC_PLUS_8,
    IdempotencyConflict,
    Ledger,
    QuotaExceeded,
    ReservationStateError,
    Scope,
    UsageKind,
)


OWNER_ID = UUID("00000000-0000-0000-0000-000000000030")
ORG_ID = UUID("00000000-0000-0000-0000-000000000040")
UTC = timezone.utc


def test_day_period_uses_japan_boundary() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)

    before_midnight = ledger.consume(
        scope,
        UsageKind.QUERY,
        units=1,
        limit=5,
        request_key="day-before",
        actor_user_id=OWNER_ID,
        occurred_at=datetime(2026, 8, 31, 15, 59, tzinfo=UTC),
        period="day",
    )
    after_midnight = ledger.consume(
        scope,
        UsageKind.QUERY,
        units=1,
        limit=5,
        request_key="day-after",
        actor_user_id=OWNER_ID,
        occurred_at=datetime(2026, 8, 31, 16, 0, tzinfo=UTC),
        period="day",
    )

    assert before_midnight.period_start == datetime(2026, 8, 31, tzinfo=UTC_PLUS_8)
    assert after_midnight.period_start == datetime(2026, 9, 1, tzinfo=UTC_PLUS_8)
    assert before_midnight.period_id != after_midnight.period_id


def test_month_period_and_summary_are_numeric_and_bounded() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)
    result = ledger.consume(
        scope,
        UsageKind.REPORT,
        units=2,
        limit=3,
        request_key="month-1",
        actor_user_id=OWNER_ID,
        occurred_at=datetime(2026, 8, 31, 16, 0, tzinfo=UTC),
        period="month",
    )

    summary = ledger.summary(
        scope,
        UsageKind.REPORT,
        datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        "month",
    )
    assert result.period_start == datetime(2026, 9, 1, tzinfo=UTC_PLUS_8)
    assert result.period_end == datetime(2026, 10, 1, tzinfo=UTC_PLUS_8)
    assert (summary.consumed, summary.reserved, summary.limit) == (2, 0, 3)


def test_consume_is_idempotent_and_rejects_fingerprint_conflicts() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)
    common = dict(
        scope=scope,
        kind=UsageKind.QUERY,
        limit=5,
        actor_user_id=OWNER_ID,
        occurred_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        period="day",
    )

    first = ledger.consume(units=1, request_key="same", **common)
    duplicate = ledger.consume(units=1, request_key="same", **common)

    assert duplicate.status == "duplicate"
    assert duplicate.event_id == first.event_id
    assert ledger.summary(scope, UsageKind.QUERY, common["occurred_at"], "day").consumed == 1
    with pytest.raises(IdempotencyConflict):
        ledger.consume(units=2, request_key="same", **common)


def test_quota_rejection_does_not_mutate_counter_or_reservation() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    ledger.consume(scope, UsageKind.QUERY, 1, 1, "accepted", OWNER_ID, now, "day")

    with pytest.raises(QuotaExceeded):
        ledger.consume(scope, UsageKind.QUERY, 1, 1, "rejected", OWNER_ID, now, "day")

    summary = ledger.summary(scope, UsageKind.QUERY, now, "day")
    assert (summary.consumed, summary.reserved, summary.limit) == (1, 0, 1)


def test_owner_and_organization_scopes_are_isolated() -> None:
    ledger = Ledger()
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    owner = ledger.consume(Scope.owner(OWNER_ID), UsageKind.QUERY, 1, 1, "same-key", OWNER_ID, now, "day")
    organization = ledger.consume(
        Scope.organization(ORG_ID), UsageKind.QUERY, 1, 1, "same-key", OWNER_ID, now, "day"
    )

    assert owner.status == organization.status == "consumed"
    assert owner.scope != organization.scope


def test_reservation_commit_uses_original_period_and_is_idempotent() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)
    reserve_at = datetime(2026, 8, 31, 15, 59, tzinfo=UTC)
    commit_at = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)

    reserved = ledger.reserve(
        scope=scope,
        kind=UsageKind.ANALYSIS,
        units=2,
        limit=3,
        request_key="reservation-1",
        actor_user_id=OWNER_ID,
        occurred_at=reserve_at,
        period="day",
    )
    committed = ledger.commit(
        scope=scope,
        kind=UsageKind.ANALYSIS,
        units=2,
        limit=3,
        request_key="commit-1",
        actor_user_id=OWNER_ID,
        occurred_at=commit_at,
        period="day",
        reservation_key="reservation-1",
    )
    duplicate = ledger.commit(
        scope=scope,
        kind=UsageKind.ANALYSIS,
        units=2,
        limit=3,
        request_key="commit-1",
        actor_user_id=OWNER_ID,
        occurred_at=commit_at,
        period="day",
        reservation_key="reservation-1",
    )

    assert reserved.status == "reserved"
    assert committed.status == "committed"
    assert committed.period_start == reserved.period_start
    assert duplicate.status == "duplicate"
    assert ledger.summary(scope, UsageKind.ANALYSIS, reserve_at, "day").consumed == 2
    assert ledger.summary(scope, UsageKind.ANALYSIS, commit_at, "day").consumed == 0


def test_release_and_transition_fingerprint_are_safe() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    ledger.reserve(
        scope=scope,
        kind=UsageKind.EXPORT,
        units=1,
        limit=1,
        request_key="reservation-2",
        actor_user_id=OWNER_ID,
        occurred_at=now,
        period="day",
    )
    released = ledger.release(
        scope=scope,
        kind=UsageKind.EXPORT,
        units=1,
        limit=1,
        request_key="release-1",
        actor_user_id=OWNER_ID,
        occurred_at=now,
        period="day",
        reservation_key="reservation-2",
    )
    assert released.status == "released"
    assert ledger.summary(scope, UsageKind.EXPORT, now, "day").reserved == 0

    with pytest.raises(ReservationStateError):
        ledger.release(
            scope=scope,
            kind=UsageKind.EXPORT,
            units=1,
            limit=1,
            request_key="release-2",
            actor_user_id=OWNER_ID,
            occurred_at=now,
            period="day",
            reservation_key="reservation-2",
        )
    with pytest.raises(IdempotencyConflict):
        ledger.release(
            scope=scope,
            kind=UsageKind.EXPORT,
            units=1,
            limit=1,
            request_key="release-1",
            actor_user_id=OWNER_ID,
            occurred_at=now,
            period="day",
            reservation_key="different-reservation",
        )


def test_limit_one_allows_only_one_concurrent_consume() -> None:
    ledger = Ledger()
    scope = Scope.owner(OWNER_ID)
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    def attempt(index: int) -> str:
        try:
            ledger.consume(scope, UsageKind.QUERY, 1, 1, f"concurrent-{index}", OWNER_ID, now, "day")
        except QuotaExceeded:
            return "quota"
        return "accepted"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))

    assert outcomes.count("accepted") == 1
    assert outcomes.count("quota") == 7
