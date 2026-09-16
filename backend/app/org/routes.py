"""Authenticated, read-only organization membership snapshots."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import AuthUser, require_user
from ..db import get_pool
from ..billing.entitlements import period_key


router = APIRouter(prefix="/api/org", tags=["organization"])
logger = logging.getLogger(__name__)
PUBLIC_ENTITLEMENTS = {
    "query": "queries",
    "stats_query": "analysis",
    "subscription_slot": "subscriptions",
    "export_row": "exports_rows",
    "report": "reports",
}
PLAN_NAMES = {"free_b": "B Free", "b_data_pro": "B Data Pro"}


def _value(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class OrganizationReadStore:
    """Resolve organization scope exclusively from the authenticated user."""

    async def _membership(self, conn: Any, user_id: Any) -> Any:
        return await conn.fetchrow(
            """
            select om.organization_id, om.role, o.name
            from public.organization_members om
            join public.organizations o on o.id = om.organization_id
            where om.user_id=$1 and om.status='active'
            order by om.created_at asc, om.id asc
            limit 1
            """,
            user_id,
        )

    async def _snapshot(self, conn: Any, membership: Any) -> dict[str, Any]:
        organization_id = _value(membership, "organization_id")
        used = await conn.fetchval(
            "select count(*) from public.organization_members where organization_id=$1 and status='active'",
            organization_id,
        )
        subscription = await conn.fetchrow(
            """
            select product_code from public.subscriptions
            where organization_id=$1 and product_code='b_data_pro_monthly'
              and status in ('active','trialing')
              and (current_period_end is null or current_period_end > now())
            order by created_at desc, id desc limit 1
            """,
            organization_id,
        )
        plan_code = "b_data_pro" if subscription else "free_b"
        plan = await conn.fetchrow(
            "select plan_code, name from public.pricing_plans where plan_code=$1 and audience='b' and active=true",
            plan_code,
        )
        entitlements = await conn.fetch(
            """
            select metric, period, limit_units from public.plan_entitlements
            where plan_code=$1 and active=true
            order by metric, period
            """,
            plan_code,
        )
        month_key = period_key(datetime.now(timezone.utc), "month")
        usage = await conn.fetch(
            """
            select usage_kind, period_key, consumed_units
            from public.usage_quotas
            where scope_key=$1 and period_key=$2
            """,
            f"org:{organization_id}",
            month_key,
        )
        usage_by_metric = {
            (str(_value(row, "usage_kind")), str(_value(row, "period_key"))): int(_value(row, "consumed_units", 0))
            for row in usage
        }
        public_entitlements: dict[str, dict[str, Any]] = {}
        for row in entitlements:
            metric = PUBLIC_ENTITLEMENTS.get(str(_value(row, "metric")))
            if not metric:
                continue
            period = str(_value(row, "period"))
            if period != "month":
                continue
            public_entitlements[metric] = {
                "used": usage_by_metric.get((str(_value(row, "metric")), month_key), 0),
                "limit": int(_value(row, "limit_units", 0)),
                "period": "month",
            }
        return {
            "organization": {"name": str(_value(membership, "name", ""))},
            "role": str(_value(membership, "role", "member")),
            "seats": {"used": int(used or 0), "limit": 5},
            "plan": {
                "name": str(_value(plan, "name", PLAN_NAMES[plan_code])),
                "entitlements": public_entitlements,
            },
        }

    async def get_me(self, user: AuthUser) -> dict[str, Any]:
        async with get_pool().acquire() as conn:
            membership = await self._membership(conn, user.user_id)
            if not membership:
                return {"organization": None, "role": None, "seats": None, "plan": None}
            return await self._snapshot(conn, membership)

    async def list_members(self, user: AuthUser) -> list[dict[str, Any]]:
        async with get_pool().acquire() as conn:
            membership = await self._membership(conn, user.user_id)
            if not membership:
                return []
            rows = await conn.fetch(
                """
                select case
                         when btrim(u.email) ~ '^[^@[:space:]]+@[^@[:space:]]+$'
                           then left(btrim(u.email), 1) || '***@' || split_part(btrim(u.email), '@', 2)
                         else '成员 ' || row_number() over (order by om.created_at asc, om.id asc)::text
                       end as display_name,
                       om.role, om.status, om.created_at
                from public.organization_members om
                left join auth.users u on u.id=om.user_id
                where om.organization_id=$1
                order by om.created_at asc, om.id asc
                """,
                _value(membership, "organization_id"),
            )
            return [
                {
                    "display_name": str(_value(row, "display_name", "成员")),
                    "role": str(_value(row, "role", "member")),
                    "status": str(_value(row, "status", "inactive")),
                    "joined_at": _iso(_value(row, "created_at")),
                }
                for row in rows
            ]


def get_org_store() -> OrganizationReadStore:
    return OrganizationReadStore()


def _error(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={"error": {"code": code, "message": message}})


@router.get("/me")
async def get_org_me(user: AuthUser = Depends(require_user), store: OrganizationReadStore = Depends(get_org_store)) -> Any:
    try:
        return await store.get_me(user)
    except Exception:
        logger.warning("organization summary unavailable", exc_info=False)
        return _error("org_unavailable", "机构信息暂时无法读取。")


@router.get("/members")
async def get_org_members(user: AuthUser = Depends(require_user), store: OrganizationReadStore = Depends(get_org_store)) -> Any:
    try:
        return {"members": await store.list_members(user)}
    except Exception:
        logger.warning("organization members unavailable", exc_info=False)
        return _error("org_unavailable", "机构成员暂时无法读取。")
