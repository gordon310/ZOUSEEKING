"""Authenticated, read-only organization membership snapshots."""

from __future__ import annotations

import logging
import csv
import io
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response

from ..auth import AuthUser, require_user
from ..db import get_pool
from ..billing.entitlements import period_key
from ..usage.ledger import QuotaExceeded
from ..usage.quota import consume_current_entitlement


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
ORG_EXPORT_CSV_COLUMNS = ("账期", "用量类型", "已用", "上限", "订单金额(最小单位)", "币种", "订单状态")
ORG_EXPORT_WINDOW_SECONDS = 60


def org_export_idempotency_key(organization_id: UUID, owner_user_id: UUID, month_key: str, now: datetime) -> str:
    window = int(now.timestamp()) // ORG_EXPORT_WINDOW_SECONDS
    return f"org-export:{organization_id}:{owner_user_id}:{month_key}:{window}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

    async def _authorized_membership(self, conn: Any, user: AuthUser, *, billing: bool = False) -> Any:
        membership = await self._membership(conn, user.user_id)
        if not membership:
            raise HTTPException(status_code=404, detail="organization not found")
        if billing and str(_value(membership, "role", "member")) not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="organization billing is restricted")
        return membership

    async def get_usage(self, user: AuthUser) -> dict[str, Any]:
        async with get_pool().acquire() as conn:
            membership = await self._membership(conn, user.user_id)
            if not membership:
                return {"organization": None, "role": None, "entitlements": {}}
            organization_id = _value(membership, "organization_id")
            month_key = period_key(datetime.now(timezone.utc), "month")
            subscription = await conn.fetchrow(
                """select 1 from public.subscriptions
                   where organization_id=$1 and product_code='b_data_pro_monthly'
                     and status in ('active','trialing')
                     and (current_period_end is null or current_period_end > now())
                   order by created_at desc, id desc limit 1""", organization_id)
            plan_code = "b_data_pro" if subscription else "free_b"
            entitlements = await conn.fetch(
                """select metric, period, limit_units from public.plan_entitlements
                   where plan_code=$1 and active=true and period='month'
                   order by metric""", plan_code)
            usage = await conn.fetch(
                """select usage_kind, consumed_units from public.usage_quotas
                   where scope_key=$1 and period_key=$2""", f"org:{organization_id}", month_key)
            used = {str(_value(row, "usage_kind")): int(_value(row, "consumed_units", 0)) for row in usage}
            public = {}
            for row in entitlements:
                key = PUBLIC_ENTITLEMENTS.get(str(_value(row, "metric")))
                if key:
                    public[key] = {"used": used.get(str(_value(row, "metric")), 0), "limit": int(_value(row, "limit_units", 0)), "period": "month"}
            return {"organization": {"name": str(_value(membership, "name", ""))}, "role": str(_value(membership, "role", "member")), "period": month_key, "entitlements": public}

    async def get_billing(self, user: AuthUser) -> dict[str, Any]:
        async with get_pool().acquire() as conn:
            membership = await self._authorized_membership(conn, user, billing=True)
            organization_id = _value(membership, "organization_id")
            orders = await conn.fetch(
                """select to_char(created_at at time zone 'Asia/Shanghai', 'YYYY-MM') as period,
                          product_code, amount_minor, currency, status, paid_at
                   from public.payment_orders where organization_id=$1
                   order by created_at desc, id desc""", organization_id)
            subscription = await conn.fetchrow(
                """select product_code, status, current_period_start, current_period_end,
                          amount_minor, currency
                   from public.subscriptions where organization_id=$1
                     and status in ('active','trialing')
                     and (current_period_end is null or current_period_end > now())
                   order by created_at desc, id desc limit 1""", organization_id)
            result_orders = [{"period": str(_value(row, "period")), "product_code": str(_value(row, "product_code")), "amount_minor": int(_value(row, "amount_minor", 0)), "currency": str(_value(row, "currency")), "status": str(_value(row, "status")), "paid_at": _iso(_value(row, "paid_at"))} for row in orders]
            currencies = {item["currency"] for item in result_orders}
            return {
                "organization": {"name": str(_value(membership, "name", ""))}, "role": str(_value(membership, "role", "member")),
                "orders": result_orders,
                "summary": {"order_count": len(result_orders), "amount_minor": sum(item["amount_minor"] for item in result_orders) if len(currencies) <= 1 else None, "currency": next(iter(currencies), None) if len(currencies) <= 1 else None},
                "subscription": None if not subscription else {"product_code": str(_value(subscription, "product_code")), "status": str(_value(subscription, "status")), "current_period_start": _iso(_value(subscription, "current_period_start")), "current_period_end": _iso(_value(subscription, "current_period_end")), "amount_minor": int(_value(subscription, "amount_minor", 0)), "currency": str(_value(subscription, "currency"))},
            }


