"""Authenticated, read-only organization membership snapshots."""

from __future__ import annotations

import logging
import csv
import io
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse, Response

from ..auth import AuthUser, require_user
from ..db import get_pool
from ..billing.entitlements import period_key
from ..usage.ledger import QuotaExceeded
from ..usage.quota import consume_current_entitlement
from .. import service_tasks


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
INVITATION_TTL = timedelta(days=7)
INVITATION_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INVITATION_ROLES = frozenset({"owner", "admin", "member"})


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


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _invitation_email(value: str) -> str:
    email = (value or "").strip().lower()
    if not INVITATION_EMAIL_RE.fullmatch(email) or len(email) > 320:
        raise HTTPException(status_code=400, detail="受邀邮箱格式无效")
    return email


def _invitation_role(value: str) -> str:
    role = (value or "").strip().lower()
    if role not in INVITATION_ROLES:
        raise HTTPException(status_code=400, detail="邀请角色无效")
    return role


class OrganizationInvitationRequest(BaseModel):
    email: str
    role: str = "member"


class OrganizationAcceptInvitationRequest(BaseModel):
    token: str


def _invitation_status(row: Any, now: Optional[datetime] = None) -> str:
    now = now or _utcnow()
    if _value(row, "accepted_at") is not None:
        return "accepted"
    if _value(row, "revoked_at") is not None:
        return "revoked"
    expires_at = _value(row, "expires_at")
    if expires_at is not None and expires_at <= now:
        return "expired"
    return "pending"


def _serialize_invitation(row: Any) -> dict[str, Any]:
    return {
        "id": str(_value(row, "id")),
        "email": str(_value(row, "email", "")),
        "role": str(_value(row, "role", "member")),
        "status": _invitation_status(row),
        "expires_at": _iso(_value(row, "expires_at")),
        "accepted_at": _iso(_value(row, "accepted_at")),
        "revoked_at": _iso(_value(row, "revoked_at")),
        "created_at": _iso(_value(row, "created_at")),
    }


def _invitation_organization(row: Any) -> dict[str, str]:
    name = str(_value(row, "organization_name", "") or "").strip()
    return {"name": name or "未命名机构"}


class OrganizationInvitationStore:
    async def create(self, user: AuthUser, email: str, role: str) -> dict[str, Any]:
        raise NotImplementedError

    async def list(self, user: AuthUser) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def revoke(self, user: AuthUser, invitation_id: UUID) -> dict[str, Any]:
        raise NotImplementedError

    async def accept(self, user: AuthUser, token: str) -> dict[str, Any]:
        raise NotImplementedError


