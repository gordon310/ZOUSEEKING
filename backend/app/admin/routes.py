"""FastAPI back-office admin boundary.

All endpoints require a Supabase-authenticated user; role-bearing routes use
``require_admin_role`` and data access goes through
:class:`~backend.app.admin.service.AdminService`.  Read views are SELECT-only; the mutators are the two role-assignment writes
(grant / revoke), the member-status write (POST /api/admin/members/{user_id}/status,
member_ops/super_admin) and the collection-run enqueue (POST
/api/admin/collection/runs, data_ops/super_admin, queues a run row only - never
executes a collection). Each successful write inserts its ``audit_events`` row
inside the same transaction.  The whole surface is disabled until the
``ADMIN_ENABLED`` env gate is on (503 from the service dependency, mirroring the
billing/usage gates).

Role matrix (spec section 13 + role-assignment unit):

===============================  ============================================
Endpoint                        Roles
===============================  ============================================
GET /api/admin/members          member_ops, super_admin
GET /api/admin/members/{id}     member_ops, super_admin
GET /api/admin/audit            super_admin (full) / member_ops
                                (member-domain actions only)
GET /api/admin/finance/orders   finance, super_admin
GET /api/admin/finance/refunds  finance, super_admin
GET /api/admin/collection/runs  member_ops, data_ops, super_admin
POST /api/admin/collection/runs data_ops, super_admin (enqueue + audit)
POST /api/admin/members/{user_id}/status
                                member_ops, super_admin (write + audit)
GET /api/admin/internal/me      any authenticated user (self roles only)
GET /api/admin/internal/roles   super_admin
POST /api/admin/internal/roles  super_admin (write + audit)
DELETE /api/admin/internal/roles/{user_id}/{role}
                                super_admin (write + audit)
===============================  ============================================

Collection runs: ``collection_runs`` (migration 20260905000601) is an
internal-domain ledger. ``POST /collection/runs`` only enqueues a queued run
row (never executes a collection - the worker is a separate unit) and writes
its ``admin.collection.queued`` audit row in the same transaction.

Email addresses are never written to logs and are only included by the member
views, whose viewers (member_ops/super_admin) both hold email visibility.
Audit summaries carry the affected role and actor user_id only - never email
addresses or other member data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import AuthUser  # noqa: F401  (documented dependency)
from .auth import (
    DATA_OPS,
    FINANCE,
    MEMBER_OPS,
    SUPER_ADMIN,
    ADMIN_ROLES,
    AdminPrincipal,
    require_admin_role,
    require_admin_viewer,
)
from .service import (
    DEFAULT_AUDIT_LIMIT,
    DEFAULT_PAGE_SIZE,
    MAX_AUDIT_LIMIT,
    MAX_PAGE_SIZE,
    SOURCE_TYPES,
    AdminService,
    EMAIL_VISIBLE_ROLES,
    MEMBER_STATUSES,
    get_admin_service,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RoleGrantRequest(BaseModel):
    """POST /api/admin/internal/roles body."""

    user_id: str
    role: str
    note: Optional[str] = None
    expires_at: Optional[str] = None


class CollectionRunEnqueueRequest(BaseModel):
    """POST /api/admin/collection/runs body."""

    source_key: str
    source_type: str


class MemberStatusRequest(BaseModel):
    """POST /api/admin/members/{user_id}/status body."""

    status: str


def _role_or_400(role: Optional[str]) -> str:
    """Validate against the DB CHECK vocabulary (six values)."""
    value = (role or "").strip()
    if value not in ADMIN_ROLES:
        raise HTTPException(status_code=400, detail="无效的内部角色")
    return value


def _member_status_or_400(status: Optional[str]) -> str:
    """Validate against the user_profiles.status CHECK vocabulary."""
    value = (status or "").strip()
    if value not in MEMBER_STATUSES:
        raise HTTPException(
            status_code=400, detail="无效的会员状态（仅 active / suspended）"
        )
    return value


def _role_user_id_or_400(user_id: str) -> UUID:
    try:
        return UUID((user_id or "").strip())
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="无效的 user_id") from exc


def _expires_at_or_400(value: Optional[str]) -> Optional[datetime]:
    """Parse an optional ISO expiry; must be a future instant."""
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="过期时间格式无效，需为 ISO 8601 时间"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="过期时间必须是未来时间")
    return parsed


def _page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> tuple[int, int]:
    return page, page_size


def _source_key_or_400(source_key: Optional[str]) -> str:
    """Trimmed, non-empty source_key; mirrors the registry config identity."""
    value = (source_key or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="无效的 source_key：不能为空")
    if len(value) > 200:
        raise HTTPException(status_code=400, detail="无效的 source_key：长度超过 200")
    return value


def _source_type_or_400(source_type: Optional[str]) -> str:
    """Validate against the DB CHECK vocabulary (five values)."""
    value = (source_type or "").strip()
    if value not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="无效的 source_type")
    return value


def _parse_user_id(user_id: str) -> UUID:
    try:
        return UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid user_id") from exc


def _parse_actor(actor: Optional[str]) -> Optional[UUID]:
    if actor is None or not actor.strip():
        return None
    try:
        return UUID(actor.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid actor user_id") from exc


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    if since is None or not since.strip():
        return None
    try:
        return datetime.fromisoformat(since.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid since timestamp") from exc


@router.get("/members")
async def list_members(
    q: str = Query("", max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    principal: AdminPrincipal = Depends(require_admin_role(MEMBER_OPS, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Member directory: roles, active subscriptions, current-month usage."""
    email_visible = bool(principal.role_set & EMAIL_VISIBLE_ROLES)
    return await service.list_members(
        q=q, page=page, page_size=page_size, email_visible=email_visible
    )


