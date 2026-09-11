from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.exports.routes import get_export_store


USER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")


class FakeExportStore:
    def __init__(self):
        self.metered_rows = 0
        self.rows = {
            USER_ID: [
                {"query_key": "q-1", "title": "One", "prefecture": "Osaka", "city": "Osaka", "ward": "Kita", "asset_type": "condo", "year": 2026, "month": 8, "query_status": "completed", "publish_month": "2026-08", "summary": "{}"},
                {"query_key": "q-2", "title": "Two", "prefecture": "Tokyo", "city": "Tokyo", "ward": "Minato", "asset_type": "condo", "year": 2026, "month": 8, "query_status": "completed", "publish_month": "2026-08", "summary": "{}"},
            ],
            OTHER_USER_ID: [{"query_key": "other", "title": "Other", "prefecture": "Tokyo", "city": "Tokyo", "ward": "", "asset_type": "condo", "year": 2026, "month": 8, "query_status": "completed", "publish_month": "2026-08", "summary": "{}"}],
        }

    async def create_export(self, user, query_ids):
        from backend.app.exports.routes import EmptyExport, ExportForbidden, ExportQuotaExceeded, build_csv
        rows = self.rows.get(user.user_id, [])
        if user.user_id == OTHER_USER_ID:
            raise ExportQuotaExceeded("export row quota exceeded")
        if query_ids:
            if any(str(query_id) != "00000000-0000-0000-0000-000000000001" for query_id in query_ids):
                raise ExportForbidden()
        if not rows:
            raise EmptyExport()
        self.metered_rows += len(rows)
        return {"id": "00000000-0000-0000-0000-000000000099", "status": "completed", "row_count": len(rows), "created_at": "2026-09-01T00:00:00+00:00", "download_url": "/api/exports/00000000-0000-0000-0000-000000000099"}

    async def list_exports(self, user):
        return []

    async def download_export(self, user, export_id):
        from backend.app.exports.routes import build_csv
        return build_csv(self.rows.get(user.user_id, []))


def test_exports_require_authentication() -> None:
    client = TestClient(app)
    assert client.get("/api/exports").status_code == 401
    assert client.post("/api/exports", json={}).status_code == 401


def test_export_rejects_a_query_owned_by_another_user(monkeypatch) -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(
        USER_ID, "member@example.com", "Member"
    )
    app.dependency_overrides[get_export_store] = FakeExportStore
    try:
        response = TestClient(app).post(
            "/api/exports",
            json={"query_ids": ["00000000-0000-0000-0000-000000000020"]},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403


def test_export_csv_has_header_and_one_row_per_owned_report(monkeypatch) -> None:
    store = FakeExportStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(
        USER_ID, "member@example.com", "Member"
    )
    app.dependency_overrides[get_export_store] = lambda: store
    try:
        response = TestClient(app).post("/api/exports", json={})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    payload = response.json()
    assert payload["row_count"] == 2
    assert payload["download_url"].startswith("/api/exports/")
    assert store.metered_rows == 2


def test_export_download_is_utf8_bom_csv_with_matching_rows() -> None:
    store = FakeExportStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "member@example.com", "Member")
    app.dependency_overrides[get_export_store] = lambda: store
    try:
        response = TestClient(app).get("/api/exports/00000000-0000-0000-0000-000000000099")
    finally:
        app.dependency_overrides.clear()
    text = response.content.decode("utf-8-sig")
    assert response.status_code == 200
    assert text.startswith("query_key,")
    assert len(text.splitlines()) == 3


def test_export_quota_failure_is_explicit(monkeypatch) -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(
        OTHER_USER_ID, "other@example.com", "Other"
    )
    app.dependency_overrides[get_export_store] = FakeExportStore
    try:
        response = TestClient(app).post("/api/exports", json={})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exceeded"
