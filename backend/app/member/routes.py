"""Authenticated, read-only member and entitlement snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncpg
from fastapi import APIRouter, Depends

from ..auth import AuthUser, require_user
from ..db import get_pool
from ..usage.ledger import period_bounds


router = APIRouter(tags=["member"])


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


def _empty_entitlements() -> Dict[str, Dict[str, Optional[int]]]:
    return {
        "queries": {"used": 0, "limit": None},
        "reports": {"used": 0, "limit": None},
        "exports_rows": {"used": 0, "limit": None},
    }


class MemberReadStore:
    """Read the current user's profile, monthly ledger and subscription."""

    async def _snapshot(self, user: AuthUser, *, now: datetime) -> Dict[str, Any]:
        period_key, period_start, period_end = _period(now)
        entitlements = _empty_entitlements()
        available = True
        tier = None
        subscription = None
        pool = get_pool()
        async with pool.acquire() as conn:
            try:
                profile = await conn.fetchrow(
                    "select membership_tier from public.user_profiles where user_id=$1",
                    user.user_id,
                )
                tier = profile["membership_tier"] if profile else None
            except asyncpg.UndefinedTableError:
                available = False

            plan = None
            if tier:
                try:
                    plan = await conn.fetchrow(
                        "select monthly_query_limit, monthly_report_quota, export_rows_monthly "
                        "from public.pricing_plans where plan_code=$1 and active=true",
                        tier,
                    )
                except asyncpg.UndefinedTableError:
                    available = False

            try:
                rows = await conn.fetch(
                    "select usage_kind, consumed_units, limit_units from public.usage_quotas "
                    "where scope_key=$1 and period_key=$2",
                    f"user:{user.user_id}", period_key,
                )
                usage = {str(row["usage_kind"]): row for row in rows}
            except asyncpg.UndefinedTableError:
                available = False
                usage = {}

            limits = {
                "query": plan["monthly_query_limit"] if plan else None,
                "report": plan["monthly_report_quota"] if plan else None,
                "export_row": plan["export_rows_monthly"] if plan else None,
            }
            names = {"query": "queries", "report": "reports", "export_row": "exports_rows"}
            for kind, name in names.items():
                row = usage.get(kind)
                entitlements[name] = {
                    "used": int(row["consumed_units"]) if row else 0,
                    "limit": int(limits[kind]) if limits[kind] is not None else None,
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
            "entitlements": entitlements,
            "subscription": subscription,
            "period": {
                "key": period_key,
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
