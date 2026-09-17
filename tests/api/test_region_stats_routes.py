from uuid import UUID

import pytest

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
            "status": "ok", "sample_size": 5, "mean_unit_price_jpy_per_sqm": 310000, "median_unit_price_jpy_per_sqm": 300000,
            "p25": 200000, "p75": 400000, "distribution": [], "period": period,
            "asset_type": asset_type, "sources": [{"id": "source", "name": "MLIT", "url": "https://www.reinfolib.mlit.go.jp/realEstatePrices/"}],
            "license": {"name": "PDL1.0", "attribution": "出典:不動産情報ライブラリ（国土交通省）"},
            "limitations": "参考信息", "data_class": "scraped_aggregate",
            "rent_sale_ratio": {"available": False, "reason": "租金数据未授权"},
        }


class CapturingStore(Store):
    def __init__(self):
        self.calls = []
        self.region_calls = []

    async def get(self, user, prefecture, city, ward, asset_type, period):
        self.calls.append((ward, asset_type))
        self.region_calls.append((prefecture, city, ward, asset_type, period))
        result = await super().get(user, prefecture, city, ward, asset_type, period)
        result["ward"] = ward
        if asset_type == "塔楼":
            result["disclosure"] = {"code": "tower_merged_into_apartment"}
        return result


def test_region_stats_normalizes_japanese_region_names_before_store_call():
    store = CapturingStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = lambda: store
    try:
        response = TestClient(app).get(
            "/api/org/region-stats",
            params={"prefecture": "東京都", "city": "港区", "ward": "麻布", "asset_type": "公寓", "year": 2025, "quarter": 1},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert store.region_calls == [("东京都", "港区", "麻布", "公寓", "2025Q1")]


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
    assert response.json()["mean_unit_price_jpy_per_sqm"] == 310000
    assert response.json()["rent_sale_ratio"]["available"] is False
    assert "organization_members" not in response.text


@pytest.mark.parametrize("ward", [None, "", "   ", "__not_subdivided__"])
def test_region_stats_normalizes_non_specific_ward_values(ward):
    store = CapturingStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = lambda: store
    try:
        params = {"prefecture": "東京都", "city": "港区", "asset_type": "公寓", "year": 2025, "quarter": 1}
        if ward is not None:
            params["ward"] = ward
        response = TestClient(app).get("/api/org/region-stats", params=params)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["sample_size"] == 5
    assert response.json()["ward"] is None
    assert store.calls == [(None, "公寓")]


def test_region_stats_keeps_real_ward_and_tower_disclosure():
    store = CapturingStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = lambda: store
    try:
        response = TestClient(app).get(
            "/api/org/region-stats",
            params={"prefecture": "東京都", "city": "港区", "ward": "麻布", "asset_type": "塔楼", "year": 2025, "quarter": 1},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["ward"] == "麻布"
    assert response.json()["disclosure"]["code"] == "tower_merged_into_apartment"
    assert store.calls == [("麻布", "塔楼")]


def test_region_stats_rejects_unknown_asset_type():
    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    try:
        response = TestClient(app).get(
            "/api/org/region-stats",
            params={"prefecture": "東京都", "city": "港区", "asset_type": "未知", "year": 2025, "quarter": 1},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400
