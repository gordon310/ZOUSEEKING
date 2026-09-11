"""Authenticated, read-only member and entitlement snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg
import logging
from fastapi import APIRouter, Depends

from ..auth import AuthUser, require_user
from ..db import get_pool
from ..usage.ledger import period_bounds
from ..billing.entitlements import normalize_entitlements, period_key, plan_for_tier


router = APIRouter(tags=["member"])
logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _period(now: datetime) -> tuple[str, datetime, datetime]:
    start, end = period_bounds(now, "month")
    return start.strftime("%Y-%m"), start, end


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _empty_entitlements() -> Dict[str, Dict[str, Any]]:
    return {
        "queries": {"used": 0, "limit": None},
        "reports": {"used": 0, "limit": None},
        "exports_rows": {"used": 0, "limit": None},
    }


class MemberReadStore:
    """Read the current user's profile, monthly ledger and subscription."""

    async def _snapshot(self, user: AuthUser, *, now: datetime) -> Dict[str, Any]:
        month_key, period_start, period_end = _period(now)
        day_key = period_key(now, "day")
        entitlements = _empty_entitlements()
        available = True
        tier = None
        audience = "c"
        subscription = None
        pool = get_pool()
        async with pool.acquire() as conn:
            try:
                profile = await conn.fetchrow(
                    "select membership_tier, audience from public.user_profiles where user_id=$1",
                    user.user_id,
                )
                # A missing/blank profile is the free tier.  This must still
                # resolve and read free_c from the database; it must not skip
                # the entitlement lookup and silently use code defaults.
                tier = (profile["membership_tier"] if profile else None) or "free"
                try:
                    audience = (profile["audience"] if profile else None) or "c"
                except (KeyError, IndexError):
                    # Older test doubles / pre-migration rows have no field.
                    audience = "c"
            except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
                available = False

            plan = None
            entitlement_rows = []
            try:
                plan = await conn.fetchrow(
                    "select plan_code, audience, monthly_query_limit, monthly_report_quota, subscription_slots, export_rows_monthly "
                    "from public.pricing_plans where plan_code=$1 and active=true",
                    plan_for_tier(tier, audience),
                )
                if plan:
                    try:
                        entitlement_rows = await conn.fetch(
                            "select metric, period, limit_units, active from public.plan_entitlements where plan_code=$1",
                            plan["plan_code"],
                        )
                    except Exception as exc:
                        logger.warning("member entitlement DB read unavailable; using fallback: %s", type(exc).__name__)
            except Exception as exc:
                logger.warning("member plan DB read unavailable; using fallback: %s", type(exc).__name__)
                available = False

            try:
                rows = await conn.fetch(
                    "select usage_kind, consumed_units, limit_units from public.usage_quotas "
                    "where scope_key=$1 and period_key = any($2::text[])",
                    f"user:{user.user_id}", [day_key, month_key],
                )
                usage = {(str(row["usage_kind"]), str(row["period_key"])): row for row in rows}
            except asyncpg.UndefinedTableError:
                available = False
                usage = {}

            code = str(plan["plan_code"]) if plan else plan_for_tier(tier, audience)
            legacy = dict(plan) if plan else {}
            # Resolution order is plan_entitlements (DB) > pricing_plans
            # monthly_* legacy columns (DB) > code defaults.
            limits = normalize_entitlements(code, rows=entitlement_rows, legacy=legacy)
            names = {"query": "queries", "report": "reports", "stats_query": "stats_queries", "export_row": "exports_rows", "subscription_slot": "subscription_slots"}
            by_metric: Dict[str, Dict[str, int]] = {}
            for (kind, period), limit in limits.items():
                by_metric.setdefault(kind, {})[period] = int(limit)
            for kind, periods in by_metric.items():
                name = names[kind]
                primary_period = "day" if "day" in periods else "month"
                period_value = day_key if primary_period == "day" else month_key
                matching_row = usage.get((kind, period_value))
                entitlements[name] = {
                    "used": int(matching_row["consumed_units"]) if matching_row else 0,
                    "limit": periods[primary_period],
                    "period": primary_period,
                    "periods": periods,
                }

            try:
                row = await conn.fetchrow(
                    "select product_code, status, current_period_end, cancel_at_period_end "
                    "from public.subscriptions where user_id=$1 "
                    "and status in ('trialing','active','past_due','canceled','unpaid','incomplete') "
                    "order by created_at desc, id desc limit 1",
                    user.user_id,
                )
                if row:
                    status = str(row["status"])
                    subscription = {
                        "plan": row["product_code"],
                        "status": "active" if status == "trialing" else "past_due" if status == "unpaid" else status,
                        "current_period_end": _iso(row["current_period_end"]),
                        "cancel_at_period_end": bool(row["cancel_at_period_end"]),
                    }
            except asyncpg.UndefinedTableError:
                available = False

        return {
            "available": available,
            "user_id": str(user.user_id),
            "email": user.email,
            "membership_tier": tier,
            "audience": audience,
            "entitlements": entitlements,
            "subscription": subscription,
                "period": {
                "key": month_key,
                "start": _iso(period_start),
                "end": _iso(period_end),
            },
        }

    async def get_me(self, user: AuthUser, *, now: datetime) -> Dict[str, Any]:
        return await self._snapshot(user, now=now)

    async def get_usage_summary(self, user: AuthUser, *, now: datetime) -> Dict[str, Any]:
        snapshot = await self._snapshot(user, now=now)
        return {
            "available": snapshot["available"],
            "period": snapshot["period"],
            "entitlements": snapshot["entitlements"],
        }


def get_member_read_store() -> MemberReadStore:
    return MemberReadStore()


@router.get("/api/me")
async def get_me(
    user: AuthUser = Depends(require_user),
    store: MemberReadStore = Depends(get_member_read_store),
) -> Dict[str, Any]:
    return await store.get_me(user, now=utcnow())
