"""Offline account, organization, and authorization contracts.

These helpers deliberately do not touch a database or an identity provider.
They define the server-side boundary that future account routes must enforce.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


PROFILE_EDITABLE_FIELDS = frozenset(
    {
        "display_name",
        "city",
        "favorite_area",
        "favorite_asset_type",
        "bio",
    }
)
PROFILE_MANAGED_FIELDS = frozenset(
    {
        "user_id",
        "email",
        "username",
        "membership_tier",
        "daily_query_limit",
        "organization_id",
        "organization_role",
        "internal_roles",
        "partner_status",
    }
)
PROFILE_FIELD_LIMITS = {
    "display_name": 80,
    "city": 100,
    "favorite_area": 120,
    "favorite_asset_type": 50,
    "bio": 500,
}

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
RECENT_AUTH_WINDOW = timedelta(minutes=15)
MAX_ACTIVE_ORGANIZATION_MEMBERS = 5

INTERNAL_ROLE_PERMISSIONS = {
    "member_ops": frozenset({"account_status.read", "package.read", "support_notes.write"}),
    "data_ops": frozenset({"authorized_data.write", "data.correct"}),
    "task_dispatch": frozenset({"task.pause", "task.assign"}),
    "reviewer": frozenset({"data.approve", "report.approve"}),
    "finance": frozenset({"orders.read", "refunds.read", "refunds.write", "price_draft.write"}),
    "super_admin": frozenset({"role.assign", "price.approve", "emergency_config.write"}),
    "database_ops": frozenset({"database.reconcile", "database.restore_plan.read"}),
    "backup_operator": frozenset({"backup.create", "backup.verify"}),
    "security_reviewer": frozenset({"security.review"}),
    "release_owner": frozenset({"release.approve"}),
}


class AccountContractError(ValueError):
    """Stable, non-provider-specific account contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _has_control_character(value: str) -> bool:
    return any(character in "\r\n\x00" or (ord(character) < 32 and character != "\t") for character in value)


def validate_profile_patch(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return a normalized user-editable profile patch.

    Identity, membership, quota, organization, and role fields are never
    accepted from a browser patch.
    """

    if not isinstance(payload, Mapping):
        raise AccountContractError("invalid_profile_payload", "资料更新格式不正确。")

    keys = set(payload)
    managed = keys & PROFILE_MANAGED_FIELDS
    if managed:
        raise AccountContractError("managed_profile_field", "账户身份和权益字段由服务端管理。")
    unknown = keys - PROFILE_EDITABLE_FIELDS
    if unknown:
        raise AccountContractError("unknown_profile_field", "资料字段不在可编辑范围内。")

    normalized: dict[str, str] = {}
    for field, raw_value in payload.items():
        if not isinstance(raw_value, str):
            raise AccountContractError("invalid_profile_value", "资料字段必须是文本。")
        value = raw_value.strip()
        if _has_control_character(value):
            raise AccountContractError("invalid_profile_value", "资料字段包含不允许的控制字符。")
        if len(value) > PROFILE_FIELD_LIMITS[field]:
            raise AccountContractError("profile_value_too_long", "资料字段超过长度限制。")
        normalized[field] = value
    return normalized


def validate_password(password: Any) -> str:
    """Validate the client-facing baseline; hashing remains provider-owned."""

    if not isinstance(password, str):
        raise AccountContractError("weak_password", "密码不符合安全要求。")
    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        raise AccountContractError("weak_password", "密码不符合安全要求。")
    if _has_control_character(password):
        raise AccountContractError("invalid_password", "密码包含不允许的控制字符。")
    return password


def public_auth_failure(_reason: str | None = None) -> dict[str, str]:
    """Return the same response for bad credentials and unavailable accounts."""

    return {
        "code": "authentication_failed",
        "message": "邮箱或密码不正确，或账户暂不可用。",
    }


def require_recent_auth(
    authenticated_at: datetime,
    *,
    now: datetime | None = None,
    window: timedelta = RECENT_AUTH_WINDOW,
) -> None:
    """Raise unless a sensitive action has a recent timezone-aware login."""

    current = now or datetime.now(timezone.utc)
    if (
        authenticated_at.tzinfo is None
        or authenticated_at.utcoffset() is None
        or current.tzinfo is None
        or current.utcoffset() is None
    ):
        raise AccountContractError("invalid_auth_time", "认证时间必须包含时区。")
    if authenticated_at > current or current - authenticated_at > window:
        raise AccountContractError("recent_auth_required", "请重新认证后再修改安全设置。")


def can_invite_member(actor_role: str, active_member_count: int) -> bool:
    if active_member_count < 0:
        raise AccountContractError("invalid_member_count", "机构成员数量不正确。")
    return actor_role == "owner" and active_member_count < MAX_ACTIVE_ORGANIZATION_MEMBERS


def can_manage_billing(actor_role: str) -> bool:
    return actor_role == "owner"


def can_view_contact(actor_role: str, *, assigned: bool) -> bool:
    return actor_role == "owner" or (actor_role == "member" and assigned)


def has_internal_permission(roles: Iterable[str], action: str) -> bool:
    return any(action in INTERNAL_ROLE_PERMISSIONS.get(role, frozenset()) for role in roles)


def can_grant_internal_role(roles: Iterable[str]) -> bool:
    return "super_admin" in set(roles)


def package_grants_internal_role(_package: str) -> bool:
    return False
