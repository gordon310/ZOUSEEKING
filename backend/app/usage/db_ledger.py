"""PostgreSQL adapter for the usage ledger contract.

This module mirrors the public semantics of :class:`backend.app.usage.ledger.Ledger`
(the thread-safe offline model) but persists every fact atomically in the V1
usage tables created by ``supabase/migrations/20260905000300_v1_usage_ledger.sql``
(which depends on ``20260905000100_v1_organizations.sql``):

* ``usage_quotas`` - one counter row per ``(scope_key, usage_kind, period_key)``
  holding ``limit_units``, ``consumed_units`` and ``reserved_units``.  Capacity
  checks are conditional ``UPDATE ... WHERE consumed_units + reserved_units +
  units <= limit_units RETURNING`` statements: PostgreSQL serialises the row
  lock and re-evaluates the predicate, so two workers can never oversell the
  last unit.
* ``usage_events`` - append-only audit trail (the table trigger rejects
  ``UPDATE``/``DELETE``).  One row is inserted per metered operation; a
  reservation lifecycle is *reserve* -> *commit* | *release*, where the
  transition event repeats the original reserve's ``period_key`` so a commit
  that crosses the UTC+8 day boundary still lands in the original period.
* ``usage_idempotency`` - registry of processed ``(scope, kind, operation,
  idempotency_key)`` requests; its two unique constraints make replay
  detection atomic: the same fingerprint on the same (scope, kind, operation)
  is recorded once (duplicate replies), and reusing an idempotency key with a
  different fingerprint raises ``IdempotencyConflict``.

One transaction per operation
-----------------------------
Every public method acquires a connection from an ``asyncpg`` pool and runs
inside a single ``async with conn.transaction()``.  The counter mutation and
the event/idempotency inserts commit together or not at all, so a failed
capacity check leaves no trace (mirroring the offline model, where a rejected
request never mutates a period).

Two serialisation layers keep replays race-free:

* a transaction-level advisory lock on ``(scope, kind, operation,
  idempotency_key)`` serialises every request that shares a client key, even
  when two attempts straddle a UTC+8 period boundary (and would otherwise
  lock different quota rows);
* a ``SELECT ... FOR UPDATE`` on the charged ``usage_quotas`` row serialises
  capacity checks of the same bucket, so concurrent consume/reserve/commit of
  one period cannot oversell ``limit_units``.

Quota limit source
------------------
Unlike the offline :class:`Ledger`, whose ``consume``/``reserve`` calls pass an
explicit ``limit``, the Postgres adapter treats ``usage_quotas.limit_units``
as the authority.  The public ``limit`` argument is optional and is used only
for two purposes: provisioning a missing quota row on first touch (the offline
model's implicit period creation) and raising ``IdempotencyConflict`` when it
disagrees with an existing row (the offline "quota limit changed" check).
When no quota row exists and no limit is passed the operation is rejected with
``QuotaExceeded`` (zero capacity, exactly like the offline model called with
``limit=0``).

Fingerprints
------------
The stored fingerprint is the offline ``Ledger._fingerprint`` tuple extended
with the charged period key and serialised to deterministic text:

``(scope.kind, scope.id, kind, units, actor_user_id, operation, limit,
reservation_key, period_key)``

The first eight components reproduce the offline tuple 1:1 (so a fingerprint
computed here for a provisioned row equals the offline string for the same
logical request); ``period_key`` is appended because the V1 registry
constraints are global per ``(scope, kind, operation)`` and must not collapse
two identical requests that charge different UTC+8 buckets (daily/monthly
resets would otherwise never meter twice).

Idempotency
-----------
Replay detection follows the offline model's ordering (fingerprint checked
against the stored registry before any state mutation) and the migration's
two unique constraints:

* same ``idempotency_key``, same fingerprint -> ``duplicate`` result,
* same ``idempotency_key``, different fingerprint -> ``IdempotencyConflict``,
* same fingerprint under a different key -> ``duplicate`` (the migration
  records an identical request once: "repeated identical requests return
  duplicate instead of double-metering").

Two deliberate consequences of the fingerprint-unique registry (both are
required by the frozen schema and documented in the tests):

* two *different* idempotency keys carrying an identical request are
  deduplicated in the database, whereas the offline model (keyed by
  ``request_key`` only) would meter them separately;
* reusing a client key after a UTC+8 period boundary computes a different
  fingerprint (the period component), which the offline model would not; the
  database treats it as a parameter conflict rather than a replay.  Fresh keys
  across periods always meter independently, which is what daily/monthly
  quota resets require.

Reservation state is derived from the event stream: a reservation is active
only while a ``reserve`` event exists for ``(scope, kind, reservation_key)``
and no ``commit``/``release`` event does.  A terminal reservation is a state
error for any *new* transition key, and a duplicate for its original key
(offline ordering).

Usage kind vocabulary
---------------------
The offline enum (``query/analysis/subscription/export/report``) predates the
frozen V1 product vocabulary (``query/report/stats_query/export_row/
subscription_slot``), so the adapter validates kinds against the database
CHECK set.  ``UsageKind`` members whose value is in that set (``QUERY``,
``REPORT``) are accepted directly; the remaining product kinds are passed as
their database strings.

Schema gate
-----------
The adapter never initialises schema and never applies migrations.  Against a
database that lacks the V1 tables every call raises an
``asyncpg.UndefinedTableError``.  Callers must connect as a role that bypasses
RLS (table owner or ``service_role``): these tables are trusted-server only
and authenticated/anon hold no write grants.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Optional, Tuple, Union
from uuid import UUID

import asyncpg

from ..db import get_pool
from .ledger import (
    IdempotencyConflict,
    LedgerResult,
    LedgerSummary,
    QuotaExceeded,
    ReservationNotFound,
    ReservationStateError,
    Scope,
    UsageError,
    UsageKind,
    UTC_PLUS_8,
    period_bounds,
)

# The frozen V1 usage_kind vocabulary (usage_*_usage_kind_allowed CHECKs).
DB_USAGE_KINDS = frozenset(
    {"query", "report", "stats_query", "export_row", "subscription_slot"}
)

_PERIODS = ("day", "month")


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _scope_key(scope: Scope) -> str:
    """Serialise a Scope to its 'user:<uuid>' / 'org:<uuid>' column form."""
    if scope.kind == "owner":
        return f"user:{scope.id}"
    if scope.kind == "organization":
        return f"org:{scope.id}"
    raise ValueError("scope.kind must be 'owner' or 'organization'")


def _normalise_kind(kind: Union[UsageKind, str]) -> str:
    """Return the V1 database usage_kind token for a kind argument."""
    if isinstance(kind, UsageKind):
        value = kind.value
    elif isinstance(kind, str):
        value = kind
    else:
        raise ValueError("kind must be a UsageKind or usage_kind string")
    if value not in DB_USAGE_KINDS:
        raise ValueError(f"usage_kind must be one of {sorted(DB_USAGE_KINDS)}")
    return value


def _kind_of(kind: str) -> Union[UsageKind, str]:
    """Return the offline UsageKind member when one exists for the DB token."""
    for member in UsageKind:
        if member.value == kind:
            return member
    return kind


def _period_bucket(occurred_at: datetime, period: str) -> Tuple[str, datetime, datetime]:
    """Return (DB period_key, UTC+8 start, UTC+8 exclusive end)."""
    if period not in _PERIODS:
        raise ValueError("period must be 'day' or 'month'")
    start, end = period_bounds(occurred_at, period)
    key = start.strftime("%Y-%m-%d") if period == "day" else start.strftime("%Y-%m")
    return key, start, end


def _bucket_bounds(period_key: str) -> Tuple[datetime, datetime]:
    """Recover UTC+8 (start, exclusive end) from a stored 'YYYY-MM-DD'/'YYYY-MM' key."""
    parts = str(period_key).split("-")
    if len(parts) == 3:
        return period_bounds(
            datetime.strptime(period_key, "%Y-%m-%d").replace(tzinfo=UTC_PLUS_8), "day"
        )
    if len(parts) == 2:
        return period_bounds(
            datetime.strptime(period_key, "%Y-%m").replace(tzinfo=UTC_PLUS_8), "month"
        )
    raise ValueError(f"malformed period_key: {period_key!r}")


def _fingerprint(
    scope: Scope,
    kind: str,
    units: int,
    actor_user_id: UUID,
    operation: str,
    limit: int,
    reservation_key: Optional[str],
    period_key: str,
) -> str:
    """Deterministic text mirror of the offline fingerprint tuple (+ period)."""
    payload = (
        scope.kind,
        str(scope.id),
        kind,
        units,
        str(actor_user_id),
        operation,
        limit,
        reservation_key,
        period_key,
    )
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _make_result(
    *,
    scope: Scope,
    kind: str,
    event_id: UUID,
    period_id: Optional[UUID],
    status: str,
    units: int,
    consumed: int,
    reserved: int,
    limit: int,
    period_start: datetime,
    period_end: datetime,
    request_key: str,
) -> LedgerResult:
    return LedgerResult(
        event_id=event_id,
        period_id=period_id,
        status=status,
        scope=scope,
        kind=_kind_of(kind),
        units=units,
        consumed=consumed,
        reserved=reserved,
        limit=limit,
        period_start=period_start,
        period_end=period_end,
        request_key=request_key,
    )


def _validate_common(
    units: int,
    request_key: str,
    actor_user_id: UUID,
    occurred_at: Optional[datetime],
    period: Optional[str],
) -> None:
    if not _is_positive_int(units):
        raise ValueError("units must be a positive integer")
    if not isinstance(request_key, str) or not request_key or len(request_key) > 128:
        raise ValueError("request_key must be 1-128 characters")
    if not isinstance(actor_user_id, UUID):
        raise ValueError("actor_user_id must be a UUID")
    if period is not None and period not in _PERIODS:
        raise ValueError("period must be 'day' or 'month'")
    # The offline model only requires a tz-aware clock for the period-mapping
    # operations (consume/reserve); transitions ignore occurred_at entirely.
    if occurred_at is not None and (
        not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None
    ):
        raise ValueError("occurred_at must include a timezone")


def _is_valid_key(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 128


async def _advisory_lock(conn: asyncpg.Connection, *parts: str) -> None:
    """Take a blocking transaction-level advisory lock for one client key.

    All requests sharing ``(scope, kind, operation, idempotency_key)`` are
    serialised on this lock (auto-released at commit/rollback), so a retry
    that straddles a UTC+8 boundary cannot race the original request even
    though it locks a different quota row.
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    key = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
    await conn.execute("select pg_advisory_xact_lock($1)", key)


