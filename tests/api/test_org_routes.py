from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.org import routes as org_routes
from backend.app.org.routes import get_org_store


USER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")
ORG_ID = UUID("00000000-0000-0000-0000-000000000032")


class FakeOrgStore:
    async def get_me(self, user):
        if user.user_id == OTHER_USER_ID:
            return {"organization": None, "role": None, "seats": None, "plan": None}
        return {
            "organization": {"name": "大阪数据协作社"},
            "role": "owner",
            "seats": {"used": 2, "limit": 5},
            "plan": {
                "name": "B Data Pro",
                "entitlements": {
                    "queries": {"used": 3, "limit": 500, "period": "month"},
                    "analysis": {"used": 0, "limit": 100, "period": "month"},
                },
            },
        }

    async def list_members(self, user):
        if user.user_id == OTHER_USER_ID:
            return []
        return [
            {"display_name": "h***@example.com", "role": "owner", "status": "active", "joined_at": "2026-09-01T00:00:00+00:00"},
            {"display_name": "成员 2", "role": "member", "status": "active", "joined_at": "2026-09-02T00:00:00+00:00"},
        ]


def test_org_api_requires_authentication() -> None:
    client = TestClient(app)
    assert client.get("/api/org/me").status_code == 401
    assert client.get("/api/org/members").status_code == 401


def test_org_api_returns_scoped_summary_and_members_without_pii() -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "hidden@example.com", "Member")
    app.dependency_overrides[get_org_store] = FakeOrgStore
    try:
        client = TestClient(app)
        me = client.get("/api/org/me")
        members = client.get("/api/org/members")
    finally:
        app.dependency_overrides.clear()

    assert me.status_code == 200
    assert me.json()["organization"]["name"] == "大阪数据协作社"
    assert me.json()["seats"] == {"used": 2, "limit": 5}
    assert members.status_code == 200
    assert len(members.json()["members"]) == 2
    assert all("email" not in item and "user_id" not in item for item in members.json()["members"])


def test_org_api_returns_honest_empty_state_for_non_member() -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(OTHER_USER_ID, "other@example.com", "Other")
    app.dependency_overrides[get_org_store] = FakeOrgStore
    try:
        client = TestClient(app)
        me = client.get("/api/org/me")
        members = client.get("/api/org/members")
    finally:
        app.dependency_overrides.clear()

    assert me.status_code == 200
    assert me.json()["organization"] is None
    assert members.status_code == 200
    assert members.json() == {"members": []}


def test_org_api_converts_store_failures_to_structured_error() -> None:
    class BrokenStore(FakeOrgStore):
        async def get_me(self, user):
            raise RuntimeError("database detail must not escape")

    app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "hidden@example.com", "Member")
    app.dependency_overrides[get_org_store] = BrokenStore
    try:
        response = TestClient(app).get("/api/org/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "org_unavailable", "message": "机构信息暂时无法读取。"}}


def test_org_store_reads_real_member_columns_and_masks_auth_email(monkeypatch) -> None:
    class FakeConnection:
        def __init__(self):
            self.queries = []

        async def fetchrow(self, query, *args):
            self.queries.append((query, args))
            return {"organization_id": ORG_ID, "role": "owner", "name": "大阪数据协作社"}

        async def fetch(self, query, *args):
            self.queries.append((query, args))
            if "auth.users" in query:
                return [
                    {"display_name": "g***@gmail.com", "role": "owner", "status": "active", "created_at": datetime(2026, 9, 1)},
                    {"display_name": "成员 2", "role": "member", "status": "active", "created_at": datetime(2026, 9, 2)},
                ]
            raise AssertionError("unexpected query")

    class FakeAcquire:
        def __init__(self, connection):
            self.connection = connection

        async def __aenter__(self):
            return self.connection

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def __init__(self, connection):
            self.connection = connection

        def acquire(self):
            return FakeAcquire(self.connection)

    connection = FakeConnection()
    monkeypatch.setattr(org_routes, "get_pool", lambda: FakePool(connection))

    members = asyncio.run(org_routes.OrganizationReadStore().list_members(AuthUser(USER_ID, "hidden@example.com", "Member")))

    assert members == [
        {"display_name": "g***@gmail.com", "role": "owner", "status": "active", "joined_at": "2026-09-01T00:00:00+00:00"},
        {"display_name": "成员 2", "role": "member", "status": "active", "joined_at": "2026-09-02T00:00:00+00:00"},
    ]
    member_query = connection.queries[-1][0]
    assert "auth.users" in member_query
    assert "user_profiles" not in member_query
    assert "select email" not in member_query.lower()
    assert "om.user_id" not in member_query.lower().split("select", 1)[1].split("from", 1)[0]
    assert "om.organization_id" not in member_query.lower().split("select", 1)[1].split("from", 1)[0]