class OrgUsageStore(Protocol):
    async def get_usage(self, user: AuthUser) -> dict[str, Any]: ...


class OrgBillingStore(Protocol):
    async def get_billing(self, user: AuthUser) -> dict[str, Any]: ...


class OrgExportStore(Protocol):
    async def create_export(self, user: AuthUser) -> dict[str, Any]: ...
    async def list_exports(self, user: AuthUser) -> list[dict[str, Any]]: ...
    async def download_export(self, user: AuthUser, export_id: UUID) -> bytes: ...


class DbOrgExportStore:
    async def _membership(self, conn: Any, user: AuthUser) -> Any:
        membership = await OrganizationReadStore()._membership(conn, user.user_id)
        if not membership:
            raise HTTPException(status_code=404, detail="organization not found")
        if str(_value(membership, "role", "member")) not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="organization export is restricted")
        return membership

    async def create_export(self, user: AuthUser) -> dict[str, Any]:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                membership = await self._membership(conn, user)
                org_id = _value(membership, "organization_id")
                now = _utcnow()
                month_key = period_key(now, "month")
                idempotency_key = org_export_idempotency_key(org_id, user.user_id, month_key, now)
                await conn.execute("select pg_advisory_xact_lock(hashtext($1))", f"{idempotency_key}:create")
                existing = await conn.fetchrow(
                    "select id, status, row_count, created_at from public.exports where organization_id=$1 and owner_user_id=$2 and idempotency_key=$3",
                    org_id, user.user_id, idempotency_key,
                )
                if existing:
                    return {
                        "id": str(existing["id"]),
                        "status": str(existing["status"]),
                        "row_count": int(existing["row_count"]),
                        "created_at": _iso(existing["created_at"]),
                        "download_url": f"/api/org/exports/{existing['id']}",
                        "reused": True,
                    }
                usage = await conn.fetch("select usage_kind, consumed_units, limit_units from public.usage_quotas where scope_key=$1 and period_key=$2 order by usage_kind", f"org:{org_id}", month_key)
                if not usage:
                    raise HTTPException(status_code=422, detail="no organization usage is available for export")
                order = await conn.fetchrow("select coalesce(sum(amount_minor), 0) as amount_minor, min(currency) as currency, min(status) as status from public.payment_orders where organization_id=$1 and to_char(created_at at time zone 'Asia/Shanghai', 'YYYY-MM')=$2", org_id, month_key)
                rows = [{"账期": month_key, "用量类型": PUBLIC_ENTITLEMENTS.get(str(_value(item, "usage_kind")), str(_value(item, "usage_kind"))), "已用": int(_value(item, "consumed_units", 0)), "上限": int(_value(item, "limit_units", 0)), "订单金额(最小单位)": int(_value(order, "amount_minor", 0)), "币种": str(_value(order, "currency", "")) if order and _value(order, "currency") else "", "订单状态": str(_value(order, "status", "")) if order and _value(order, "status") else ""} for item in usage if PUBLIC_ENTITLEMENTS.get(str(_value(item, "usage_kind")))]
                if not rows:
                    raise HTTPException(status_code=422, detail="no organization usage is available for export")
                output = io.StringIO(newline="")
                writer = csv.DictWriter(output, fieldnames=ORG_EXPORT_CSV_COLUMNS, lineterminator="\r\n", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
                content = ("\ufeff" + output.getvalue()).encode("utf-8")
                export_id = uuid4()
                await consume_current_entitlement(conn, user=user, metric="export_row", units=len(rows), idempotency_key=idempotency_key, fingerprint=idempotency_key, scope_key=f"org:{org_id}")
                await conn.execute("insert into public.exports(id, owner_user_id, organization_id, idempotency_key, status, row_count, csv_content) values($1,$2,$3,$4,'completed',$5,$6)", export_id, user.user_id, org_id, idempotency_key, len(rows), content)
                row = await conn.fetchrow("select id, status, row_count, created_at from public.exports where id=$1", export_id)
                return {"id": str(row["id"]), "status": str(row["status"]), "row_count": int(row["row_count"]), "created_at": _iso(row["created_at"]), "download_url": f"/api/org/exports/{export_id}", "reused": False}

    async def list_exports(self, user: AuthUser) -> list[dict[str, Any]]:
        async with get_pool().acquire() as conn:
            membership = await self._membership(conn, user)
            rows = await conn.fetch("select id, status, row_count, created_at from public.exports where organization_id=$1 and owner_user_id=$2 order by created_at desc limit 100", _value(membership, "organization_id"), user.user_id)
            return [{"id": str(row["id"]), "status": str(row["status"]), "row_count": int(row["row_count"]), "created_at": _iso(row["created_at"]), "download_url": f"/api/org/exports/{row['id']}"} for row in rows]

    async def download_export(self, user: AuthUser, export_id: UUID) -> bytes:
        async with get_pool().acquire() as conn:
            membership = await self._membership(conn, user)
            row = await conn.fetchrow("select csv_content from public.exports where id=$1 and organization_id=$2 and owner_user_id=$3", export_id, _value(membership, "organization_id"), user.user_id)
            if not row:
                raise HTTPException(status_code=404, detail="export not found")
            return bytes(row["csv_content"])


def get_org_usage_store() -> OrgUsageStore:
    return OrganizationReadStore()


def get_org_billing_store() -> OrgBillingStore:
    return OrganizationReadStore()


def get_org_export_store() -> OrgExportStore:
    return DbOrgExportStore()


@router.get("/usage")
async def get_org_usage(user: AuthUser = Depends(require_user), store: OrgUsageStore = Depends(get_org_usage_store)) -> Any:
    try:
        return await store.get_usage(user)
    except HTTPException:
        raise
    except Exception:
        logger.warning("organization usage unavailable", exc_info=False)
        return _error("org_unavailable", "机构用量暂时无法读取。")


@router.get("/billing")
async def get_org_billing(user: AuthUser = Depends(require_user), store: OrgBillingStore = Depends(get_org_billing_store)) -> Any:
    try:
        return await store.get_billing(user)
    except HTTPException:
        raise
    except Exception:
        logger.warning("organization billing unavailable", exc_info=False)
        return _error("org_unavailable", "机构账单暂时无法读取。")


@router.post("/exports", status_code=201)
async def create_org_export(user: AuthUser = Depends(require_user), store: OrgExportStore = Depends(get_org_export_store)) -> Any:
    try:
        return await store.create_export(user)
    except HTTPException:
        raise
    except QuotaExceeded:
        return JSONResponse(status_code=429, content={"error": {"code": "quota_exceeded", "message": "机构导出额度已用尽。"}})


@router.get("/exports")
async def list_org_exports(user: AuthUser = Depends(require_user), store: OrgExportStore = Depends(get_org_export_store)) -> Any:
    return {"exports": await store.list_exports(user)}


@router.get("/exports/{export_id}")
async def download_org_export(export_id: UUID, user: AuthUser = Depends(require_user), store: OrgExportStore = Depends(get_org_export_store)) -> Response:
    return Response(content=await store.download_export(user, export_id), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="org-export-{export_id}.csv"'})


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
