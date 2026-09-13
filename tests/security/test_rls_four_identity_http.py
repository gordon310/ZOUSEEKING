"""Live Supabase REST RLS regression gate.

Run with RLS_TEST_BASE_URL, RLS_TEST_ANON_KEY and RLS_TEST_SERVICE_ROLE_KEY
set in the shell. Keys are read only from the environment and are never
printed. The test creates synthetic users/rows and removes them in finally.
"""

from __future__ import annotations

import os

import pytest

from scripts.staging_m1_acceptance import StagingM1Acceptance


def test_rls_four_identity_http_matrix() -> None:
    base_url = os.environ.get("RLS_TEST_BASE_URL", "").strip()
    anon_key = os.environ.get("RLS_TEST_ANON_KEY", "").strip()
    service_key = os.environ.get("RLS_TEST_SERVICE_ROLE_KEY", "").strip()
    if not (base_url and anon_key and service_key):
        pytest.skip(
            "未执行：需要 RLS_TEST_BASE_URL、RLS_TEST_ANON_KEY、"
            "RLS_TEST_SERVICE_ROLE_KEY（仅从环境读取）"
        )

    acceptance = StagingM1Acceptance(base_url, anon_key, service_key)
    owner_email = f"rls-owner-{acceptance.run_id}@example.invalid"
    other_email = f"rls-other-{acceptance.run_id}@example.invalid"
    owner_password = "Rls!" + acceptance.run_id + "aA9"
    other_password = "Rls!" + acceptance.run_id + "bB8"
    try:
        owner = acceptance._admin_create_user(owner_email, owner_password, confirmed=True)
        other = acceptance._admin_create_user(other_email, other_password, confirmed=True)
        owner_id = str(owner["id"])
        other_id = str(other["id"])
        owner_session = acceptance._sign_in(owner_email, owner_password)
        other_session = acceptance._sign_in(other_email, other_password)
        ids = acceptance.seed_rls_fixtures(owner_id, other_id)
        acceptance.check_four_identity_rls(
            ids,
            owner_id,
            str(owner_session["access_token"]),
            str(other_session["access_token"]),
        )
        print("[RESULT] anonymous=PASS; owner=PASS; another_authenticated=PASS; privileged_worker=PASS")
    finally:
        acceptance.cleanup()
        acceptance.close()
    assert not acceptance.cleanup_errors, f"fixture cleanup failed: {acceptance.cleanup_errors}"
