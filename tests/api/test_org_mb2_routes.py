from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.org.routes import ORG_EXPORT_CSV_COLUMNS, get_org_billing_store, get_org_export_store, get_org_usage_store

OWNER = UUID("00000000-0000-0000-0000-000000000030")
OUTSIDER = UUID("00000000-0000-0000-0000-000000000032")
EXPORT = UUID("00000000-0000-0000-0000-000000000034")


class Store:
    async def get_usage(self, user):
        if user.user_id == OUTSIDER:
            raise HTTPException(status_code=404, detail="organization not found")
        return {"organization": {"name": "大阪数据协作社"}, "role": "owner", "entitlements": {"queries": {"used": 3, "limit": 500, "period": "month"}}}

    async def get_billing(self, user):
        if user.user_id == OUTSIDER:
            raise HTTPException(status_code=404, detail="organization not found")
        return {"organization": {"name": "大阪数据协作社"}, "role": "owner", "orders": [{"period": "2026-09", "product_code": "b_data_pro_monthly", "amount_minor": 399900, "currency": "JPY", "status": "paid", "paid_at": "2026-09-01T00:00:00+00:00"}], "summary": {"order_count": 1, "amount_minor": 399900, "currency": "JPY"}, "subscription": {"product_code": "b_data_pro_monthly", "status": "active", "amount_minor": 399900, "currency": "JPY", "current_period_start": "2026-09-01T00:00:00+00:00", "current_period_end": "2026-10-01T00:00:00+00:00"}}

    async def create_export(self, user):
        return {"id": str(EXPORT), "status": "completed", "row_count": 1, "created_at": "2026-09-16T00:00:00+00:00", "download_url": f"/api/org/exports/{EXPORT}"}

    async def list_exports(self, user):
        return [{"id": str(EXPORT), "status": "completed", "row_count": 1, "created_at": "2026-09-16T00:00:00+00:00", "download_url": f"/api/org/exports/{EXPORT}"}]

    async def download_export(self, user, export_id):
        return "账期,用量类型,已用,上限,订单金额(最小单位),币种,订单状态\r\n2026-09,queries,3,500,399900,JPY,paid\r\n".encode("utf-8-sig")


def setup(user_id=OWNER):
    store = Store()
    app.dependency_overrides[require_user] = lambda: AuthUser(user_id, "masked@example.com", "Member")
    app.dependency_overrides[get_org_usage_store] = lambda: store
    app.dependency_overrides[get_org_billing_store] = lambda: store
    app.dependency_overrides[get_org_export_store] = lambda: store
    return TestClient(app)


def teardown():
    app.dependency_overrides.clear()


def test_org_mb2_requires_auth_and_uses_public_usage_keys():
    assert TestClient(app).get("/api/org/usage").status_code == 401
    client = setup()
    try:
        response = client.get("/api/org/usage")
    finally:
        teardown()
    assert response.status_code == 200
    assert response.json()["entitlements"]["queries"]["used"] == 3
    assert "scope_key" not in response.text


def test_org_billing_returns_honest_fields_without_fake_invoice():
    client = setup()
    try:
        response = client.get("/api/org/billing")
    finally:
        teardown()
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["amount_minor"] == 399900
    assert body["orders"][0]["paid_at"]
    assert "invoice" not in response.text.lower()


def test_org_exports_have_fixed_allowlisted_csv_and_auth_routes():
    assert ORG_EXPORT_CSV_COLUMNS == ("账期", "用量类型", "已用", "上限", "订单金额(最小单位)", "币种", "订单状态")
    client = setup()
    try:
        created = client.post("/api/org/exports", json={})
        listed = client.get("/api/org/exports")
        downloaded = client.get(f"/api/org/exports/{EXPORT}")
    finally:
        teardown()
    assert created.status_code == 201
    assert listed.status_code == 200
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"\xef\xbb\xbf")
    assert downloaded.content.decode("utf-8-sig").splitlines()[0].split(",") == list(ORG_EXPORT_CSV_COLUMNS)
    assert "user_id" not in downloaded.text and "scope_key" not in downloaded.text


def test_org_non_member_is_hidden():
    client = setup(OUTSIDER)
    try:
        response = client.get("/api/org/billing")
    finally:
        teardown()
    assert response.status_code == 404


def test_org_member_is_forbidden_from_billing_and_export():
    class MemberStore(Store):
        async def get_billing(self, user):
            raise HTTPException(status_code=403, detail="organization billing is restricted")

        async def create_export(self, user):
            raise HTTPException(status_code=403, detail="organization export is restricted")

    store = MemberStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(OWNER, "masked@example.com", "Member")
    app.dependency_overrides[get_org_billing_store] = lambda: store
    app.dependency_overrides[get_org_export_store] = lambda: store
    try:
        client = TestClient(app)
        billing = client.get("/api/org/billing")
        export = client.post("/api/org/exports", json={})
    finally:
        teardown()
    assert billing.status_code == 403
    assert export.status_code == 403
