from __future__ import annotations

import pytest

from scripts.staging_m1_acceptance import (
    STAGING_PROJECT_REF,
    redact_evidence,
    select_legacy_keys,
    validate_live_target,
)


def test_live_target_requires_exact_staging_ref_url_and_explicit_flag() -> None:
    expected_url = f"https://{STAGING_PROJECT_REF}.supabase.co"

    assert validate_live_target(STAGING_PROJECT_REF, expected_url, True) == expected_url

    with pytest.raises(ValueError, match="explicit live staging flag"):
        validate_live_target(STAGING_PROJECT_REF, expected_url, False)
    with pytest.raises(ValueError, match="exact staging project"):
        validate_live_target("not-the-staging-project", expected_url, True)
    with pytest.raises(ValueError, match="exact staging URL"):
        validate_live_target(STAGING_PROJECT_REF, "https://example.invalid", True)


def test_select_legacy_keys_never_falls_back_to_publishable_or_secret_keys() -> None:
    payload = [
        {"name": "anon", "api_key": "anon-jwt"},
        {"name": "service_role", "api_key": "service-jwt"},
        {"name": "publishable", "api_key": "sb_publishable_test"},
        {"name": "secret", "api_key": "sb_secret_test"},
    ]

    assert select_legacy_keys(payload) == ("anon-jwt", "service-jwt")

    with pytest.raises(ValueError, match="legacy anon/service_role"):
        select_legacy_keys(payload[2:])


def test_redact_evidence_masks_auth_and_service_secrets_recursively() -> None:
    evidence = {
        "access_token": "access",
        "nested": {
            "refresh_token": "refresh",
            "password": "password",
            "safe_count": 3,
        },
        "action_link": "https://secret.example",
        "checks": [{"api_key": "key"}, {"status": "pass"}],
    }

    assert redact_evidence(evidence) == {
        "access_token": "<redacted>",
        "nested": {
            "refresh_token": "<redacted>",
            "password": "<redacted>",
            "safe_count": 3,
        },
        "action_link": "<redacted>",
        "checks": [{"api_key": "<redacted>"}, {"status": "pass"}],
    }
