from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import auth
from backend.app.auth import require_user
from backend.app.main import app
from backend.app.member.routes import get_member_read_store


TOKEN = "real-path-token"
USER_ID = UUID("00000000-0000-0000-0000-000000000099")
USER_PAYLOAD = {
    "id": str(USER_ID),
    "email": "member@example.com",
    "user_metadata": {"username": "member"},
}


@pytest.mark.asyncio
async def test_require_user_preserves_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_fetch_supabase_user", lambda access_token: USER_PAYLOAD)

    user = await require_user(f"Bearer {TOKEN}")

    assert user.user_id == USER_ID
    assert user.access_token == TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Basic credentials", "Bearer "])
async def test_require_user_rejects_missing_or_malformed_authorization(authorization) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await require_user(authorization)

    assert exc_info.value.status_code == 401


def test_protected_route_runs_real_authentication_path(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_fetch_supabase_user", lambda access_token: USER_PAYLOAD)

    class FakeMemberReadStore:
        async def get_me(self, user, *, now):
            assert user.user_id == USER_ID
            assert user.access_token == TOKEN
            return {"user_id": str(user.user_id), "email": user.email}

    app.dependency_overrides[get_member_read_store] = FakeMemberReadStore
    try:
        response = TestClient(app).get("/api/me", headers={"Authorization": f"Bearer {TOKEN}"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code < 500
    assert response.status_code == 200
    assert response.json()["user_id"] == str(USER_ID)
