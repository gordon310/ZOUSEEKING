"""FastAPI read-only back-office admin boundary.

All endpoints require a Supabase-authenticated user holding at least one of
the roles declared on the route (``require_admin_role``) and all data access
goes through :class:`~backend.app.admin.service.AdminService` SELECT-only
queries.  The whole surface is disabled until the ``ADMIN_ENABLED`` env gate
is on (503 from the service dependency, mirroring the billing/usage gates).

Role matrix (spec section 13):

===============================  ============================================
Endpoint                        Roles
===============================  ============================================
GET /api/admin/members          member_ops, super_admin
GET /api/admin/members/{id}     member_ops, super_admin
GET /api/admin/audit            super_admin (full) / member_ops
                                (member-domain actions only)
GET /api/admin/finance/orders   finance, super_admin
GET /api/admin/finance/refunds  finance, super_admin
GET /api/admin/internal/roles   super_admin
===============================  ============================================

Every method is read-only; nothing here accepts a write body or mutates state.
Email addresses are never written to logs and are only included by the member
views, whose viewers (member_ops/super_admin) both hold email visibility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import AuthUser  # noqa: F401  (documented dependency)
from .auth import (
    FINANCE,
    MEMBER_OPS,
    SUPER_ADMIN,
    AdminPrincipal,
    require_admin_role,
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
