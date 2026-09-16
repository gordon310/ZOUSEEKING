from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.admin.auth import AdminPrincipal
from backend.app.admin.service import get_admin_service


class FakeAdminService:
    async def fetch_active_roles(self, user_id):
        return ["member_ops"]

    async def create_organization(self, **kwargs):
        return {"organization": {"id": "org-id", "name": kwargs["name"]}, "owner_invitation": None}


def test_member_ops_can_create_organization_and_get_audited_result():
    app.dependency_overrides[require_user] = lambda: AuthUser(UUID("00000000-0000-0000-0000-000000000102"), "ops@example.com", "Ops")
    app.dependency_overrides[get_admin_service] = lambda: FakeAdminService()
    try:
        response = TestClient(app).post("/api/admin/organizations", json={"name": "机构一"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["organization"]["name"] == "机构一"