class DbOrganizationInvitationStore(OrganizationInvitationStore):
    async def _membership(self, conn: Any, user_id: UUID) -> Any:
        return await conn.fetchrow(
            """select om.organization_id, om.role, o.name
               from public.organization_members om
               join public.organizations o on o.id=om.organization_id
               where om.user_id=$1 and om.status='active'
               order by om.created_at, om.id limit 1""", user_id)

    async def _manager_membership(self, conn: Any, user_id: UUID) -> Any:
        membership = await self._membership(conn, user_id)
        if not membership:
            raise HTTPException(status_code=404, detail="机构不存在")
        if str(_value(membership, "role")) not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="只有机构管理员可以管理邀请")
        return membership

    async def _seat_limit(self, conn: Any, organization_id: UUID) -> int:
        row = await conn.fetchrow(
            """select coalesce(nullif(pp.subscription_slots, 0), 5) as seat_limit
               from public.organizations o
               left join public.subscriptions s on s.organization_id=o.id
                 and s.product_code='b_data_pro_monthly'
                 and s.status in ('active','trialing')
                 and (s.current_period_end is null or s.current_period_end > now())
               left join public.pricing_plans pp on pp.plan_code=case when s.id is null then 'free_b' else 'b_data_pro' end
                 and pp.audience='b' and pp.active=true
               where o.id=$1 limit 1""", organization_id)
        return max(1, int(_value(row, "seat_limit", 5) or 5))

    async def create(self, user: AuthUser, email: str, role: str) -> dict[str, Any]:
        email, role = _invitation_email(email), _invitation_role(role)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                membership = await self._manager_membership(conn, user.user_id)
                org_id = _value(membership, "organization_id")
                duplicate = await conn.fetchval(
                    """select 1 from public.organization_invitations
                       where organization_id=$1 and email=$2 and accepted_at is null
                         and revoked_at is null and expires_at > now() limit 1""", org_id, email)
                if duplicate:
                    raise HTTPException(status_code=409, detail="该邮箱已有待处理邀请")
                active, pending, limit = await conn.fetchrow(
                    """select
                       (select count(*) from public.organization_members where organization_id=$1 and status='active') as active,
                       (select count(*) from public.organization_invitations where organization_id=$1 and accepted_at is null and revoked_at is null and expires_at > now()) as pending,
                       (select coalesce(nullif(pp.subscription_slots,0),5) from public.organizations o
                          left join public.subscriptions s on s.organization_id=o.id and s.product_code='b_data_pro_monthly' and s.status in ('active','trialing') and (s.current_period_end is null or s.current_period_end > now())
                          left join public.pricing_plans pp on pp.plan_code=case when s.id is null then 'free_b' else 'b_data_pro' end and pp.audience='b' and pp.active=true where o.id=$1 limit 1)""", org_id)
                if int(active or 0) + int(pending or 0) >= int(limit or 5):
                    raise HTTPException(status_code=409, detail="机构可用席位已满")
                token = secrets.token_urlsafe(32)
                expires = _utcnow() + INVITATION_TTL
                await conn.execute(
                    """insert into public.organization_invitations
                       (organization_id,email,role,token_hash,created_by_user_id,expires_at)
                       values($1,$2,$3,$4,$5,$6)""", org_id, email, role, invitation_token_hash(token), user.user_id, expires)
        return {"invite_token": token, "expires_at": _iso(expires)}

    async def list(self, user: AuthUser) -> list[dict[str, Any]]:
        async with get_pool().acquire() as conn:
            membership = await self._manager_membership(conn, user.user_id)
            rows = await conn.fetch(
                """select id,email,role,expires_at,accepted_at,revoked_at,created_at
                   from public.organization_invitations where organization_id=$1
                   order by created_at desc,id desc""", _value(membership, "organization_id"))
            return [_serialize_invitation(row) for row in rows]

    async def revoke(self, user: AuthUser, invitation_id: UUID) -> dict[str, Any]:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                membership = await self._manager_membership(conn, user.user_id)
                row = await conn.fetchrow(
                    """select * from public.organization_invitations
                       where id=$1 and organization_id=$2 for update""", invitation_id, _value(membership, "organization_id"))
                if not row:
                    raise HTTPException(status_code=404, detail="邀请不存在")
                current = _invitation_status(row)
                if current != "pending":
                    raise HTTPException(status_code=409, detail=f"邀请当前状态为{current}，不能撤销")
                row = await conn.fetchrow("update public.organization_invitations set revoked_at=now() where id=$1 returning id,email,role,expires_at,accepted_at,revoked_at,created_at", invitation_id)
                return _serialize_invitation(row)

    async def accept(self, user: AuthUser, token: str) -> dict[str, Any]:
        token = (token or "").strip()
        if not token or len(token) > 512:
            raise HTTPException(status_code=400, detail="邀请链接无效或已失效")
        computed = invitation_token_hash(token)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """select oi.*, o.name as organization_name
                       from public.organization_invitations oi
                       join public.organizations o on o.id=oi.organization_id
                       where oi.token_hash=$1 for update""", computed)
                if not row or not hmac.compare_digest(str(_value(row, "token_hash", "")), computed):
                    raise HTTPException(status_code=404, detail="邀请链接无效或已失效")
                if user.email.strip().lower() != str(_value(row, "email", "")).lower():
                    raise HTTPException(status_code=403, detail="请使用受邀邮箱登录后接受邀请")
                status = _invitation_status(row)
                if status == "accepted":
                    return {"accepted": True, "already_accepted": True, "organization": _invitation_organization(row), "role": str(_value(row, "role"))}
                if status == "revoked":
                    raise HTTPException(status_code=410, detail="邀请已撤销")
                if status == "expired":
                    raise HTTPException(status_code=410, detail="邀请已过期")
                existing = await conn.fetchval("select 1 from public.organization_members where organization_id=$1 and user_id=$2", _value(row, "organization_id"), user.user_id)
                if existing:
                    await conn.execute("update public.organization_invitations set accepted_at=now(),accepted_by_user_id=$2 where id=$1", _value(row, "id"), user.user_id)
                    return {"accepted": True, "already_member": True, "organization": _invitation_organization(row), "role": str(_value(row, "role"))}
                active = await conn.fetchval("select count(*) from public.organization_members where organization_id=$1 and status='active'", _value(row, "organization_id"))
                pending = await conn.fetchval("select count(*) from public.organization_invitations where organization_id=$1 and accepted_at is null and revoked_at is null and expires_at > now()", _value(row, "organization_id"))
                limit = await self._seat_limit(conn, _value(row, "organization_id"))
                if int(active or 0) >= limit:
                    raise HTTPException(status_code=409, detail="机构可用席位已满")
                await conn.execute("insert into public.organization_members(organization_id,user_id,role,status) values($1,$2,$3,'active')", _value(row, "organization_id"), user.user_id, _value(row, "role"))
                await conn.execute("update public.organization_invitations set accepted_at=now(),accepted_by_user_id=$2 where id=$1", _value(row, "id"), user.user_id)
                return {"accepted": True, "organization": _invitation_organization(row), "role": str(_value(row, "role"))}


