from datetime import datetime, timedelta, timezone

import pytest

from backend.app.account_controls import (
    AccountContractError,
    can_grant_internal_role,
    can_invite_member,
    can_manage_billing,
    can_view_contact,
    has_internal_permission,
    package_grants_internal_role,
    public_auth_failure,
    require_recent_auth,
    validate_password,
    validate_profile_patch,
)


def test_profile_patch_keeps_only_user_editable_fields_and_normalizes_text():
    assert validate_profile_patch(
        {
            "display_name": "  小象用户  ",
            "city": "大阪市",
            "bio": "  投资出租  ",
        }
    ) == {
        "display_name": "小象用户",
        "city": "大阪市",
        "bio": "投资出租",
    }


def test_profile_patch_rejects_unknown_and_server_managed_fields():
    with pytest.raises(AccountContractError) as unknown:
        validate_profile_patch({"phone": "090"})
    assert unknown.value.code == "unknown_profile_field"

    with pytest.raises(AccountContractError) as managed:
        validate_profile_patch({"membership_tier": "pro"})
    assert managed.value.code == "managed_profile_field"


def test_profile_patch_rejects_control_characters_and_oversized_values():
    with pytest.raises(AccountContractError) as control:
        validate_profile_patch({"display_name": "小象\n用户"})
    assert control.value.code == "invalid_profile_value"

    with pytest.raises(AccountContractError) as oversized:
        validate_profile_patch({"bio": "x" * 501})
    assert oversized.value.code == "profile_value_too_long"


def test_password_policy_requires_a_long_non_control_value():
    assert validate_password("Correct Horse Battery Staple") == "Correct Horse Battery Staple"

    with pytest.raises(AccountContractError) as short:
        validate_password("short")
    assert short.value.code == "weak_password"

    with pytest.raises(AccountContractError) as control:
        validate_password("Correct Horse\nBattery Staple")
    assert control.value.code == "invalid_password"


def test_auth_failures_are_uniform_for_credentials_and_account_state():
    assert public_auth_failure("invalid_credentials") == public_auth_failure("account_disabled")
    assert public_auth_failure("invalid_credentials") == {
        "code": "authentication_failed",
        "message": "邮箱或密码不正确，或账户暂不可用。",
    }


def test_recent_auth_gate_requires_timezone_and_fifteen_minutes_or_less():
    now = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert require_recent_auth(now - timedelta(minutes=14), now=now) is None

    with pytest.raises(AccountContractError) as stale:
        require_recent_auth(now - timedelta(minutes=16), now=now)
    assert stale.value.code == "recent_auth_required"

    with pytest.raises(AccountContractError) as naive:
        require_recent_auth(datetime(2026, 9, 1), now=now)
    assert naive.value.code == "invalid_auth_time"


def test_organization_roles_enforce_five_seat_and_billing_boundaries():
    assert can_invite_member("owner", 4)
    assert not can_invite_member("owner", 5)
    assert not can_invite_member("member", 4)
    assert can_manage_billing("owner")
    assert not can_manage_billing("member")
    assert can_view_contact("owner", assigned=False)
    assert can_view_contact("member", assigned=True)
    assert not can_view_contact("member", assigned=False)


def test_internal_roles_are_separate_from_packages_and_self_approval():
    assert can_grant_internal_role({"super_admin"})
    assert not can_grant_internal_role({"finance"})
    assert has_internal_permission({"finance"}, "refunds.read")
    assert not has_internal_permission({"finance"}, "data.approve")
    assert not has_internal_permission({"data_ops"}, "data.approve_own")
    assert not package_grants_internal_role("B Data Pro")