@router.get("/members/{user_id}")
async def get_member(
    user_id: str,
    principal: AdminPrincipal = Depends(require_admin_role(MEMBER_OPS, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """One member with roles, subscriptions, month quota and recent usage."""
    parsed = _parse_user_id(user_id)
    email_visible = bool(principal.role_set & EMAIL_VISIBLE_ROLES)
    member = await service.get_member(parsed, email_visible=email_visible)
    if member is None:
        raise HTTPException(status_code=404, detail="会员不存在")
    return member


@router.get("/audit")
async def list_audit(
    actor: Optional[str] = Query(None),
    action: str = Query("", max_length=160),
    since: Optional[str] = Query(None),
    limit: int = Query(DEFAULT_AUDIT_LIMIT, ge=1, le=MAX_AUDIT_LIMIT),
    principal: AdminPrincipal = Depends(require_admin_role(MEMBER_OPS, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Append-only audit log.  super_admin: full log; member_ops: member scope."""
    member_ops_scope = not principal.has_role(SUPER_ADMIN)
    return await service.list_audit(
        actor=_parse_actor(actor),
        action=action,
        since=_parse_since(since),
        limit=limit,
        member_ops_scope=member_ops_scope,
    )


@router.get("/finance/orders")
async def list_orders(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    principal: AdminPrincipal = Depends(require_admin_role(FINANCE, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Payment orders (read-only) with row count and amount subtotal."""
    return await service.list_orders(status=status, page=page, page_size=page_size)


@router.get("/finance/refunds")
async def list_refunds(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    principal: AdminPrincipal = Depends(require_admin_role(FINANCE, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Refunds (read-only) with row count and amount subtotal."""
    return await service.list_refunds(status=status, page=page, page_size=page_size)


@router.get("/collection/runs")
async def list_collection_runs(
    status: Optional[str] = Query(None),
    source_key: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    principal: AdminPrincipal = Depends(
        require_admin_role(MEMBER_OPS, DATA_OPS, SUPER_ADMIN)
    ),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Collection run ledger (read-only): status, rows, hash, error, times.

    ``status`` must be one of the five run statuses (422 otherwise);
    ``source_key`` filters by substring so an operator can type a
    ``configs/jphouse_23ku/<ward>``-style prefix. member_ops may read the
    ledger; only data_ops/super_admin may enqueue (see POST below).
    """
    return await service.list_collection_runs(
        status=status,
        source_key=(source_key or "").strip(),
        page=page,
        page_size=page_size,
    )


@router.post("/collection/runs", status_code=201)
async def enqueue_collection_run(
    body: CollectionRunEnqueueRequest,
    principal: AdminPrincipal = Depends(require_admin_role(DATA_OPS, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Enqueue one collection run (status queued); audits on success.

    Validation order: source_key shape (non-empty, <= 200 chars) then
    source_type vocabulary.  The run row and its ``admin.collection.queued``
    audit row commit in one transaction.  This endpoint only queues - the
    collection worker executor is a separate unit that claims queued rows.
    """
    source_key = _source_key_or_400(body.source_key)
    source_type = _source_type_or_400(body.source_type)
    return await service.enqueue_collection_run(
        source_key=source_key,
        source_type=source_type,
        operator_user_id=principal.user.user_id,
    )


@router.get("/internal/roles")
async def list_internal_roles(
    principal: AdminPrincipal = Depends(require_admin_role(SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Current internal role assignments (super_admin only)."""
    return await service.list_role_assignments()


@router.get("/internal/me")
async def my_internal_roles(
    principal: AdminPrincipal = Depends(require_admin_viewer()),
) -> dict[str, Any]:
    """The caller's own active internal roles (possibly none).

    Any authenticated user may ask about themselves; the response drives the
    front end's visibility decisions (e.g. only super_admin sees the role
    assignment controls).  Empty array when the caller holds no role.
    """
    return {"user_id": str(principal.user.user_id), "roles": list(principal.roles)}


@router.post("/internal/roles", status_code=201)
async def grant_internal_role(
    body: RoleGrantRequest,
    principal: AdminPrincipal = Depends(require_admin_role(SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Grant one internal role; audits ``admin.role.granted`` on success.

    Validation order: role vocabulary, user_id shape, optional future expiry,
    then existence of the target in ``auth.users`` (400).  A pre-existing
    (user_id, role) row - even an already-expired one - is a 409 so operators
    revoke before re-granting.  The assignment row and its audit row commit in
    one transaction, so a failure never leaves a half-written grant.
    """
    role = _role_or_400(body.role)
    user_id = _role_user_id_or_400(body.user_id)
    expires_at = _expires_at_or_400(body.expires_at)
    if not await service.user_exists(user_id):
        raise HTTPException(status_code=400, detail="目标用户不存在")
    return await service.grant_role(
        user_id=user_id,
        role=role,
        granted_by=principal.user.user_id,
        note=body.note,
        expires_at=expires_at,
    )


@router.delete("/internal/roles/{user_id}/{role}")
async def revoke_internal_role(
    user_id: str,
    role: str,
    principal: AdminPrincipal = Depends(require_admin_role(SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Revoke one internal role; audits ``admin.role.revoked`` on success.

    A super_admin cannot revoke their own super_admin assignment through this
    endpoint: doing so could lock every operator out of the console.  That
    change needs a second super_admin acting here or a manual database edit,
    so the guard returns 400 instead of allowing self-lockout.
    """
    parsed_role = _role_or_400(role)
    parsed_user_id = _role_user_id_or_400(user_id)
    if parsed_user_id == principal.user.user_id and parsed_role == SUPER_ADMIN:
        raise HTTPException(
            status_code=400,
            detail="不能撤销自己的 super_admin：需由另一位 super_admin 撤销，或人工在数据库中处理，避免后台权限被锁死",
        )
    return await service.revoke_role(
        user_id=parsed_user_id,
        role=parsed_role,
        revoked_by=principal.user.user_id,
    )


@router.post("/members/{user_id}/status")
async def set_member_status(
    user_id: str,
    body: MemberStatusRequest,
    principal: AdminPrincipal = Depends(require_admin_role(MEMBER_OPS, SUPER_ADMIN)),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, Any]:
    """Suspend or reactivate one member; audits ``admin.member.status_changed``.

    Validation order: user_id shape (422), then the status vocabulary (400 -
    only active/suspended are storable, mirroring the DB CHECK).  A member
    with no ``user_profiles`` row is a 404.  Setting the current value again
    is idempotent: 200 with ``changed=false`` and no audit row; a real
    transition updates ``user_profiles.status`` and writes its audit row in
    the same transaction.  status is a server-managed column - authenticated
    users cannot write it through their profile-update policy (column grant
    removed by migration 20260905000600), so this trusted path is the only
    way the value changes.
    """
    parsed_user_id = _parse_user_id(user_id)
    status = _member_status_or_400(body.status)
    result = await service.set_member_status(
        user_id=parsed_user_id,
        status=status,
        actor=principal.user.user_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="会员不存在")
    return result
