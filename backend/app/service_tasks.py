"""Trusted-backend service-task workflow over the frozen V1 tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .db import get_pool

TASK_STATUSES = frozenset({
    "draft", "open", "matched_pending_consent", "in_progress",
    "completion_pending", "completed", "cancelled", "expired",
    "closed_unconfirmed", "suspended",
})
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "expired", "closed_unconfirmed", "suspended"})
APPLICATION_TERMINAL = frozenset({"withdrawn", "rejected", "match_expired"})
TRANSITIONS = {
    "draft": frozenset({"open", "cancelled"}),
    "open": frozenset({"matched_pending_consent", "cancelled"}),
    "matched_pending_consent": frozenset({"in_progress", "cancelled"}),
    "in_progress": frozenset({"completion_pending", "cancelled"}),
    "completion_pending": frozenset({"completed"}),
}


class ServiceTaskCreate(BaseModel):
    creator_user_id: Optional[UUID] = None
    purpose: str = Field(min_length=1, max_length=200)
    region_pref: Optional[str] = Field(default=None, max_length=200)
    asset_type: Optional[str] = Field(default=None, max_length=80)
    compensation: str = Field(min_length=1, max_length=80)
    public_description: str = Field(min_length=10, max_length=2000)
    apply_deadline: Optional[datetime] = None
    status: Literal["draft", "open"] = "draft"


class ServiceTaskStatus(BaseModel):
    status: str
    application_id: Optional[UUID] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class ServiceTaskApply(BaseModel):
    assigned_member_user_id: UUID


def allowed_transition(old: str, new: str, *, actor: str | None = None) -> bool:
    if old == "completion_pending" and new == "completed":
        return actor == "creator"
    return new in TRANSITIONS.get(old, frozenset())


def require_transition(old: str, new: str, *, actor: str | None = None) -> None:
    if not allowed_transition(old, new, actor=actor):
        raise HTTPException(status_code=409, detail={
            "code": "invalid_status_transition",
            "from_status": old,
            "to_status": new,
        })


def _value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def serialize_task(row: Any) -> dict[str, Any]:
    result = {
        "id": str(_value(row, "id")),
        "purpose": _value(row, "purpose"),
        "region_pref": _value(row, "region_pref"),
        "asset_type": _value(row, "asset_type"),
        "compensation": _value(row, "compensation"),
        "public_description": _value(row, "public_description"),
        "apply_deadline": _iso(_value(row, "apply_deadline")),
        "status": _value(row, "status"),
        "created_at": _iso(_value(row, "created_at")),
        "updated_at": _iso(_value(row, "updated_at")),
    }
    if _value(row, "application_status") is not None:
        result["application_status"] = _value(row, "application_status")
    if _value(row, "creator_consent_status") is not None:
        result["creator_consent_status"] = _value(row, "creator_consent_status")
    return result


async def _org_ids(conn: Any, user_id: UUID, *, managers: bool = False) -> list[UUID]:
    roles = ("owner", "admin") if managers else ("owner", "admin", "member")
    rows = await conn.fetch(
        """select organization_id from public.organization_members
           where user_id=$1 and status='active' and role = any($2::text[])
           order by created_at, id""",
        user_id, list(roles),
    )
    if not rows:
        raise HTTPException(status_code=403 if managers else 404, detail="organization access required")
    return [row["organization_id"] for row in rows]


async def _manager_org_for_assignment(conn: Any, caller_id: UUID, assigned_member_id: UUID) -> UUID:
    row = await conn.fetchrow(
        """select manager.organization_id
           from public.organization_members manager
           join public.organization_members assigned
             on assigned.organization_id=manager.organization_id
            and assigned.user_id=$2 and assigned.status='active'
           where manager.user_id=$1 and manager.status='active'
             and manager.role in ('owner','admin')
           order by manager.created_at, manager.id limit 1""",
        caller_id, assigned_member_id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="assigned member is not active in your organization")
    return row["organization_id"]


async def _append_history(conn: Any, task_id: UUID, old: str | None, new: str, actor: UUID | None, note: str | None = None) -> None:
    if old == new:
        return
    await conn.execute(
        """insert into public.task_status_history
           (task_id,from_status,to_status,changed_by_user_id,note)
           values($1,$2,$3,$4,$5)""",
        task_id, old, new, actor, note,
    )


async def _audit(conn: Any, actor: UUID, action: str, task_id: UUID, summary: dict[str, Any]) -> None:
    await conn.execute(
        """insert into public.audit_events(actor_user_id,action,target_type,target_id,summary)
           values($1,$2,'service_task',$3,$4::jsonb)""",
        actor, action, str(task_id), json.dumps(summary, ensure_ascii=False),
    )


async def list_for_org(user_id: UUID) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        org_ids = await _org_ids(conn, user_id)
        rows = await conn.fetch(
            """select st.*, own.status as application_status
               from public.service_tasks st
               left join lateral (
                 select a.status from public.task_applications a
                 where a.task_id=st.id and a.organization_id = any($1::uuid[])
                 order by a.updated_at desc limit 1
               ) own on true
               where st.status='open' or own.status is not null
               order by st.created_at desc, st.id desc limit 100""",
            org_ids,
        )
        return {"items": [serialize_task(row) for row in rows], "page_size": 100}


async def list_for_creator(user_id: UUID) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """select st.*, cc.c_status as creator_consent_status
               from public.service_tasks st
               left join public.contact_consents cc
                 on cc.task_id=st.id and cc.c_user_id=st.creator_user_id
               where st.creator_user_id=$1
               order by st.created_at desc, st.id desc limit 100""",
            user_id,
        )
        return {"items": [serialize_task(row) for row in rows], "page_size": 100}


async def apply(user_id: UUID, task_id: UUID, body: ServiceTaskApply) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            org_id = await _manager_org_for_assignment(conn, user_id, body.assigned_member_user_id)
            task = await conn.fetchrow("select * from public.service_tasks where id=$1 for update", task_id)
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            if task["status"] != "open":
                raise HTTPException(status_code=409, detail={"code": "task_not_open", "status": task["status"]})
            existing = await conn.fetchrow(
                "select id,status from public.task_applications where task_id=$1 and organization_id=$2 for update",
                task_id, org_id,
            )
            if existing:
                if existing["status"] == "pending":
                    return {"id": str(existing["id"]), "task_id": str(task_id), "status": "pending", "idempotent": True}
                if existing["status"] in APPLICATION_TERMINAL:
                    raise HTTPException(status_code=409, detail={"code": "application_terminal", "status": existing["status"]})
            application = await conn.fetchrow(
                """insert into public.task_applications(task_id,organization_id,assigned_member_user_id)
                   values($1,$2,$3) returning id,status""",
                task_id, org_id, body.assigned_member_user_id,
            )
            return {"id": str(application["id"]), "task_id": str(task_id), "status": application["status"], "idempotent": False}


async def withdraw(user_id: UUID, task_id: UUID) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            org_ids = await _org_ids(conn, user_id, managers=True)
            task = await conn.fetchrow("select * from public.service_tasks where id=$1 for update", task_id)
            application = await conn.fetchrow(
                """select * from public.task_applications where task_id=$1
                   and organization_id=any($2::uuid[]) for update""", task_id, org_ids,
            )
            if not task or not application:
                raise HTTPException(status_code=404, detail="application not found")
            if application["status"] == "withdrawn":
                return {"task_id": str(task_id), "status": "withdrawn", "idempotent": True}
            if application["status"] != "pending" or task["status"] != "open":
                raise HTTPException(status_code=409, detail={"code": "withdrawal_not_allowed", "status": task["status"]})
            await conn.execute("update public.task_applications set status='withdrawn' where id=$1", application["id"])
            return {"task_id": str(task_id), "status": "withdrawn", "idempotent": False}


async def complete(user_id: UUID, task_id: UUID) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            org_ids = await _org_ids(conn, user_id, managers=True)
            task = await conn.fetchrow(
                """select st.* from public.service_tasks st
                   where st.id=$1 and exists (select 1 from public.task_applications a
                   where a.task_id=st.id and a.organization_id=any($2::uuid[]) and a.status='matched')
                   for update""", task_id, org_ids,
            )
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            require_transition(task["status"], "completion_pending")
            await conn.execute("update public.service_tasks set status='completion_pending' where id=$1", task_id)
            await _append_history(conn, task_id, task["status"], "completion_pending", user_id, "B requested completion")
            return {"task_id": str(task_id), "status": "completion_pending"}


async def admin_create(user_id: UUID, body: ServiceTaskCreate) -> dict[str, Any]:
    if body.compensation not in {"paid", "unpaid", "negotiable"} or (body.asset_type and body.asset_type not in {"apartment", "tower", "detached_house", "other"}):
        raise HTTPException(status_code=400, detail={"code": "invalid_task_enum"})
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            task = await conn.fetchrow(
                """insert into public.service_tasks(creator_user_id,purpose,region_pref,asset_type,compensation,public_description,apply_deadline,status)
                   values($1,$2,$3,$4,$5,$6,$7,$8) returning *""",
                body.creator_user_id or user_id, body.purpose, body.region_pref, body.asset_type, body.compensation,
                body.public_description, body.apply_deadline, body.status,
            )
            await _append_history(conn, task["id"], None, body.status, user_id, "task created")
            await _audit(conn, user_id, "admin.service_task.created", task["id"], {"status": body.status})
            return serialize_task(task)


async def admin_status(user_id: UUID, task_id: UUID, body: ServiceTaskStatus) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            task = await conn.fetchrow("select * from public.service_tasks where id=$1 for update", task_id)
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            old = task["status"]
            new = body.status
            if new == "completed":
                raise HTTPException(status_code=409, detail={"code": "creator_confirmation_required"})
            if new == "matched_pending_consent":
                if old != "open" or body.application_id is None:
                    raise HTTPException(status_code=409, detail={"code": "match_requires_open_task_and_application"})
                application = await conn.fetchrow(
                    "select * from public.task_applications where id=$1 and task_id=$2 for update",
                    body.application_id, task_id,
                )
                if not application or application["status"] != "pending":
                    raise HTTPException(status_code=409, detail={"code": "application_not_pending"})
                require_transition(old, new)
                await conn.execute("update public.task_applications set status='matched' where id=$1", application["id"])
                await conn.execute("update public.service_tasks set status=$2 where id=$1", task_id, new)
                await conn.execute(
                    """insert into public.contact_consents(task_id,c_user_id,b_organization_id,b_member_user_id,consent_version)
                       values($1,$2,$3,$4,'v1')""",
                    task_id, task["creator_user_id"], application["organization_id"], application["assigned_member_user_id"],
                )
                await _append_history(conn, task_id, old, new, user_id, body.note)
                await _audit(conn, user_id, "admin.service_task.matched", task_id, {"to_status": new})
                return serialize_task({**dict(task), "status": new})
            if new not in TASK_STATUSES:
                raise HTTPException(status_code=400, detail={"code": "invalid_task_status"})
            if new == "cancelled" and old not in {"draft", "open"}:
                raise HTTPException(status_code=409, detail={"code": "cancellation_not_allowed", "status": old})
            require_transition(old, new)
            updated = await conn.fetchrow("update public.service_tasks set status=$2 where id=$1 returning *", task_id, new)
            await _append_history(conn, task_id, old, new, user_id, body.note)
            await _audit(conn, user_id, "admin.service_task.status_changed", task_id, {"from_status": old, "to_status": new})
            return serialize_task(updated)


async def grant_creator_consent(user_id: UUID, task_id: UUID) -> dict[str, Any]:
    return await _grant_consent(user_id, task_id, "creator")


async def grant_org_consent(user_id: UUID, task_id: UUID) -> dict[str, Any]:
    return await _grant_consent(user_id, task_id, "org")


async def _grant_consent(user_id: UUID, task_id: UUID, actor: Literal["creator", "org"]) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            consent = await conn.fetchrow("select * from public.contact_consents where task_id=$1 for update", task_id)
            task = await conn.fetchrow("select * from public.service_tasks where id=$1 for update", task_id)
            if not task or not consent:
                raise HTTPException(status_code=404, detail="matched task not found")
            if actor == "creator":
                if task["creator_user_id"] != user_id:
                    raise HTTPException(status_code=403, detail="task creator access required")
                field = "c_status"
            else:
                org_ids = await _org_ids(conn, user_id, managers=True)
                if consent["b_organization_id"] not in org_ids:
                    raise HTTPException(status_code=403, detail="matched organization access required")
                field = "b_status"
            if consent[field] == "granted":
                return {"task_id": str(task_id), "status": task["status"], "idempotent": True}
            other_field = "b_status" if field == "c_status" else "c_status"
            if consent[other_field] == "granted" and task["status"] == "matched_pending_consent":
                await conn.execute(
                    f"""update public.contact_consents
                       set {field}='granted', granted_at=coalesce(granted_at,now()), emails_visible_until=coalesce(emails_visible_until,now()+interval '30 days'),
                           c_email_verified=(select email from auth.users where id=c_user_id),
                           b_email_verified=(select email from auth.users where id=b_member_user_id)
                       where task_id=$1""", task_id,
                )
                await conn.execute("update public.service_tasks set status='in_progress' where id=$1", task_id)
                await _append_history(conn, task_id, task["status"], "in_progress", user_id, "mutual contact consent granted")
                return {"task_id": str(task_id), "status": "in_progress", "idempotent": False}
            await conn.execute(f"update public.contact_consents set {field}='granted' where task_id=$1", task_id)
            return {"task_id": str(task_id), "status": task["status"], "idempotent": False}


async def confirm_completion(user_id: UUID, task_id: UUID) -> dict[str, Any]:
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            task = await conn.fetchrow("select * from public.service_tasks where id=$1 for update", task_id)
            if not task:
                raise HTTPException(status_code=404, detail="task not found")
            if task["creator_user_id"] != user_id:
                raise HTTPException(status_code=403, detail="task creator access required")
            require_transition(task["status"], "completed", actor="creator")
            await conn.execute("update public.service_tasks set status='completed' where id=$1", task_id)
            await _append_history(conn, task_id, task["status"], "completed", user_id, "creator confirmed completion")
            return {"task_id": str(task_id), "status": "completed"}
