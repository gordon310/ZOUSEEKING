from uuid import UUID

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.auth import AuthUser, require_user
from backend.app.models import QueryRequest
from backend.app.usage.ledger import QuotaExceeded


def test_query_quota_exhaustion_is_returned_as_429(monkeypatch) -> None:
    async def exhausted(request, user_id):
        raise QuotaExceeded("full")

    monkeypatch.setattr(main, "create_or_get_query_job", exhausted)
    from backend.app.main import app

    app.dependency_overrides[require_user] = lambda: AuthUser(
        UUID("00000000-0000-0000-0000-000000000030"), "real@example.com", "Real"
    )
    try:
        response = TestClient(app).post(
            "/api/query",
            json={"prefecture": "大阪府", "city": "大阪市", "asset_type": "塔楼", "year": 2026, "month": 9},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 429
    assert response.json() == {"error": {"code": "quota_exceeded", "message": "query quota exceeded"}}


def test_query_does_not_use_request_body_username_as_owner(monkeypatch) -> None:
    captured = {}

    async def fake(request: QueryRequest, user_id: str):
        captured.update(user_id=user_id, username=request.username)
        return {"query_key": "q", "status": "pending", "cached": False, "title": "q", "job_id": "j", "report": None}

    monkeypatch.setattr(main, "create_or_get_query_job", fake)
    from backend.app.main import app
    app.dependency_overrides[require_user] = lambda: main.AuthUser(
        UUID("00000000-0000-0000-0000-000000000030"), "real@example.com", "Real"
    )
    try:
        response = TestClient(app).post(
            "/api/query",
            json={"prefecture": "大阪府", "city": "大阪市", "asset_type": "塔楼", "year": 2026, "month": 9, "username": "attacker"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert captured == {"user_id": "00000000-0000-0000-0000-000000000030", "username": "attacker"}