def get_org_invitation_store() -> OrganizationInvitationStore:
    return DbOrganizationInvitationStore()


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
        seat_limit = await conn.fetchval(
            """select coalesce(nullif(subscription_slots, 0), 5)
               from public.pricing_plans where plan_code=$1 and audience='b' and active=true
               limit 1""", plan_code)
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
            "seats": {"used": int(used or 0), "limit": int(seat_limit or 5)},
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


@router.get("/service-tasks")
async def list_org_service_tasks(user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return await service_tasks.list_for_org(user.user_id)


@router.post("/service-tasks/{task_id}/apply")
async def apply_org_service_task(task_id: UUID, body: service_tasks.ServiceTaskApply, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return await service_tasks.apply(user.user_id, task_id, body)


@router.post("/service-tasks/{task_id}/withdraw")
async def withdraw_org_service_task(task_id: UUID, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return await service_tasks.withdraw(user.user_id, task_id)


@router.post("/service-tasks/{task_id}/consent")
async def grant_org_service_task_consent(task_id: UUID, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return await service_tasks.grant_org_consent(user.user_id, task_id)


@router.post("/service-tasks/{task_id}/complete")
async def complete_org_service_task(task_id: UUID, user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    return await service_tasks.complete(user.user_id, task_id)


@router.get("/members")
async def get_org_members(user: AuthUser = Depends(require_user), store: OrganizationReadStore = Depends(get_org_store)) -> Any:
    try:
        return {"members": await store.list_members(user)}
    except Exception:
        logger.warning("organization members unavailable", exc_info=False)
        return _error("org_unavailable", "机构成员暂时无法读取。")


@router.post("/invitations", status_code=201)
async def create_org_invitation(
    body: OrganizationInvitationRequest,
    user: AuthUser = Depends(require_user),
    store: OrganizationInvitationStore = Depends(get_org_invitation_store),
) -> Any:
    return await store.create(user, body.email, body.role)


@router.get("/invitations")
async def list_org_invitations(
    user: AuthUser = Depends(require_user),
    store: OrganizationInvitationStore = Depends(get_org_invitation_store),
) -> dict[str, Any]:
    return {"invitations": await store.list(user)}


@router.post("/invitations/{invitation_id}/revoke")
async def revoke_org_invitation(
    invitation_id: UUID,
    user: AuthUser = Depends(require_user),
    store: OrganizationInvitationStore = Depends(get_org_invitation_store),
) -> Any:
    return await store.revoke(user, invitation_id)


@router.post("/invitations/accept")
async def accept_org_invitation(
    body: OrganizationAcceptInvitationRequest,
    user: AuthUser = Depends(require_user),
    store: OrganizationInvitationStore = Depends(get_org_invitation_store),
) -> Any:
    return await store.accept(user, body.token)
