from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.analysis.routes import get_analysis_store
from backend.app.auth import AuthUser, require_user
from backend.app.main import app


USER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")


class FakeAnalysisStore:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def analyze(self, user, request):
        self.calls.append(user.user_id)
        if user.user_id == OTHER_USER_ID:
            from backend.app.analysis.routes import AnalysisQuotaExceeded

            raise AnalysisQuotaExceeded()
        return {
            "status": "ok",
            "metric": request.metric,
            "layout": request.layout,
            "sample_count": 2,
            "period": {"from": "2026-08", "to": "2026-08"},
            "points": [{"month": "2026-08", "value": 6_000_000.0, "sample_count": 2}],
            "source_class": ["scraped_aggregate"],
            "sources": [{"name": "licensed source", "url": "https://example.test"}],
            "quota": {"used": 1, "limit": 5, "remaining": 4, "period": "2026-08"},
        }


def test_analysis_requires_authentication() -> None:
    response = TestClient(app).post("/api/analysis", json={"metric": "sale", "layout": "1LDK"})
    assert response.status_code == 401


def test_analysis_returns_owned_result_and_server_quota() -> None:
    store = FakeAnalysisStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(USER_ID, "member@example.com", "Member")
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        response = TestClient(app).post("/api/analysis", json={"metric": "sale", "layout": "1LDK"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["quota"]["remaining"] == 4
    assert store.calls == [USER_ID]


def test_analysis_quota_is_explicit() -> None:
    store = FakeAnalysisStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(OTHER_USER_ID, "other@example.com", "Other")
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        response = TestClient(app).post("/api/analysis", json={"metric": "sale", "layout": "1LDK"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 429
    assert response.json() == {"error": {"code": "quota_exceeded", "message": "analysis quota exceeded"}}

