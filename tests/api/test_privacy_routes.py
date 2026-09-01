from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.routes.privacy import get_deletion_executor


USER = AuthUser(UUID("00000000-0000-0000-0000-000000000030"), "member@example.invalid", "演示用户")


def teardown_function():
    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides.pop(get_deletion_executor, None)


def test_privacy_metadata_does_not_require_authentication():
    response = TestClient(app).get("/api/privacy")

    assert response.status_code == 200
    body = response.json()
    assert body["privacy_policy_version"] == "privacy-2026-08"
    assert body["terms_version"] == "terms-2026-08"
    assert body["account_deletion"]["no_side_effect_on_unavailable"] is True


def test_deletion_request_requires_authenticated_user():
    response = TestClient(app).post(
        "/api/account/deletion-request",
        json={
            "privacy_policy_version": "privacy-2026-08",
            "terms_version": "terms-2026-08",
            "confirmation": "DELETE_ACCOUNT",
        },
    )

    assert response.status_code == 401


def test_deletion_request_fails_closed_without_executor_and_leaks_no_identity():
    app.dependency_overrides[require_user] = lambda: USER

    response = TestClient(app).post(
        "/api/account/deletion-request",
        json={
            "privacy_policy_version": "privacy-2026-08",
            "terms_version": "terms-2026-08",
            "confirmation": "DELETE_ACCOUNT",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "account deletion service is not configured; no account data was changed"
    assert "member@example.invalid" not in response.text
    assert str(USER.user_id) not in response.text


def test_deletion_request_rejects_stale_policy_versions_before_executor():
    app.dependency_overrides[require_user] = lambda: USER

    response = TestClient(app).post(
        "/api/account/deletion-request",
        json={
            "privacy_policy_version": "privacy-2026-07",
            "terms_version": "terms-2026-08",
            "confirmation": "DELETE_ACCOUNT",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "please accept the current privacy and terms versions"


def test_deletion_request_does_not_echo_or_use_client_supplied_identity_fields():
    app.dependency_overrides[require_user] = lambda: USER

    response = TestClient(app).post(
        "/api/account/deletion-request",
        json={
            "privacy_policy_version": "privacy-2026-08",
            "terms_version": "terms-2026-08",
            "confirmation": "DELETE_ACCOUNT",
            "email": "member@example.invalid",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "account deletion service is not configured; no account data was changed"
    assert "member@example.invalid" not in response.text


def test_deletion_request_returns_executor_receipt_without_exposing_email():
    app.dependency_overrides[require_user] = lambda: USER

    class RecordingExecutor:
        def __init__(self):
            self.calls = []

        async def submit(self, user, *, requested_at):
            self.calls.append((user.user_id, requested_at))
            return {
                "status": "pending",
                "request_id": "delreq-test-only",
                "policy_version": "privacy-2026-08",
                "requested_at": "2026-08-31T02:00:00Z",
                "email": "member@example.invalid",
            }

    executor = RecordingExecutor()
    app.dependency_overrides[get_deletion_executor] = lambda: executor

    response = TestClient(app).post(
        "/api/account/deletion-request",
        json={
            "privacy_policy_version": "privacy-2026-08",
            "terms_version": "terms-2026-08",
            "confirmation": "DELETE_ACCOUNT",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "pending",
        "request_id": "delreq-test-only",
        "policy_version": "privacy-2026-08",
        "requested_at": "2026-08-31T02:00:00Z",
    }
    assert executor.calls[0][0] == USER.user_id
