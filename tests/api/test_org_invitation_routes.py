import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.org.routes import DbOrganizationInvitationStore, get_org_invitation_store, invitation_token_hash


OWNER = AuthUser(UUID("00000000-0000-0000-0000-000000000101"), "owner@example.com", "Owner")
INVITEE = AuthUser(UUID("00000000-0000-0000-0000-000000000102"), "invitee@example.com", "Invitee")


class FakeInvitationStore:
    def __init__(self):
        self.created = []

    async def create(self, user, email, role):
        self.created.append((user.user_id, email, role))
        return {"id": "internal-id", "invite_token": "plain-token", "expires_at": "2026-09-23T00:00:00+00:00"}

    async def list(self, user):
        return [{"status": "pending", "email": "invitee@example.com", "role": "member"}]

    async def revoke(self, user, invitation_id):
        return {"revoked": True, "status": "revoked"}

    async def accept(self, user, token):
        return {"accepted": True, "organization": {"name": "Test Org"}, "role": "member"}


def setup(store, user=OWNER):
    app.dependency_overrides[require_user] = lambda: user
    app.dependency_overrides[get_org_invitation_store] = lambda: store
    return TestClient(app)


def teardown():
    app.dependency_overrides.clear()


def test_owner_can_create_invitation_and_response_never_contains_hash():
    store = FakeInvitationStore()
    try:
        response = setup(store).post("/api/org/invitations", json={"email": "invitee@example.com", "role": "member"})
    finally:
        teardown()
    assert response.status_code == 201
    assert response.json()["invite_token"] == "plain-token"
    assert "token_hash" not in response.text


def test_invitation_routes_expose_list_revoke_and_accept():
    store = FakeInvitationStore()
    try:
        client = setup(store)
        assert client.get("/api/org/invitations").json()["invitations"][0]["status"] == "pending"
        assert client.post("/api/org/invitations/00000000-0000-0000-0000-000000000103/revoke").json()["revoked"] is True
        assert client.post("/api/org/invitations/accept", json={"token": "plain-token"}).json()["accepted"] is True
    finally:
        teardown()


def test_anonymous_invitation_creation_requires_authentication():
    try:
        response = TestClient(app).post("/api/org/invitations", json={"email": "x@example.com", "role": "member"})
    finally:
        teardown()
    assert response.status_code == 401


@pytest.mark.parametrize("branch", ["already_accepted", "already_member", "accepted"])
def test_database_acceptance_success_branches_have_the_same_real_organization_name(branch):
    class Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self):
            self.queries = []
            self.row = {
                "id": UUID("00000000-0000-0000-0000-000000000301"),
                "organization_id": UUID("00000000-0000-0000-0000-000000000302"),
                "email": INVITEE.email,
                "role": "member",
                "token_hash": invitation_token_hash("plain-token"),
                "accepted_at": datetime.now(timezone.utc) if branch == "already_accepted" else None,
                "revoked_at": None,
                "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            }

        def transaction(self):
            return Transaction()

        async def fetchrow(self, query, *args):
            self.queries.append((query, args))
            if "from public.organization_invitations" in query and "token_hash=$1" in query:
                row = dict(self.row)
                if "join public.organizations" in query:
                    row["organization_name"] = "真实机构名"
                return row
            if "seat_limit" in query:
                return {"seat_limit": 5}
            raise AssertionError(f"unexpected fetchrow query: {query}")

        async def fetchval(self, query, *args):
            self.queries.append((query, args))
            if "organization_members where organization_id=$1 and user_id=$2" in query:
                return 1 if branch == "already_member" else None
            if "count(*) from public.organization_members" in query:
                return 0
            if "count(*) from public.organization_invitations" in query:
                return 1
            raise AssertionError(f"unexpected fetchval query: {query}")

        async def execute(self, query, *args):
            self.queries.append((query, args))

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

    from backend.app.org import routes as org_routes

    connection = FakeConnection()
    original_get_pool = org_routes.get_pool
    org_routes.get_pool = lambda: FakePool(connection)
    try:
        response = asyncio.run(DbOrganizationInvitationStore().accept(INVITEE, "plain-token"))
    finally:
        org_routes.get_pool = original_get_pool

    assert response["accepted"] is True
    assert response.get(branch) is True if branch != "accepted" else "already_accepted" not in response
    assert response["organization"] == {"name": "真实机构名"}
    assert response["organization"]["name"] != ""
    assert any("join public.organizations" in query for query, _ in connection.queries)
