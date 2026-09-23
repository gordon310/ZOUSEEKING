"""Invite-only consumer registration boundary."""

from uuid import UUID

import pytest

from backend.app.invites import InviteCodeError, normalize_invite_code
from backend.app.rate_limit import abuse_subject_hash


def test_normalize_invite_code_is_case_insensitive_and_trimmed() -> None:
    assert normalize_invite_code("  Zou-Launch-01 ") == "zou-launch-01"


@pytest.mark.parametrize("value", ["", " ", "x" * 129])
def test_normalize_invite_code_rejects_empty_or_oversized_values(value: str) -> None:
    with pytest.raises(InviteCodeError) as error:
        normalize_invite_code(value)
    assert error.value.code == "invite_code_invalid"


def test_invite_error_is_safe_for_client_i18n() -> None:
    error = InviteCodeError("invite_code_exhausted", 409)
    assert error.code == "invite_code_exhausted"
    assert error.status_code == 409
    assert str(error) == "invite_code_exhausted"


def test_existing_account_path_is_not_an_invite_gate() -> None:
    # Login keeps using Supabase Auth; it must never require an invite code.
    from backend.app.invites import INVITE_REQUIRED_OPERATIONS

    assert "login" not in INVITE_REQUIRED_OPERATIONS
    assert "existing_account" not in INVITE_REQUIRED_OPERATIONS


def test_registration_abuse_subject_uses_a_salted_non_reversible_hash(monkeypatch) -> None:
    monkeypatch.setenv("ABUSE_HASH_SALT", "test-secret")
    digest = abuse_subject_hash("registration", "203.0.113.7")
    assert digest != "203.0.113.7"
    assert len(digest) == 64
