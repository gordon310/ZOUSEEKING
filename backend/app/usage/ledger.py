"""Thread-safe offline model for atomic usage and quota accounting.

This module deliberately models the contract in memory. It is suitable for
deterministic tests and a local/staging adapter, but it is not a production
database implementation or migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Dict, Optional, Tuple
from uuid import UUID, uuid4


UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")
PeriodKey = Tuple[object, ...]
EventKey = Tuple[str, UUID, str, str]
ReservationIndexKey = Tuple[str, UUID, str, str]


class UsageKind(str, Enum):
    QUERY = "query"
    ANALYSIS = "analysis"
    SUBSCRIPTION = "subscription"
    EXPORT = "export"
    REPORT = "report"


@dataclass(frozen=True)
class Scope:
    kind: str
    id: UUID

    @classmethod
    def owner(cls, owner_user_id: UUID) -> "Scope":
        return cls("owner", owner_user_id)

    @classmethod
    def organization(cls, organization_id: UUID) -> "Scope":
        return cls("organization", organization_id)


@dataclass(frozen=True)
class LedgerResult:
    event_id: UUID
    period_id: UUID
    status: str
    scope: Scope
    kind: UsageKind
    units: int
    consumed: int
    reserved: int
    limit: int
    period_start: datetime
    period_end: datetime
    request_key: str


@dataclass(frozen=True)
class LedgerSummary:
    scope: Scope
    kind: UsageKind
    consumed: int
    reserved: int
    limit: int
    period_start: datetime
    period_end: datetime


class UsageError(Exception):
    """Base class for public-safe usage errors."""


class IdempotencyConflict(UsageError):
    """A key was reused with a different request or state."""


class QuotaExceeded(UsageError):
    """The period has no capacity for the requested units."""


class ReservationNotFound(UsageError):
    """A reservation transition references an unknown reservation."""


class ReservationStateError(UsageError):
    """A reservation is no longer active."""


@dataclass
class _Period:
    scope: Scope
    kind: UsageKind
    period_start: datetime
    period_end: datetime
    limit: int
    consumed: int = 0
    reserved: int = 0
    period_id: UUID = field(default_factory=uuid4)


@dataclass
class _Event:
    event_id: UUID
    operation: str
    request_key: str
    fingerprint: Tuple[object, ...]
    status: str
    units: int
    period_key: PeriodKey


@dataclass
class _Reservation:
    period_key: PeriodKey
    reservation_key: str
    units: int
    status: str


def _as_utc_plus_8(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    return value.astimezone(UTC_PLUS_8)


def period_bounds(occurred_at: datetime, period: str) -> Tuple[datetime, datetime]:
    """Return the UTC+8 start and exclusive end for a day or month."""

    local = _as_utc_plus_8(occurred_at)
    if period == "day":
        start_date = local.date()
        end_date = start_date + timedelta(days=1)
    elif period == "month":
        start_date = local.date().replace(day=1)
        if start_date.month == 12:
            end_date = date(start_date.year + 1, 1, 1)
        else:
            end_date = date(start_date.year, start_date.month + 1, 1)
    else:
        raise ValueError("period must be day or month")
    return (
        datetime.combine(start_date, time.min, tzinfo=UTC_PLUS_8),
        datetime.combine(end_date, time.min, tzinfo=UTC_PLUS_8),
    )


class Ledger:
    """Atomic in-memory model of the usage ledger contract."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._periods: Dict[PeriodKey, _Period] = {}
        self._events: Dict[EventKey, _Event] = {}
        self._reservations: Dict[Tuple[PeriodKey, str], _Reservation] = {}
        self._reservation_index: Dict[ReservationIndexKey, PeriodKey] = {}

    @staticmethod
    def _validate_request(units: int, limit: int, request_key: str) -> None:
        if not isinstance(units, int) or isinstance(units, bool) or units <= 0:
            raise ValueError("units must be a positive integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if not isinstance(request_key, str) or not request_key or len(request_key) > 128:
            raise ValueError("request_key must be 1-128 characters")

    def _get_period(
        self,
        scope: Scope,
        kind: UsageKind,
        limit: int,
        occurred_at: datetime,
        period: str,
    ) -> Tuple[PeriodKey, _Period]:
        period_start, period_end = period_bounds(occurred_at, period)
        key: PeriodKey = (scope.kind, scope.id, kind.value, period_start)
        current = self._periods.get(key)
        if current is None:
            current = _Period(scope, kind, period_start, period_end, limit)
            self._periods[key] = current
        elif current.limit != limit:
            raise IdempotencyConflict("quota limit changed for an existing period")
        return key, current

    @staticmethod
    def _fingerprint(
        scope: Scope,
        kind: UsageKind,
        units: int,
        actor_user_id: UUID,
        operation: str,
        limit: int,
        reservation_key: Optional[str],
    ) -> Tuple[object, ...]:
        return (scope.kind, scope.id, kind.value, units, actor_user_id, operation, limit, reservation_key)

    @staticmethod
    def _result(period: _Period, event: _Event, status: Optional[str] = None) -> LedgerResult:
        return LedgerResult(
            event_id=event.event_id,
            period_id=period.period_id,
            status=status or event.status,
            scope=period.scope,
            kind=period.kind,
            units=event.units,
            consumed=period.consumed,
            reserved=period.reserved,
            limit=period.limit,
            period_start=period.period_start,
            period_end=period.period_end,
            request_key=event.request_key,
        )

    def _existing(
        self,
        scope: Scope,
        request_key: str,
        operation: str,
        fingerprint: Tuple[object, ...],
    ) -> Optional[LedgerResult]:
        event = self._events.get((scope.kind, scope.id, request_key, operation))
        if event is None:
            return None
        if event.fingerprint != fingerprint:
            raise IdempotencyConflict("request_key was reused with different parameters")
        return self._result(self._periods[event.period_key], event, "duplicate")

    @staticmethod
    def _ensure_capacity(period: _Period, units: int) -> None:
        if period.consumed + period.reserved + units > period.limit:
            raise QuotaExceeded("usage quota exceeded")

    def consume(
        self,
        scope: Scope,
        kind: UsageKind,
        units: int,
        limit: int,
        request_key: str,
        actor_user_id: UUID,
        occurred_at: datetime,
        period: str,
    ) -> LedgerResult:
        self._validate_request(units, limit, request_key)
        with self._lock:
            fingerprint = self._fingerprint(scope, kind, units, actor_user_id, "consume", limit, None)
            existing = self._existing(scope, request_key, "consume", fingerprint)
            if existing:
                return existing
            period_key, current = self._get_period(scope, kind, limit, occurred_at, period)
            self._ensure_capacity(current, units)
            event = _Event(uuid4(), "consume", request_key, fingerprint, "consumed", units, period_key)
            self._events[(scope.kind, scope.id, request_key, "consume")] = event
            current.consumed += units
            return self._result(current, event)

    def reserve(self, **kwargs: object) -> LedgerResult:
        return self._reserve_or_transition("reserve", **kwargs)

    def commit(self, *, reservation_key: str, **kwargs: object) -> LedgerResult:
        return self._reserve_or_transition("commit", reservation_key=reservation_key, **kwargs)

    def release(self, *, reservation_key: str, **kwargs: object) -> LedgerResult:
        return self._reserve_or_transition("release", reservation_key=reservation_key, **kwargs)

    def _reserve_or_transition(
        self,
        operation: str,
        *,
        scope: Scope,
        kind: UsageKind,
        units: int,
        limit: int,
        request_key: str,
        actor_user_id: UUID,
        occurred_at: datetime,
        period: str,
        reservation_key: Optional[str] = None,
    ) -> LedgerResult:
        self._validate_request(units, limit, request_key)
        if operation == "reserve" and reservation_key is not None:
            raise ValueError("reservation_key is assigned by request_key for reserve")
        if operation != "reserve" and (
            not isinstance(reservation_key, str) or not reservation_key or len(reservation_key) > 128
        ):
            raise ValueError("reservation_key is required")
        with self._lock:
            effective_reservation_key = request_key if operation == "reserve" else reservation_key
            fingerprint = self._fingerprint(
                scope,
                kind,
                units,
                actor_user_id,
                operation,
                limit,
                effective_reservation_key,
            )
            existing = self._existing(scope, request_key, operation, fingerprint)
            if existing:
                return existing

            if operation == "reserve":
                period_key, current = self._get_period(scope, kind, limit, occurred_at, period)
            else:
                reservation_index_key = (scope.kind, scope.id, kind.value, reservation_key)
                period_key = self._reservation_index.get(reservation_index_key)
                if period_key is None:
                    raise ReservationNotFound("reservation not found")
                current = self._periods[period_key]
                if current.limit != limit:
                    raise IdempotencyConflict("quota limit changed for an existing period")

            if operation == "reserve":
                assert effective_reservation_key is not None
                reservation_id = (period_key, effective_reservation_key)
                prior = self._reservations.get(reservation_id)
                if prior is not None or (
                    self._reservation_index.get((scope.kind, scope.id, kind.value, effective_reservation_key))
                    not in (None, period_key)
                ):
                    raise IdempotencyConflict("reservation_key was already used")
                self._ensure_capacity(current, units)
                current.reserved += units
                self._reservations[reservation_id] = _Reservation(
                    period_key, effective_reservation_key, units, "reserved"
                )
                self._reservation_index[(scope.kind, scope.id, kind.value, effective_reservation_key)] = period_key
                status = "reserved"
            else:
                assert reservation_key is not None
                reservation_id = (period_key, reservation_key)
                prior = self._reservations.get(reservation_id)
                if prior is None:
                    raise ReservationNotFound("reservation not found")
                if prior.units != units:
                    raise IdempotencyConflict("reservation units do not match")
                if prior.status != "reserved":
                    raise ReservationStateError("reservation is no longer active")
                current.reserved -= units
                if operation == "commit":
                    current.consumed += units
                    status = "committed"
                else:
                    status = "released"
                prior.status = status

            event = _Event(uuid4(), operation, request_key, fingerprint, status, units, period_key)
            self._events[(scope.kind, scope.id, request_key, operation)] = event
            return self._result(current, event)

    def summary(self, scope: Scope, kind: UsageKind, occurred_at: datetime, period: str) -> LedgerSummary:
        with self._lock:
            start, end = period_bounds(occurred_at, period)
            key: PeriodKey = (scope.kind, scope.id, kind.value, start)
            current = self._periods.get(key)
            if current is None:
                return LedgerSummary(scope, kind, 0, 0, 0, start, end)
            return LedgerSummary(
                scope,
                kind,
                current.consumed,
                current.reserved,
                current.limit,
                current.period_start,
                current.period_end,
            )
