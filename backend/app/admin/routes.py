"""FastAPI back-office admin boundary.

All endpoints require a Supabase-authenticated user; role-bearing routes use
``require_admin_role`` and data access goes through
:class:`~backend.app.admin.service.AdminService`.  Read views are SELECT-only;
the two role-assignment writes (grant / revoke) are the only mutators and each
successful write inserts its ``audit_events`` row inside the same transaction.
The whole surface is disabled until the ``ADMIN_ENABLED`` env gate is on (503
from the service dependency, mirroring the billing/usage gates).

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
GET /api/admin/internal/me      any authenticated user (self roles only)
GET /api/admin/internal/roles   super_admin
POST /api/admin/internal/roles  super_admin (write + audit)
DELETE /api/admin/internal/roles/{user_id}/{role}
                                super_admin (write + audit)
===============================  ============================================

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
    AdminService,
    EMAIL_VISIBLE_ROLES,
    get_admin_service,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RoleGrantRequest(BaseModel):
    """POST /api/admin/internal/roles body."""

    user_id: str
    role: str
    note: Optional[str] = None
    expires_at: Optional[str] = None


def _role_or_400(role: Optional[str]) -> str:
    """Validate against the DB CHECK vocabulary (six values)."""
    value = (role or "").strip()
    if value not in ADMIN_ROLES:
        raise HTTPException(status_code=400, detail="无效的内部角色")
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
