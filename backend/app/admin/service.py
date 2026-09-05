"""Data access for the back-office admin API.

The member / audit / finance / role-list surface is SELECT-only, and the two
role-assignment writes (grant / revoke) are the only mutating methods.  Every
write runs inside one transaction together with its ``audit_events`` insert,
so an assignment is never created or revoked without an audit row (the
append-only triggers forbid UPDATE/DELETE but allow INSERT).  Queries target
the tables created by the applied migrations:

* ``public.user_profiles`` (``20260824000100_legacy_schema_baseline``) - the
  member directory;
* ``public.internal_role_assignments`` and ``public.audit_events``
  (``20260905000500_v1_finance_admin_audit``) - back-office roles and the
  append-only audit log;
* ``public.subscriptions`` (``20260905000200_v1_products_subscriptions``) -
  active entitlement summary per member;
* ``public.usage_quotas`` / ``public.usage_events``
  (``20260905000300_v1_usage_ledger``) - current UTC+8 month counters and the
  member's most recent metered events;
* ``public.payment_orders`` / ``public.refunds``
  (``20260905000500_v1_finance_admin_audit``) - finance read views;
* ``public.collection_runs`` (``20260905000601_collection_runs``) - the
  collection run ledger (queued here by the admin API; advanced later by the
  collection worker).

Privacy posture: admin endpoints never appear in application logs and this
module performs no logging.  Email addresses are only ever returned by the
member views, which are gated to roles with email visibility (see
``EMAIL_VISIBLE_ROLES``); serialisers mask the email for every other viewer so
a future role expansion cannot start leaking addresses by accident.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from ..db import get_pool
from ..usage.ledger import UTC_PLUS_8

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_AUDIT_LIMIT = 100
MAX_AUDIT_LIMIT = 500

# Roles allowed to see the full email address on member views.  Both member
# endpoints are gated to member_ops/super_admin, so today every authorised
# viewer qualifies; keeping the set explicit makes the masking rule testable.
# String literals on purpose: admin.auth imports admin.service (one-way edge).
EMAIL_VISIBLE_ROLES = frozenset({"member_ops", "finance", "super_admin"})

# member_ops audit scope: actions whose dotted prefix belongs to the
# member/account domain.  super_admin sees the entire log.  Extend here when a
# future trusted writer introduces a new member-domain action prefix.
# "admin.member." admits the member-status writes (admin.member.status_changed,
# member_ops/super_admin gated) while keeping admin.role.* super_admin-only.
MEMBER_OPS_ACTION_PREFIXES = (
    "member.",
    "profile.",
    "membership.",
    "account.",
    "role.member.",
    "usage.member.",
    "admin.member.",
)

# user_profiles.status vocabulary (frozen by the user_profiles_status_allowed
# CHECK in migration 20260905000600_member_status.sql).
MEMBER_STATUSES = ("active", "suspended")

ORDERS_STATUSES = (
    "pending",
    "paid",
    "failed",
    "canceled",
    "refunded",
    "partially_refunded",
)
REFUND_STATUSES = ("pending", "succeeded", "failed")

# Collection runs domain (migration 20260905000601_collection_runs): the
# source_type/status vocabularies are frozen by the table CHECK constraints
# and mirrored here for route validation. String literals on purpose - the
# DB CHECK is the single source of truth, this tuple is a defensive echo.
SOURCE_TYPES = (
    "authorized_csv",
    "official_open",
    "partner",
    "user_submitted",
    "aggregate_authorized",
)
RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

# Subscription statuses that count as an active entitlement; inline constant,
# never user input, so it is safe inside the SQL text.
_ACTIVE_SUBSCRIPTION_STATUSES_SQL = "('trialing', 'active')"

# Shared role-assignment SELECT (list rows and freshly inserted rows).  The
# caller appends its own ``where`` / ``order by`` clauses.
_ROLE_ASSIGNMENT_SELECT = (
    "select ra.id, ra.user_id, ra.role, ra.granted_by_user_id,"
    " ra.granted_at, ra.expires_at, ra.note,"
    " up.username, up.display_name"
    " from public.internal_role_assignments ra"
    " left join public.user_profiles up on up.user_id = ra.user_id"
)


def mask_email(email: str) -> str:
    """Return ``l***@domain`` so a full address never leaks outside gated rows."""
    text = (email or "").strip()
    if not text or "@" not in text:
        return text
    local, _, domain = text.partition("@")
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"


def current_month_period_key(now: Optional[datetime] = None) -> str:
    """UTC+8 'YYYY-MM' period key that usage_quotas rows are bucketed by."""
    moment = now or datetime.now(UTC_PLUS_8)
    return moment.astimezone(UTC_PLUS_8).strftime("%Y-%m")


def _json_value(value: Any) -> Any:
    """asyncpg returns jsonb as text; normalise to Python objects."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _iso(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _money(minor: Any) -> Any:
    return int(minor) if minor is not None else None


