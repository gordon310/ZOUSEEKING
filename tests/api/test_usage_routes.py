from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.usage.ledger import Ledger, Scope, UsageKind
from backend.app.usage.routes import get_usage_service
from backend.app.usage.service import UsageService


TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000030")
FIXED_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def usage_context():
    service = UsageService(
        Ledger(),
        scope_resolver=lambda user_id, _kind: Scope.owner(user_id),
        limit_resolver=lambda _scope, _kind, _period: 2,
        clock=lambda: FIXED_NOW,
    )
    app.dependency_overrides[require_user] = lambda: AuthUser(TEST_USER_ID, "member@example.com", "测试用户")
    app.dependency_overrides[get_usage_service] = lambda: service
    client = TestClient(app)
    yield client, service
    app.dependency_overrides.clear()


def test_usage_route_is_disabled_without_explicit_service_configuration() -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(TEST_USER_ID, "member@example.com", "测试用户")
    try:
        response = TestClient(app).post(
            "/api/usage/events",
            json={"kind": "query", "units": 1},
            headers={"Idempotency-Key": "disabled-check"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "usage service is not configured"}


def test_usage_route_derives_scope_and_limit_from_trusted_service(usage_context) -> None:
    client, _service = usage_context

    response = client.post(
        "/api/usage/events",
        json={"kind": "query", "units": 1, "operation": "consume", "period": "day"},
        headers={"Idempotency-Key": "query-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "consumed"
    assert body["scope_type"] == "owner"
    assert body["kind"] == "query"
    assert body["consumed_units"] == 1
    assert body["reserved_units"] == 0
    assert body["limit_units"] == 2
    assert "owner_user_id" not in body


def test_usage_route_duplicate_is_safe_and_client_owned_fields_are_forbidden(usage_context) -> None:
    client, _service = usage_context
    request = {"kind": "query", "units": 1}
    first = client.post("/api/usage/events", json=request, headers={"Idempotency-Key": "duplicate-1"})
    duplicate = client.post("/api/usage/events", json=request, headers={"Idempotency-Key": "duplicate-1"})
    forbidden = client.post(
        "/api/usage/events",
        json={**request, "owner_user_id": str(TEST_USER_ID), "limit_units": 999},
        headers={"Idempotency-Key": "client-owned-fields"},
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert forbidden.status_code == 422


def test_usage_route_maps_quota_and_hides_internal_failures(usage_context) -> None:
    client, _service = usage_context
    first = client.post("/api/usage/events", json={"kind": "query", "units": 2}, headers={"Idempotency-Key": "quota-1"})
    rejected = client.post("/api/usage/events", json={"kind": "query", "units": 1}, headers={"Idempotency-Key": "quota-2"})

    assert first.status_code == 200
    assert rejected.status_code == 429
    assert rejected.json() == {"error": {"code": "quota_exceeded", "message": "usage quota exceeded"}}


def test_usage_route_returns_generic_error_for_unexpected_service_failure(usage_context) -> None:
    client, service = usage_context

    def fail(*_args, **_kwargs):
        raise RuntimeError("database password leaked")

    service.apply = fail
    response = client.post(
        "/api/usage/events",
        json={"kind": "query", "units": 1},
        headers={"Idempotency-Key": "unexpected-1"},
    )

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "usage_unavailable", "message": "usage service unavailable"}}
    assert "database password" not in response.text


def test_usage_route_is_not_added_to_phase_one_allowlist(usage_context, monkeypatch) -> None:
    client, _service = usage_context
    monkeypatch.setenv("RELEASE_PHASE", "consumer_intake_preview")

    response = client.post(
        "/api/usage/events",
        json={"kind": "query", "units": 1},
        headers={"Idempotency-Key": "managed-1"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "operation unavailable in current release phase"}


def test_usage_request_requires_reservation_key_for_transitions_and_header() -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(TEST_USER_ID, "member@example.com", "测试用户")
    try:
        service = UsageService(
            Ledger(),
            scope_resolver=lambda user_id, _kind: Scope.owner(user_id),
            limit_resolver=lambda _scope, _kind, _period: 2,
            clock=lambda: FIXED_NOW,
        )
        app.dependency_overrides[get_usage_service] = lambda: service
        client = TestClient(app)
        missing_header = client.post("/api/usage/events", json={"kind": "query", "units": 1})
        missing_reservation = client.post(
            "/api/usage/events",
            json={"kind": "query", "units": 1, "operation": "commit"},
            headers={"Idempotency-Key": "commit-1"},
        )
        reserve_key_from_client = client.post(
            "/api/usage/events",
            json={"kind": "query", "units": 1, "operation": "reserve", "reservation_key": "attacker-key"},
            headers={"Idempotency-Key": "reserve-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert missing_header.status_code == 422
    assert missing_reservation.status_code == 422
    assert reserve_key_from_client.status_code == 422
