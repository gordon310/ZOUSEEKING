from uuid import UUID

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.region_stats_routes import get_region_stats_store
from fastapi.testclient import TestClient

USER = UUID("00000000-0000-0000-0000-000000000030")


class Store:
    async def get(self, user, prefecture, city, ward, asset_type, period):
        if user.user_id != USER:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="机构成员权限不足")
        return {
            "status": "ok", "sample_size": 5, "median_unit_price_jpy_per_sqm": 300000,
            "p25": 200000, "p75": 400000, "distribution": [], "period": period,
            "asset_type": asset_type, "sources": [{"id": "source", "name": "MLIT", "url": "https://www.reinfolib.mlit.go.jp/realEstatePrices/"}],
            "license": {"name": "PDL1.0", "attribution": "出典:不動産情報ライブラリ（国土交通省）"},
            "limitations": "参考信息", "data_class": "scraped_aggregate",
            "rent_sale_ratio": {"available": False, "reason": "租金数据未授权"},
        }


def test_region_stats_requires_authentication():
    assert TestClient(app).get("/api/org/region-stats?prefecture=東京都&city=港区&asset_type=公寓&year=2025&quarter=1").status_code == 401


def test_region_stats_returns_numeric_server_contract():
    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = Store
    try:
        response = TestClient(app).get("/api/org/region-stats?prefecture=東京都&city=港区&asset_type=公寓&year=2025&quarter=1")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["median_unit_price_jpy_per_sqm"] == 300000
    assert response.json()["rent_sale_ratio"]["available"] is False
    assert "organization_members" not in response.text
