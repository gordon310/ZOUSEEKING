from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.member.routes import get_member_read_store


USER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")
NOW = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


class FakeMemberReadStore:
    def __init__(self) -> None:
        self.me = {
            "available": True,
            "user_id": str(USER_ID),
            "email": "member@example.com",
            "membership_tier": "c_plus",
            "entitlements": {
                "queries": {"used": 2, "limit": 100},
                "reports": {"used": 1, "limit": 12},
                "exports_rows": {"used": 4, "limit": 0},
            },
            "subscription": {
                "plan": "c_plus_monthly",
                "status": "active",
                "current_period_end": "2026-09-30T00:00:00+00:00",
            },
        }
        self.summary = {
            "available": True,
            "period": {
                "key": "2026-09",
                "start": "2026-08-31T16:00:00+00:00",
                "end": "2026-09-30T16:00:00+00:00",
            },
            "entitlements": self.me["entitlements"],
        }

    async def get_me(self, user, *, now):
        assert user.user_id == USER_ID
        assert now == NOW
        return self.me

    async def get_usage_summary(self, user, *, now):
        assert user.user_id == USER_ID
        assert now == NOW
        return self.summary


def test_member_reads_require_authentication() -> None:
    response = TestClient(app).get("/api/me")
    assert response.status_code == 401

    usage = TestClient(app).get("/api/usage/summary")
    assert usage.status_code == 401


def test_member_reads_return_current_user_and_natural_month_summary(monkeypatch) -> None:
    store = FakeMemberReadStore()
    monkeypatch.setattr("backend.app.member.routes.utcnow", lambda: NOW)
    monkeypatch.setattr("backend.app.usage.routes.utcnow", lambda: NOW)
    app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "member@example.com", "Member")
    app.dependency_overrides[get_member_read_store] = lambda: store
    try:
        client = TestClient(app)
        me = client.get("/api/me")
        summary = client.get("/api/usage/summary")
    finally:
        app.dependency_overrides.clear()

    assert me.status_code == 200
    assert me.json()["user_id"] == str(USER_ID)
    assert me.json()["entitlements"]["queries"] == {"used": 2, "limit": 100}
    assert summary.status_code == 200
    assert summary.json()["period"]["key"] == "2026-09"
    assert summary.json()["entitlements"]["reports"]["used"] == 1


def test_member_read_store_cannot_be_used_to_read_another_user(monkeypatch) -> None:
    class OwnerScopedStore(FakeMemberReadStore):
        async def get_me(self, user, *, now):
            if user.user_id != USER_ID:
                from fastapi import HTTPException

                raise HTTPException(status_code=403, detail="member data unavailable")
            return await super().get_me(user, now=now)

    store = OwnerScopedStore()
    monkeypatch.setattr("backend.app.member.routes.utcnow", lambda: NOW)
    app.dependency_overrides[require_user] = lambda: AuthUser(OTHER_USER_ID, "other@example.com", "Other")
    app.dependency_overrides[get_member_read_store] = lambda: store
    try:
        response = TestClient(app).get("/api/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_member_read_store_returns_honest_empty_subscription() -> None:
    class EmptyStore(FakeMemberReadStore):
        async def get_me(self, user, *, now):
            result = dict(self.me)
            result["subscription"] = None
            return result

    app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "member@example.com", "Member")
    app.dependency_overrides[get_member_read_store] = EmptyStore
    try:
        response = TestClient(app).get("/api/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["subscription"] is None
