"""Internal back-office role gate for the read-only admin API.

Roles are stored in ``public.internal_role_assignments`` (migration
``20260905000500_v1_finance_admin_audit.sql``) keyed by the Supabase auth
``user_id``.  A role is active while its ``expires_at`` is null or in the
future; an expired or revoked assignment grants nothing.

Every admin endpoint first authenticates through ``require_user`` (the shared
Supabase token boundary) and then through one ``require_admin_role(...)``
check produced by :func:`require_admin_role`.  The dependency returns an
:class:`AdminPrincipal` (the authenticated user plus the full set of their
active roles) so a handler can apply role-aware row filtering - the audit
endpoint, for example, lets ``member_ops`` see only member-domain actions
while ``super_admin`` sees the whole log.

Role vocabulary (frozen by the database CHECK constraint):
``member_ops``, ``data_ops``, ``task_dispatcher``, ``reviewer``, ``finance``,
``super_admin``.  Permission is per-role per-action; there is no implicit
omnipotence, so every endpoint lists the exact roles that may call it.
"""

from __future__ import annotations

from typing import FrozenSet, Sequence

from fastapi import Depends, HTTPException

from ..auth import AuthUser, require_user
from .service import AdminService, get_admin_service

MEMBER_OPS = "member_ops"
DATA_OPS = "data_ops"
TASK_DISPATCHER = "task_dispatcher"
REVIEWER = "reviewer"
FINANCE = "finance"
SUPER_ADMIN = "super_admin"

ADMIN_ROLES: FrozenSet[str] = frozenset(
    {MEMBER_OPS, DATA_OPS, TASK_DISPATCHER, REVIEWER, FINANCE, SUPER_ADMIN}
)


class AdminPrincipal:
    """Authenticated back-office caller plus their active role names."""

    __slots__ = ("user", "roles")

    def __init__(self, user: AuthUser, roles: Sequence[str]) -> None:
        self.user = user
        self.roles = tuple(sorted(roles))

    @property
    def role_set(self) -> FrozenSet[str]:
        return frozenset(self.roles)

    def has_role(self, *roles: str) -> bool:
        return bool(self.role_set & frozenset(roles))


def require_admin_role(*roles: str):
    """Build a FastAPI dependency that authenticates and enforces a role.

    Resolution order matters and is guaranteed by parameter declaration:
    ``require_user`` (401 on a missing/invalid token) runs before
    ``get_admin_service`` (503 when the admin surface is not enabled), and the
    role lookup itself only runs after both succeed.
    """
    allowed = frozenset(roles)
    if not allowed:
        raise ValueError("require_admin_role needs at least one role")
    if not allowed <= ADMIN_ROLES:
        unknown = ", ".join(sorted(allowed - ADMIN_ROLES))
        raise ValueError(f"unknown admin role(s): {unknown}")

    async def _checker(
        user: AuthUser = Depends(require_user),
        service: AdminService = Depends(get_admin_service),
    ) -> AdminPrincipal:
        active = await service.fetch_active_roles(user.user_id)
        if not active:
            raise HTTPException(status_code=403, detail="当前账号没有后台访问权限")
        if not (allowed & set(active)):
            raise HTTPException(status_code=403, detail="当前账号无权访问该后台资源")
        return AdminPrincipal(user=user, roles=active)

    return _checker
