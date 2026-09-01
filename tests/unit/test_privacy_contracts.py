from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services.privacy import (
    PRIVACY_POLICY_VERSION,
    TERMS_VERSION,
    build_consent_record,
    build_deletion_plan,
    privacy_metadata,
)


def test_consent_record_contains_versioned_utc_timestamp_and_metadata():
    accepted_at = datetime(2026, 8, 31, 1, 2, 3, tzinfo=timezone.utc)

    record = build_consent_record(accepted_at=accepted_at)

    assert record.privacy_policy_version == PRIVACY_POLICY_VERSION
    assert record.terms_version == TERMS_VERSION
    assert record.accepted_at == accepted_at
    assert record.as_auth_metadata() == {
        "consent_version": PRIVACY_POLICY_VERSION,
        "consent_at": "2026-08-31T01:02:03Z",
        "terms_version": TERMS_VERSION,
        "consent_source": "registration",
    }


def test_consent_record_rejects_naive_and_future_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_consent_record(accepted_at=datetime(2026, 8, 31, 1, 2, 3))

    future = datetime.now(timezone.utc) + timedelta(minutes=1)
    with pytest.raises(ValueError, match="future"):
        build_consent_record(accepted_at=future)


def test_deletion_plan_has_explicit_internal_sla_deadlines():
    requested_at = datetime(2026, 8, 31, 2, 0, tzinfo=timezone.utc)

    plan = build_deletion_plan(requested_at)

    assert plan == {
        "requested_at": "2026-08-31T02:00:00Z",
        "acknowledgement_due": "2026-09-01T02:00:00Z",
        "access_restriction_due": "2026-09-01T02:00:00Z",
        "primary_data_deletion_due": "2026-09-30T02:00:00Z",
        "backup_expiry_due": "2026-11-29T02:00:00Z",
    }


def test_privacy_metadata_is_public_and_marks_unconfigured_deletion_executor():
    metadata = privacy_metadata()

    assert metadata["privacy_policy_version"] == PRIVACY_POLICY_VERSION
    assert metadata["terms_version"] == TERMS_VERSION
    assert metadata["consent"]["accepted_at"] == "client_generated_utc_submission"
    assert metadata["consent"]["timestamp_authority"] == "untrusted_until_server_capture"
    assert metadata["authentication"]["all_session_revocation"] == "not_verified"
    assert metadata["account_deletion"]["status"] == "unavailable_without_trusted_executor"
    assert metadata["support"]["url"] == "/support.html"