def _serialize_member(row: asyncpg.Record, *, email_visible: bool) -> dict[str, Any]:
    """Turn one user_profiles row (with role/subscription/quota aggregates)."""
    email = str(row["email"] or "")
    return {
        "user_id": str(row["user_id"]),
        "username": row["username"] or "",
        "display_name": row["display_name"] or "",
        "email": email if email_visible else mask_email(email),
        "city": row["city"] or "",
        "favorite_area": row["favorite_area"] or "",
        "favorite_asset_type": row["favorite_asset_type"] or "",
        "bio": row["bio"] or "",
        "membership_tier": row["membership_tier"] or "free",
        "daily_query_limit": row["daily_query_limit"],
        "status": row["status"] or "active",
        "created_at": _iso(row["created_at"]),
        "roles": _json_value(row["roles"]),
        "subscriptions": _json_value(row["subscriptions"]),
        "usage_quotas": _json_value(row["usage_quotas"]),
    }


def _serialize_audit_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "actor_user_id": str(row["actor_user_id"]) if row["actor_user_id"] else None,
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "summary": _json_value(row["summary"]),
        "occurred_at": _iso(row["occurred_at"]),
    }


def _serialize_order(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "order_no": row["order_no"],
        "owner_user_id": str(row["owner_user_id"]) if row["owner_user_id"] else None,
        "organization_id": (
            str(row["organization_id"]) if row["organization_id"] else None
        ),
        "product_code": row["product_code"],
        "price_version": row["price_version"],
        "currency": row["currency"],
        "amount_minor": _money(row["amount_minor"]),
        "status": row["status"],
        "provider": row["provider"],
        "provider_session_id": row["provider_session_id"],
        "provider_payment_intent_id": row["provider_payment_intent_id"],
        "paid_at": _iso(row["paid_at"]),
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _serialize_refund(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "order_id": str(row["order_id"]),
        "order_no": row["order_no"],
        "amount_minor": _money(row["amount_minor"]),
        "currency": row["currency"],
        "reason": row["reason"],
        "status": row["status"],
        "provider_refund_id": row["provider_refund_id"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _serialize_collection_run(row: asyncpg.Record) -> dict[str, Any]:
    """Turn one collection_runs row into the admin API payload.

    snapshot_hash is char(64) in Postgres; bpchar output preserves the
    trailing padding, so it is stripped before serialisation.
    """
    raw_hash = row["snapshot_hash"]
    snapshot_hash = str(raw_hash).rstrip() if raw_hash is not None else None
    return {
        "id": str(row["id"]),
        "source_key": row["source_key"],
        "source_type": row["source_type"],
        "status": row["status"],
        "rows_collected": int(row["rows_collected"] or 0),
        "snapshot_hash": snapshot_hash or None,
        "error_message": row["error_message"],
        "operator_user_id": (
            str(row["operator_user_id"]) if row["operator_user_id"] else None
        ),
        "started_at": _iso(row["started_at"]),
        "completed_at": _iso(row["completed_at"]),
        "created_at": _iso(row["created_at"]),
    }


def _serialize_role_assignment(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "role": row["role"],
        "granted_by_user_id": (
            str(row["granted_by_user_id"]) if row["granted_by_user_id"] else None
        ),
        "granted_at": _iso(row["granted_at"]),
        "expires_at": _iso(row["expires_at"]),
        "note": row["note"],
        "username": row["username"] or "",
        "display_name": row["display_name"] or "",
    }


# Shared member SELECT.  Param slots inside the text:
#   $1 = period_key (usage_quotas UTC+8 current month)  [list + detail]
#   $2 = q search term                                   [list only]
#   $3 = page_size, $4 = offset                          [list only]
# The detail variant appends its own ``where up.user_id = $2`` and keeps
# $1 for the period key, so the two call sites stay explicit about ordering.
_MEMBER_BASE_SELECT = """
        select
          up.user_id, up.email, up.username, up.display_name,
          up.city, up.favorite_area, up.favorite_asset_type, up.bio,
          up.membership_tier, up.daily_query_limit,
          up.status,
          up.created_at, up.updated_at,
          coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'role', ra.role, 'granted_at', ra.granted_at, 'expires_at', ra.expires_at
              ) order by ra.role
            )
            from public.internal_role_assignments ra
            where ra.user_id = up.user_id
              and (ra.expires_at is null or ra.expires_at > now())
          ), '[]'::jsonb) as roles,
          coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'product_code', s.product_code, 'status', s.status,
                'currency', s.currency, 'amount_minor', s.amount_minor,
                'current_period_end', s.current_period_end,
                'cancel_at_period_end', s.cancel_at_period_end
              ) order by s.created_at desc
            )
            from public.subscriptions s
            where s.user_id = up.user_id
              and s.status in %s
          ), '[]'::jsonb) as subscriptions,
          coalesce((
            select jsonb_agg(
              jsonb_build_object(
                'usage_kind', u.usage_kind, 'period_key', u.period_key,
                'limit_units', u.limit_units, 'consumed_units', u.consumed_units,
                'reserved_units', u.reserved_units
              )
            )
            from public.usage_quotas u
            where u.scope_key = 'user:' || up.user_id::text
              and u.period_key = $1
          ), '[]'::jsonb) as usage_quotas
        from public.user_profiles up
    """ % _ACTIVE_SUBSCRIPTION_STATUSES_SQL


class AdminService:
    """Read-only asyncpg queries backing the admin API.

    :param pool: an asyncpg pool; when omitted the application-wide pool from
        :func:`backend.app.db.get_pool` is used (only reachable once the admin
        env gate is enabled).
    """

    def __init__(self, pool: Optional[asyncpg.Pool] = None) -> None:
        self._pool = pool

    def _acquire(self) -> asyncpg.Pool:
        return self._pool if self._pool is not None else get_pool()

    # -- roles ---------------------------------------------------------------

    async def fetch_active_roles(self, user_id: UUID) -> List[str]:
        """Active internal roles for one auth user (expires_at null or future)."""
        async with self._acquire().acquire() as conn:
            rows = await conn.fetch(
                "select role from public.internal_role_assignments"
                " where user_id = $1"
                "   and (expires_at is null or expires_at > now())",
                user_id,
            )
        return [row["role"] for row in rows]

    # -- members -------------------------------------------------------------

    async def list_members(
        self,
        q: str = "",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        *,
        email_visible: bool = True,
    ) -> dict[str, Any]:
        """Paginated member directory with roles, active subs and month quota."""
        term = (q or "").strip()
        period_key = current_month_period_key()
        # Placeholder numbering differs between the two statements: the count
        # query has no base SELECT (which already uses $1 for period_key), so
        # the search term is $1 there and $2 in the row query.
        term_sql = (
            " {p} = ''"
            "   or up.display_name ilike '%' || {p} || '%'"
            "   or up.user_id::text ilike '%' || {p} || '%'"
        )
        count_where = " where (" + term_sql.format(p="$1") + ")"
        row_where = " where (" + term_sql.format(p="$2") + ")"
        offset = max(page - 1, 0) * page_size
        sql = (
            _MEMBER_BASE_SELECT
            + row_where
            + " order by up.created_at desc, up.user_id"
            + " limit $3 offset $4"
        )
        async with self._acquire().acquire() as conn:
            total = await conn.fetchval(
                "select count(*) from public.user_profiles up" + count_where, term
            )
            rows = await conn.fetch(sql, period_key, term, page_size, offset)
        return {
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "items": [
                _serialize_member(row, email_visible=email_visible) for row in rows
            ],
        }

    async def get_member(
        self, user_id: UUID, *, email_visible: bool = True
    ) -> Optional[dict[str, Any]]:
        """One member with detail, usage summary and recent usage events."""
        sql = (
            _MEMBER_BASE_SELECT
            + " where up.user_id = $2"
            + " limit 1"
        )
        async with self._acquire().acquire() as conn:
            row = await conn.fetchrow(sql, period_key := current_month_period_key(), user_id)
            if row is None:
                return None
            events = await conn.fetch(
                "select id, usage_kind, operation, units, period_key, created_at"
                " from public.usage_events"
                " where scope_key = $1"
                " order by created_at desc"
                " limit 20",
                f"user:{user_id}",
            )
        member = _serialize_member(row, email_visible=email_visible)
        member["usage_events"] = [
            {
                "id": str(event["id"]),
                "usage_kind": event["usage_kind"],
                "operation": event["operation"],
                "units": event["units"],
                "period_key": event["period_key"],
                "created_at": _iso(event["created_at"]),
            }
            for event in events
        ]
        return member

    # -- audit (append-only read) --------------------------------------------

    async def list_audit(
        self,
        *,
        actor: Optional[UUID] = None,
        action: str = "",
        since: Optional[datetime] = None,
        limit: int = DEFAULT_AUDIT_LIMIT,
        member_ops_scope: bool = False,
    ) -> dict[str, Any]:
        """Recent audit_events rows.

        ``member_ops_scope=True`` restricts rows to the member-domain action
        prefixes in ``MEMBER_OPS_ACTION_PREFIXES`` (the member_ops view of the
        log); super_admin callers pass False and see the whole log.
        """
        action_term = (action or "").strip()
        clauses: List[str] = []
        params: List[Any] = [limit]
        if actor is not None:
            params.append(actor)
            clauses.append("actor_user_id = $%d" % len(params))
        if action_term:
            params.append(action_term)
            clauses.append("action like $%d || '%%'" % len(params))
        if since is not None:
            params.append(since)
            clauses.append("occurred_at >= $%d" % len(params))
        if member_ops_scope:
            params.append([f"{p}%" for p in MEMBER_OPS_ACTION_PREFIXES])
            clauses.append("action like any ($%d)" % len(params))
        where_sql = (" where " + " and ".join(clauses)) if clauses else ""
        sql = (
            "select id, actor_user_id, action, target_type, target_id,"
            " summary, occurred_at from public.audit_events"
            + where_sql
            + " order by occurred_at desc, id desc"
            + " limit $1"
        )
        async with self._acquire().acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return {
            "limit": limit,
            "actor_user_id": str(actor) if actor else None,
            "action": action_term,
            "member_ops_scope": member_ops_scope,
            "items": [_serialize_audit_row(row) for row in rows],
        }

    # -- finance read views --------------------------------------------------

    async def list_orders(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Payment orders with row count and amount-minor subtotal."""
        if status is not None and status not in ORDERS_STATUSES:
            raise HTTPException(
                status_code=422, detail=f"unknown order status: {status}"
            )
        where = " where ($1::text is null or status = $1)"
        offset = max(page - 1, 0) * page_size
        async with self._acquire().acquire() as conn:
            totals = await conn.fetchrow(
                "select count(*) as total, coalesce(sum(amount_minor), 0) as subtotal"
                " from public.payment_orders" + where,
                status,
            )
            rows = await conn.fetch(
                "select id, order_no, owner_user_id, organization_id, product_code,"
                " price_version, currency, amount_minor, status, provider,"
                " provider_session_id, provider_payment_intent_id, paid_at,"
                " created_at, updated_at from public.payment_orders"
                + where
                + " order by created_at desc, id desc"
                + " limit $2 offset $3",
                status,
                page_size,
                offset,
            )
        return {
            "total": int(totals["total"] or 0),
            "subtotal_amount_minor": int(totals["subtotal"] or 0),
            "page": page,
            "page_size": page_size,
            "items": [_serialize_order(row) for row in rows],
        }

    async def list_refunds(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Refunds with row count and amount-minor subtotal."""
        if status is not None and status not in REFUND_STATUSES:
            raise HTTPException(
                status_code=422, detail=f"unknown refund status: {status}"
            )
        where = " where ($1::text is null or r.status = $1)"
        offset = max(page - 1, 0) * page_size
        async with self._acquire().acquire() as conn:
            totals = await conn.fetchrow(
                "select count(*) as total, coalesce(sum(r.amount_minor), 0) as subtotal"
                " from public.refunds r" + where,
                status,
            )
            rows = await conn.fetch(
                "select r.id, r.order_id, po.order_no, r.amount_minor, r.currency,"
                " r.reason, r.status, r.provider_refund_id, r.created_at, r.updated_at"
                " from public.refunds r"
                " left join public.payment_orders po on po.id = r.order_id"
                + where
                + " order by r.created_at desc, r.id desc"
                + " limit $2 offset $3",
                status,
                page_size,
                offset,
            )
        return {
            "total": int(totals["total"] or 0),
            "subtotal_amount_minor": int(totals["subtotal"] or 0),
            "page": page,
            "page_size": page_size,
            "items": [_serialize_refund(row) for row in rows],
        }

    # -- collection runs read / enqueue (internal domain) -------------------

    async def list_collection_runs(
        self,
        status: Optional[str] = None,
        source_key: str = "",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Paginated collection run ledger, newest first.

        ``status`` must be one of ``RUN_STATUSES`` (422 otherwise, mirroring
        the finance views); ``source_key`` is a forgiving substring match so
        an operator can filter by configuration identity prefix.
        """
        if status is not None and status not in RUN_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"unknown collection run status: {status}",
            )
        where = (
            " where ($1::text is null or status = $1)"
            "   and ($2 = '' or source_key ilike '%' || $2 || '%')"
        )
        offset = max(page - 1, 0) * page_size
        async with self._acquire().acquire() as conn:
            total = await conn.fetchval(
                "select count(*) from public.collection_runs" + where,
                status,
                source_key,
            )
            rows = await conn.fetch(
                "select id, source_key, source_type, status, rows_collected,"
                " snapshot_hash, error_message, operator_user_id, started_at,"
                " completed_at, created_at from public.collection_runs"
                + where
                + " order by created_at desc, id desc"
                + " limit $3 offset $4",
                status,
                source_key,
                page_size,
                offset,
            )
        return {
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "items": [_serialize_collection_run(row) for row in rows],
        }

    async def enqueue_collection_run(
        self,
        *,
        source_key: str,
        source_type: str,
        operator_user_id: UUID,
    ) -> dict[str, Any]:
        """Insert one queued collection run plus its audit row in one tx.

        The route pre-validates source_type against ``SOURCE_TYPES`` and the
        non-empty source_key shape; the DB CHECK constraints are the final
        authority. Only the queue write happens here - no collection is ever
        executed by this method (worker executor is a separate unit).
        """
        async with self._acquire().acquire() as conn:
            async with conn.transaction():
                run_id = await conn.fetchval(
                    "insert into public.collection_runs"
                    " (source_key, source_type, operator_user_id)"
                    " values ($1, $2, $3)"
                    " returning id",
                    source_key,
                    source_type,
                    operator_user_id,
                )
                row = await conn.fetchrow(
                    "select id, source_key, source_type, status, rows_collected,"
                    " snapshot_hash, error_message, operator_user_id, started_at,"
                    " completed_at, created_at from public.collection_runs"
                    " where id = $1",
                    run_id,
                )
                await conn.execute(
                    "insert into public.audit_events"
                    " (actor_user_id, action, target_type, target_id, summary)"
                    " values ($1, 'admin.collection.queued', 'collection_run',"
                    " $2, $3::jsonb)",
                    operator_user_id,
                    str(run_id),
                    json.dumps(
                        {
                            "source_key": source_key,
                            "source_type": source_type,
                            "queued_by": str(operator_user_id),
                        },
                        ensure_ascii=False,
                    ),
                )
        return _serialize_collection_run(row)

    # -- role assignments ----------------------------------------------------

    async def list_role_assignments(self) -> dict[str, Any]:
        """Every internal role assignment (current state, incl. expiring)."""
        async with self._acquire().acquire() as conn:
            rows = await conn.fetch(
                _ROLE_ASSIGNMENT_SELECT
                + " order by ra.role, ra.granted_at desc, ra.id"
            )
        return {"items": [_serialize_role_assignment(row) for row in rows]}

    # -- role assignment writes (super_admin only, audited) -----------------

    async def user_exists(self, user_id: UUID) -> bool:
        """True when the target is a real ``auth.users`` row.

        Roles write to ``internal_role_assignments.user_id`` which carries an
        FK to ``auth.users(id)``; the route pre-checks existence so a typo in
        the user_id yields a clean 400 instead of a constraint error.
        """
        async with self._acquire().acquire() as conn:
            found = await conn.fetchval(
                "select 1 from auth.users where id = $1", user_id
            )
        return found is not None

    async def grant_role(
        self,
        *,
        user_id: UUID,
        role: str,
        granted_by: UUID,
        note: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Insert one role assignment plus its audit row in one transaction.

        Raises 409 when the (user_id, role) pair already exists (the table's
        unique constraint - an expired assignment still blocks a re-grant, so
        the caller should revoke first) and 400 when the auth.users FK fails
        (target deleted between the route's existence check and this insert).
        Either way the transaction is rolled back: a failed grant never leaves
        an audit row behind.
        """
        async with self._acquire().acquire() as conn:
            try:
                async with conn.transaction():
                    assignment_id = await conn.fetchval(
                        "insert into public.internal_role_assignments"
                        " (user_id, role, granted_by_user_id, note, expires_at)"
                        " values ($1, $2, $3, $4, $5)"
                        " returning id",
                        user_id,
                        role,
                        granted_by,
                        note or None,
                        expires_at,
                    )
                    row = await conn.fetchrow(
                        _ROLE_ASSIGNMENT_SELECT + " where ra.id = $1",
                        assignment_id,
                    )
                    await conn.execute(
                        "insert into public.audit_events"
                        " (actor_user_id, action, target_type, target_id, summary)"
                        " values ($1, 'admin.role.granted', 'user', $2, $3::jsonb)",
                        granted_by,
                        str(user_id),
                        json.dumps(
                            {"role": role, "granted_by": str(granted_by)},
                            ensure_ascii=False,
                        ),
                    )
            except asyncpg.UniqueViolationError as exc:
                raise HTTPException(
                    status_code=409, detail="该用户已持有此内部角色"
                ) from exc
            except asyncpg.ForeignKeyViolationError as exc:
                raise HTTPException(
                    status_code=400, detail="目标用户不存在"
                ) from exc
        return _serialize_role_assignment(row)

    async def revoke_role(
        self, *, user_id: UUID, role: str, revoked_by: UUID
    ) -> dict[str, Any]:
        """Remove one role assignment plus its audit row in one transaction.

        Raises 404 when no such assignment exists.  The route already guards
        against a super_admin revoking their own super_admin role, so the
        only way to lock the console out is by editing the database directly.
        """
        async with self._acquire().acquire() as conn:
            async with conn.transaction():
                deleted = await conn.fetchval(
                    "delete from public.internal_role_assignments"
                    " where user_id = $1 and role = $2"
                    " returning id",
                    user_id,
                    role,
                )
                if deleted is None:
                    raise HTTPException(
                        status_code=404, detail="该角色分配不存在"
                    )
                await conn.execute(
                    "insert into public.audit_events"
                    " (actor_user_id, action, target_type, target_id, summary)"
                    " values ($1, 'admin.role.revoked', 'user', $2, $3::jsonb)",
                    revoked_by,
                    str(user_id),
                    json.dumps(
                        {"role": role, "revoked_by": str(revoked_by)},
                        ensure_ascii=False,
                    ),
                )
        return {"revoked": True, "user_id": str(user_id), "role": role}

    # -- member status writes (member_ops / super_admin, audited) ------------

    async def set_member_status(
        self,
        *,
        user_id: UUID,
        status: str,
        actor: UUID,
    ) -> Optional[dict[str, Any]]:
        """Set one member's ``user_profiles.status``; audits on an actual change.

        Idempotent by design: when the member already holds the requested
        status the call returns 200-shaped ``changed=False`` and writes no
        audit row.  A real transition updates ``user_profiles.status`` and
        inserts its ``admin.member.status_changed`` audit row inside the same
        transaction (``select ... for update`` serialises concurrent flips, so
        the second caller sees the committed value and becomes a no-op).
        Returns ``None`` when no such member profile exists (route -> 404).

        ``status`` is validated against the DB CHECK vocabulary by the route;
        the UPDATE itself runs on the trusted service connection, which is the
        only path allowed to touch the column (column grant removed for
        authenticated by migration 20260905000600, trigger-guarded as well).
        """
        async with self._acquire().acquire() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    "select status from public.user_profiles"
                    " where user_id = $1"
                    " for update",
                    user_id,
                )
                if current is None:
                    return None
                previous_status = current["status"]
                if previous_status == status:
                    return {
                        "user_id": str(user_id),
                        "status": status,
                        "previous_status": previous_status,
                        "changed": False,
                    }
                await conn.execute(
                    "update public.user_profiles set status = $2"
                    " where user_id = $1",
                    user_id,
                    status,
                )
                await conn.execute(
                    "insert into public.audit_events"
                    " (actor_user_id, action, target_type, target_id, summary)"
                    " values ($1, 'admin.member.status_changed', 'user', $2, $3::jsonb)",
                    actor,
                    str(user_id),
                    json.dumps(
                        {
                            "status": status,
                            "previous_status": previous_status,
                        },
                        ensure_ascii=False,
                    ),
                )
        return {
            "user_id": str(user_id),
            "status": status,
            "previous_status": previous_status,
            "changed": True,
        }


def get_admin_service() -> AdminService:
    """Billing-style dependency: 503 until the admin surface is enabled.

    The env gate ``ADMIN_ENABLED`` defaults to off.  The admin pool is the
    application-wide pool and is only reachable once the gate is on - an
    unconfigured or not-yet-connected database yields the same 503.
    """
    enabled = os.getenv("ADMIN_ENABLED", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=503, detail="admin 未配置")
    try:
        pool = get_pool()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="admin 未配置") from exc
    return AdminService(pool)
