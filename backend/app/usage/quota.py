"""One transactional, server-owned quota consumption primitive."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional
from uuid import UUID, uuid4

import asyncpg

from ..auth import AuthUser
from ..billing.entitlements import plan_for_tier
from .ledger import QuotaExceeded

UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")

# ``free_preview`` is a product action, not a frozen database usage_kind.  It
# uses the existing query entitlement/bucket while retaining its own stable
# fingerprint, so no frozen CHECK constraint or column needs to change.
METER_MAP = {
    "free_preview": ("query", "day"),
    "query": ("query", "month"),
    "report": ("report", "month"),
    "stats": ("stats_query", "month"),
    "stats_query": ("stats_query", "month"),
    "export": ("export_row", "month"),
    "export_row": ("export_row", "month"),
}


@dataclass(frozen=True)
class QuotaConsumption:
    status: str
    metric: str
    period_key: str
    used: int
    limit: int
    remaining: int


def current_period_key(value: datetime, period: str) -> str:
    if period not in {"day", "month"}:
        raise ValueError("period must be 'day' or 'month'")
    local = value.astimezone(UTC_PLUS_8)
    return local.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")


def select_live_entitlement(
    rows: Iterable[Mapping[str, Any]], metric: str, period: str
) -> Optional[int]:
    candidates = [
        row for row in rows
        if row.get("metric") == metric and row.get("period") == period and row.get("active", True)
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            row.get("effective_from") is not None,
            row.get("effective_from") or datetime.min.replace(tzinfo=timezone.utc),
            row.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return max(0, int(candidates[0]["limit_units"]))


def _scope_key(user_id: UUID, organization_id: Optional[UUID] = None) -> str:
    return f"org:{organization_id}" if organization_id else f"user:{user_id}"


async def _resolve_plan(conn: asyncpg.Connection, user_id: UUID) -> tuple[str, str]:
    profile = await conn.fetchrow(
        "select membership_tier, audience from public.user_profiles where user_id=$1",
        user_id,
    )
    tier = (profile["membership_tier"] if profile else None) or "free"
    audience = (profile["audience"] if profile else None) or "c"
    organization = await conn.fetchrow(
        """
        select om.organization_id
        from public.organization_members om
        join public.subscriptions s on s.organization_id=om.organization_id
        where om.user_id=$1 and om.status='active'
          and s.status in ('active', 'trialing')
          and (s.current_period_end is null or s.current_period_end > now())
        order by om.created_at asc limit 1
        """,
        user_id,
    )
    if organization:
        return _scope_key(user_id, organization["organization_id"]), "b_data_pro"
    return _scope_key(user_id), plan_for_tier(tier, audience)


async def consume_current_entitlement(
    conn: asyncpg.Connection,
    *,
    user: AuthUser,
    metric: str,
    period: Optional[str] = None,
    units: int,
    idempotency_key: str,
    fingerprint: str,
    scope_key: Optional[str] = None,
) -> QuotaConsumption:
    """Consume live entitlement; caller must have opened the transaction."""
    if metric not in METER_MAP:
        raise ValueError("unsupported quota metric")
    if not isinstance(units, int) or isinstance(units, bool) or units <= 0:
        raise ValueError("units must be a positive integer")
    usage_kind, default_period = METER_MAP[metric]
    period = period or default_period
    if period != default_period:
        raise ValueError("period does not match quota metric")
    if not idempotency_key or not fingerprint:
        raise ValueError("idempotency_key and fingerprint are required")

    resolved_scope, plan_code = await _resolve_plan(conn, user.user_id)
    scope_key = scope_key or resolved_scope
    period_key = current_period_key(datetime.now(timezone.utc), period)

    # Serialise identical replays before either one reads or mutates the row.
    await conn.execute(
        "select pg_advisory_xact_lock(hashtext($1))",
        f"quota:{scope_key}:{usage_kind}:{idempotency_key}:{fingerprint}",
    )
    prior = await conn.fetchrow(
        """
        select fingerprint from public.usage_idempotency
        where scope_key=$1 and usage_kind=$2 and operation='consume' and idempotency_key=$3
        """,
        scope_key, usage_kind, idempotency_key,
    )
    if prior:
        if prior["fingerprint"] != fingerprint:
            raise ValueError("idempotency key was reused with different parameters")
        quota = await conn.fetchrow(
            """select consumed_units, limit_units from public.usage_quotas
               where scope_key=$1 and usage_kind=$2 and period_key=$3""",
            scope_key, usage_kind, period_key,
        )
        used = int(quota["consumed_units"]) if quota else 0
        limit = int(quota["limit_units"]) if quota else 0
        return QuotaConsumption("duplicate", metric, period_key, used, limit, max(0, limit - used))

    entitlement = await conn.fetchrow(
        """
        select limit_units from public.plan_entitlements
        where plan_code=$1 and metric=$2 and period=$3 and active=true
        order by effective_from desc nulls last, created_at desc limit 1
        """,
        plan_code, usage_kind, period,
    )
    if entitlement is None:
        raise QuotaExceeded("usage quota is not configured")
    live_limit = max(0, int(entitlement["limit_units"]))

    await conn.execute(
        """insert into public.usage_quotas(scope_key, usage_kind, period_key, limit_units)
           values($1,$2,$3,$4) on conflict(scope_key, usage_kind, period_key) do nothing""",
        scope_key, usage_kind, period_key, live_limit,
    )
    quota = await conn.fetchrow(
        """select id, consumed_units, reserved_units, limit_units
           from public.usage_quotas
           where scope_key=$1 and usage_kind=$2 and period_key=$3 for update""",
        scope_key, usage_kind, period_key,
    )
    if quota is None:
        raise QuotaExceeded("usage quota is not configured")
    quota = await conn.fetchrow(
        """update public.usage_quotas set limit_units=$4
           where scope_key=$1 and usage_kind=$2 and period_key=$3
           returning id, consumed_units, reserved_units, limit_units""",
        scope_key, usage_kind, period_key, live_limit,
    )
    if int(quota["consumed_units"]) + int(quota["reserved_units"]) + units > live_limit:
        raise QuotaExceeded("usage quota exceeded")

    event_id = uuid4()
    await conn.execute(
        """insert into public.usage_events
           (id,scope_key,usage_kind,operation,units,period_key,idempotency_key,fingerprint,actor_user_id)
           values($1,$2,$3,'consume',$4,$5,$6,$7,$8)""",
        event_id, scope_key, usage_kind, units, period_key, idempotency_key, fingerprint, user.user_id,
    )
    await conn.execute(
        """insert into public.usage_idempotency
           (scope_key,usage_kind,operation,idempotency_key,fingerprint)
           values($1,$2,'consume',$3,$4)""",
        scope_key, usage_kind, idempotency_key, fingerprint,
    )
    updated = await conn.fetchrow(
        """update public.usage_quotas set consumed_units=consumed_units+$4
           where scope_key=$1 and usage_kind=$2 and period_key=$3
           returning consumed_units, limit_units""",
        scope_key, usage_kind, period_key, units,
    )
    used = int(updated["consumed_units"])
    limit = int(updated["limit_units"])
    return QuotaConsumption("consumed", metric, period_key, used, limit, max(0, limit - used))