async def _select_event_by_fingerprint(
    conn: asyncpg.Connection, scope_key: str, kind: str, operation: str, fingerprint: str
):
    return await conn.fetchrow(
        "select id, period_key, units, idempotency_key from public.usage_events"
        " where scope_key = $1 and usage_kind = $2 and operation = $3"
        "   and fingerprint = $4"
        " order by created_at asc, id asc limit 1",
        scope_key,
        kind,
        operation,
        fingerprint,
    )


class PostgresLedger:
    """Asyncpg implementation of the usage ledger contract over the V1 tables.

    :param pool: an optional asyncpg pool; defaults to the application-wide
        pool from :func:`backend.app.db.get_pool`.
    """

    def __init__(self, pool: Optional[asyncpg.Pool] = None) -> None:
        self._pool = pool

    def _acquire(self) -> asyncpg.Pool:
        return self._pool if self._pool is not None else get_pool()

    # -- shared internals ----------------------------------------------------

    async def _lock_quota_or_provision(
        self,
        conn: asyncpg.Connection,
        *,
        scope_key: str,
        kind: str,
        period_key: str,
        limit: Optional[int],
    ):
        """Return the counter row (locked), provisioning it on first touch."""
        row = await conn.fetchrow(
            "select id, limit_units, consumed_units, reserved_units"
            " from public.usage_quotas"
            " where scope_key = $1 and usage_kind = $2 and period_key = $3"
            " for update",
            scope_key,
            kind,
            period_key,
        )
        if row is None:
            if limit is None:
                raise QuotaExceeded("usage quota exceeded")
            await conn.execute(
                "insert into public.usage_quotas"
                " (scope_key, usage_kind, period_key, limit_units)"
                " values ($1, $2, $3, $4)"
                " on conflict (scope_key, usage_kind, period_key) do nothing",
                scope_key,
                kind,
                period_key,
                int(limit),
            )
            row = await conn.fetchrow(
                "select id, limit_units, consumed_units, reserved_units"
                " from public.usage_quotas"
                " where scope_key = $1 and usage_kind = $2 and period_key = $3"
                " for update",
                scope_key,
                kind,
                period_key,
            )
        if row is None:  # pragma: no cover - unreachable after the upsert
            raise QuotaExceeded("usage quota exceeded")
        return row

    @staticmethod
    async def _registry_by_key(
        conn: asyncpg.Connection, scope_key: str, kind: str, operation: str, request_key: str
    ):
        return await conn.fetchrow(
            "select fingerprint from public.usage_idempotency"
            " where scope_key = $1 and usage_kind = $2 and operation = $3"
            "   and idempotency_key = $4",
            scope_key,
            kind,
            operation,
            request_key,
        )

    @staticmethod
    async def _registry_by_fingerprint(
        conn: asyncpg.Connection, scope_key: str, kind: str, operation: str, fingerprint: str
    ):
        return await conn.fetchrow(
            "select idempotency_key from public.usage_idempotency"
            " where scope_key = $1 and usage_kind = $2 and operation = $3"
            "   and fingerprint = $4",
            scope_key,
            kind,
            operation,
            fingerprint,
        )

    async def _replay_result(
        self,
        conn: asyncpg.Connection,
        *,
        scope: Scope,
        kind: str,
        operation: str,
        fingerprint: str,
    ) -> LedgerResult:
        """Rebuild the original result for a stored fingerprint (status duplicate)."""
        event = await _select_event_by_fingerprint(
            conn, _scope_key(scope), kind, operation, fingerprint
        )
        if event is None:
            raise UsageError("idempotency registry points at no event")
        period_key = event["period_key"]
        period_start, period_end = _bucket_bounds(period_key)
        quota = await conn.fetchrow(
            "select id, limit_units, consumed_units, reserved_units"
            " from public.usage_quotas"
            " where scope_key = $1 and usage_kind = $2 and period_key = $3",
            _scope_key(scope),
            kind,
            period_key,
        )
        return _make_result(
            scope=scope,
            kind=kind,
            event_id=event["id"],
            period_id=None if quota is None else quota["id"],
            status="duplicate",
            units=event["units"],
            consumed=0 if quota is None else quota["consumed_units"],
            reserved=0 if quota is None else quota["reserved_units"],
            limit=0 if quota is None else quota["limit_units"],
            period_start=period_start,
            period_end=period_end,
            request_key=event["idempotency_key"],
        )

    async def _replay_outcome(
        self,
        conn: asyncpg.Connection,
        *,
        scope: Scope,
        kind: str,
        operation: str,
        request_key: str,
        fingerprint: str,
    ) -> Optional[LedgerResult]:
        """Return a duplicate result for a replay, or None for a new request.

        Raises ``IdempotencyConflict`` when the client key was reused with
        different parameters (offline ``Ledger._existing`` behaviour).
        """
        scope_key = _scope_key(scope)
        by_key = await self._registry_by_key(
            conn, scope_key, kind, operation, request_key
        )
        if by_key is not None:
            if by_key["fingerprint"] != fingerprint:
                raise IdempotencyConflict(
                    "request_key was reused with different parameters"
                )
            return await self._replay_result(
                conn, scope=scope, kind=kind, operation=operation, fingerprint=fingerprint
            )
        by_fingerprint = await self._registry_by_fingerprint(
            conn, scope_key, kind, operation, fingerprint
        )
        if by_fingerprint is not None:
            return await self._replay_result(
                conn, scope=scope, kind=kind, operation=operation, fingerprint=fingerprint
            )
        return None

    @staticmethod
    async def _insert_event_and_registry(
        conn: asyncpg.Connection,
        *,
        scope_key: str,
        kind: str,
        operation: str,
        units: int,
        period_key: str,
        request_key: str,
        actor_user_id: UUID,
        fingerprint: str,
        reservation_key: Optional[str],
    ) -> UUID:
        """Record the append-only event and registry row (same transaction)."""
        event_id = await conn.fetchval(
            "insert into public.usage_events"
            " (scope_key, usage_kind, operation, units, period_key, idempotency_key,"
            "  fingerprint, reservation_key, actor_user_id)"
            " values ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
            " returning id",
            scope_key,
            kind,
            operation,
            units,
            period_key,
            request_key,
            fingerprint,
            reservation_key,
            actor_user_id,
        )
        try:
            await conn.execute(
                "insert into public.usage_idempotency"
                " (scope_key, usage_kind, operation, idempotency_key, fingerprint)"
                " values ($1, $2, $3, $4, $5)",
                scope_key,
                kind,
                operation,
                request_key,
                fingerprint,
            )
        except asyncpg.UniqueViolationError:
            # Defensive: the registry is claimed first inside the same lock, so
            # a unique violation here means a concurrent identical request
            # committed between the capacity update and the insert.  The whole
            # transaction (including the counter change) rolls back, so the
            # safe reply is a duplicate of the winner.
            raise QuotaExceeded("usage quota exceeded") from None
        return event_id

    @staticmethod
    async def _read_quota(
        conn: asyncpg.Connection, scope_key: str, kind: str, period_key: str
    ):
        return await conn.fetchrow(
            "select id, limit_units, consumed_units, reserved_units"
            " from public.usage_quotas"
            " where scope_key = $1 and usage_kind = $2 and period_key = $3",
            scope_key,
            kind,
            period_key,
        )

    # -- consume / reserve ---------------------------------------------------

    async def consume(
        self,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        units: int,
        limit: Optional[int] = None,
        request_key: str,
        actor_user_id: UUID,
        occurred_at: datetime,
        period: str,
    ) -> LedgerResult:
        """Atomically count ``units`` of immediate usage (status 'consumed')."""
        return await self._charge(
            "consume",
            scope=scope,
            kind=kind,
            units=units,
            limit=limit,
            request_key=request_key,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            period=period,
        )

    async def reserve(
        self,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        units: int,
        limit: Optional[int] = None,
        request_key: str,
        actor_user_id: UUID,
        occurred_at: datetime,
        period: str,
    ) -> LedgerResult:
        """Atomically reserve capacity; the reservation key is the request key."""
        return await self._charge(
            "reserve",
            scope=scope,
            kind=kind,
            units=units,
            limit=limit,
            request_key=request_key,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            period=period,
        )

    async def _charge(
        self,
        operation: str,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        units: int,
        limit: Optional[int],
        request_key: str,
        actor_user_id: UUID,
        occurred_at: datetime,
        period: str,
    ) -> LedgerResult:
        _validate_common(units, request_key, actor_user_id, occurred_at, period)
        kind_text = _normalise_kind(kind)
        scope_key = _scope_key(scope)
        period_key, start, end = _period_bucket(occurred_at, period)
        reservation_key = request_key if operation == "reserve" else None

        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _advisory_lock(conn, scope_key, kind_text, operation, request_key)
                quota = await self._lock_quota_or_provision(
                    conn, scope_key=scope_key, kind=kind_text,
                    period_key=period_key, limit=limit,
                )
                row_limit = int(quota["limit_units"])
                if limit is not None and int(limit) != row_limit:
                    raise IdempotencyConflict("quota limit changed for an existing period")
                fingerprint = _fingerprint(
                    scope, kind_text, units, actor_user_id, operation,
                    row_limit, reservation_key, period_key,
                )
                replay = await self._replay_outcome(
                    conn, scope=scope, kind=kind_text, operation=operation,
                    request_key=request_key, fingerprint=fingerprint,
                )
                if replay is not None:
                    return replay

                column = "consumed_units" if operation == "consume" else "reserved_units"
                updated = await conn.fetchrow(
                    "update public.usage_quotas"
                    f" set {column} = {column} + $1"
                    " where scope_key = $2 and usage_kind = $3 and period_key = $4"
                    "   and consumed_units + reserved_units + $1 <= limit_units"
                    " returning id, limit_units, consumed_units, reserved_units",
                    units,
                    scope_key,
                    kind_text,
                    period_key,
                )
                if updated is None:
                    raise QuotaExceeded("usage quota exceeded")

                event_id = await self._insert_event_and_registry(
                    conn,
                    scope_key=scope_key,
                    kind=kind_text,
                    operation=operation,
                    units=units,
                    period_key=period_key,
                    request_key=request_key,
                    actor_user_id=actor_user_id,
                    fingerprint=fingerprint,
                    reservation_key=reservation_key,
                )
                return _make_result(
                    scope=scope,
                    kind=kind_text,
                    event_id=event_id,
                    period_id=updated["id"],
                    status="consumed" if operation == "consume" else "reserved",
                    units=units,
                    consumed=updated["consumed_units"],
                    reserved=updated["reserved_units"],
                    limit=updated["limit_units"],
                    period_start=start,
                    period_end=end,
                    request_key=request_key,
                )

    # -- reservation transitions ---------------------------------------------

    async def commit(
        self,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        units: int,
        limit: Optional[int] = None,
        request_key: str,
        actor_user_id: UUID,
        occurred_at: Optional[datetime] = None,
        period: Optional[str] = None,
        reservation_key: str,
    ) -> LedgerResult:
        """Turn an active reservation into usage in its *original* period."""
        return await self._transition(
            "commit",
            scope=scope,
            kind=kind,
            units=units,
            limit=limit,
            request_key=request_key,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            period=period,
            reservation_key=reservation_key,
        )

    async def release(
        self,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        units: int,
        limit: Optional[int] = None,
        request_key: str,
        actor_user_id: UUID,
        occurred_at: Optional[datetime] = None,
        period: Optional[str] = None,
        reservation_key: str,
    ) -> LedgerResult:
        """Return a reservation's capacity to the period (status 'released')."""
        return await self._transition(
            "release",
            scope=scope,
            kind=kind,
            units=units,
            limit=limit,
            request_key=request_key,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            period=period,
            reservation_key=reservation_key,
        )

    async def _transition(
        self,
        operation: str,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        units: int,
        limit: Optional[int],
        request_key: str,
        actor_user_id: UUID,
        occurred_at: Optional[datetime],
        period: Optional[str],
        reservation_key: str,
    ) -> LedgerResult:
        _validate_common(units, request_key, actor_user_id, occurred_at, period)
        kind_text = _normalise_kind(kind)
        scope_key = _scope_key(scope)
        if not _is_valid_key(reservation_key):
            raise ValueError("reservation_key must be 1-128 characters")

        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _advisory_lock(
                    conn, scope_key, kind_text, operation, request_key
                )
                # 1) Same-key replay is a duplicate/conflict before any state
                #    inspection (mirrors Ledger._existing ordering).
                by_key = await self._registry_by_key(
                    conn, scope_key, kind_text, operation, request_key
                )
                if by_key is not None:
                    original = await _select_event_by_fingerprint(
                        conn, scope_key, kind_text, operation, by_key["fingerprint"]
                    )
                    if original is None:  # pragma: no cover
                        raise UsageError("idempotency registry points at no event")
                    original_period = original["period_key"]
                    quota = await self._read_quota(
                        conn, scope_key, kind_text, original_period
                    )
                    original_limit = 0 if quota is None else quota["limit_units"]
                    candidate = _fingerprint(
                        scope, kind_text, units, actor_user_id, operation,
                        original_limit, reservation_key, original_period,
                    )
                    if candidate != by_key["fingerprint"]:
                        raise IdempotencyConflict(
                            "request_key was reused with different parameters"
                        )
                    return await self._replay_result(
                        conn, scope=scope, kind=kind_text,
                        operation=operation, fingerprint=by_key["fingerprint"],
                    )

                # 2) The reservation must exist and carry the same units.
                reserve_event = await conn.fetchrow(
                    "select id, period_key, units from public.usage_events"
                    " where scope_key = $1 and usage_kind = $2"
                    "   and operation = 'reserve' and reservation_key = $3"
                    " order by created_at asc, id asc limit 1"
                    " for update",
                    scope_key,
                    kind_text,
                    reservation_key,
                )
                if reserve_event is None:
                    raise ReservationNotFound("reservation not found")
                if reserve_event["units"] != units:
                    raise IdempotencyConflict("reservation units do not match")

                original_period_key = reserve_event["period_key"]
                period_start, period_end = _bucket_bounds(original_period_key)
                quota = await self._lock_quota_or_provision(
                    conn, scope_key=scope_key, kind=kind_text,
                    period_key=original_period_key, limit=limit,
                )
                row_limit = int(quota["limit_units"])
                if limit is not None and int(limit) != row_limit:
                    raise IdempotencyConflict("quota limit changed for an existing period")
                fingerprint = _fingerprint(
                    scope, kind_text, units, actor_user_id, operation,
                    row_limit, reservation_key, original_period_key,
                )

                # 3) An already terminal reservation is a state error for any
                #    *new* transition key (the same-key case returned above).
                terminal = await conn.fetchrow(
                    "select 1 from public.usage_events"
                    " where scope_key = $1 and usage_kind = $2"
                    "   and reservation_key = $3"
                    "   and operation in ('commit', 'release')"
                    " limit 1",
                    scope_key,
                    kind_text,
                    reservation_key,
                )
                if terminal is not None:
                    raise ReservationStateError("reservation is no longer active")

                if operation == "commit":
                    updated = await conn.fetchrow(
                        "update public.usage_quotas"
                        " set reserved_units = reserved_units - $1,"
                        "     consumed_units = consumed_units + $1"
                        " where scope_key = $2 and usage_kind = $3 and period_key = $4"
                        "   and reserved_units >= $1"
                        " returning id, limit_units, consumed_units, reserved_units",
                        units,
                        scope_key,
                        kind_text,
                        original_period_key,
                    )
                    status = "committed"
                else:
                    updated = await conn.fetchrow(
                        "update public.usage_quotas"
                        " set reserved_units = reserved_units - $1"
                        " where scope_key = $2 and usage_kind = $3 and period_key = $4"
                        "   and reserved_units >= $1"
                        " returning id, limit_units, consumed_units, reserved_units",
                        units,
                        scope_key,
                        kind_text,
                        original_period_key,
                    )
                    status = "released"
                if updated is None:
                    raise ReservationStateError("reservation is no longer active")

                event_id = await self._insert_event_and_registry(
                    conn,
                    scope_key=scope_key,
                    kind=kind_text,
                    operation=operation,
                    units=units,
                    period_key=original_period_key,
                    request_key=request_key,
                    actor_user_id=actor_user_id,
                    fingerprint=fingerprint,
                    reservation_key=reservation_key,
                )
                return _make_result(
                    scope=scope,
                    kind=kind_text,
                    event_id=event_id,
                    period_id=updated["id"],
                    status=status,
                    units=units,
                    consumed=updated["consumed_units"],
                    reserved=updated["reserved_units"],
                    limit=updated["limit_units"],
                    period_start=period_start,
                    period_end=period_end,
                    request_key=request_key,
                )

    # -- summary -------------------------------------------------------------

    async def summary(
        self,
        *,
        scope: Scope,
        kind: Union[UsageKind, str],
        occurred_at: datetime,
        period: str,
    ) -> LedgerSummary:
        """Return current counters for one UTC+8 bucket (absent period = zeros)."""
        kind_text = _normalise_kind(kind)
        scope_key = _scope_key(scope)
        period_key, start, end = _period_bucket(occurred_at, period)
        pool = self._acquire()
        async with pool.acquire() as conn:
            quota = await self._read_quota(conn, scope_key, kind_text, period_key)
        if quota is None:
            return LedgerSummary(scope, kind, 0, 0, 0, start, end)
        return LedgerSummary(
            scope,
            kind,
            quota["consumed_units"],
            quota["reserved_units"],
            quota["limit_units"],
            start,
            end,
        )
