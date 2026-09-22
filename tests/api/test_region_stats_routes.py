from uuid import UUID

import pytest

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.region_stats_routes import DbRegionStatsStore, get_region_stats_store
from backend.app.services.provenance import REQUIRED_STATISTIC_FIELDS
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
            "limitations": "参考信息", "data_class": "verified_observation",
            "source_url": "https://www.reinfolib.mlit.go.jp/realEstatePrices/",
            "retrieved_at": "2026-09-20T00:00:00+00:00", "source_period": period,
            "transformation_version": "region-stats-v1", "rights_status": "rights_confirmed",
            "rights_confirmed": "yes", "aggregation_method": "mean_median_quartiles",
            "missing_value_policy": "exclude_missing_or_nonpositive_unit_price", "unit": "JPY/sqm",
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


class TrendStore(Store):
    def __init__(self):
        self.calls = []

    async def get_trend(self, user, prefecture, city, ward, asset_type, from_period, to_period):
        self.calls.append((prefecture, city, ward, asset_type, from_period, to_period))
        period = self.calls[-1][-2] or "2025Q4"
        metric = await self.get(user, prefecture, city, ward, asset_type, period)
        next_metric = dict(metric, period="2026Q1", source_period="2026Q1")
        return {
            "status": "ok", "period_count": 2, "asset_type": asset_type, "ward": ward,
            "periods": [metric, next_metric], "excluded_periods": [],
            "comparability": {"consistent": True, "dimensions": {"unit": "JPY/sqm", "asset_type": asset_type}},
        }


def test_region_stats_trend_normalizes_filters_and_each_period_has_provenance_contract():
    store = TrendStore()
    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = lambda: store
    try:
        response = TestClient(app).get(
            "/api/org/region-stats/trend",
            params={"prefecture": "東京都", "city": "港区", "ward": "麻布", "asset_type": "公寓", "from_period": "2025Q4", "to_period": "2026Q1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert store.calls == [("东京都", "港区", "麻布", "公寓", "2025Q4", "2026Q1")]
    assert [period["period"] for period in payload["periods"]] == ["2025Q4", "2026Q1"]
    for period in payload["periods"]:
        assert set(REQUIRED_STATISTIC_FIELDS) <= period.keys()


def test_region_stats_trend_returns_explicit_no_data_without_provenance_when_only_one_period():
    class OnePeriodStore:
        async def get_trend(self, *args):
            return {
                "status": "insufficient_periods", "period_count": 1, "asset_type": "公寓", "ward": None,
                "periods": [], "excluded_periods": [{"period": "2025Q1", "reason": "only_one_comparable_period", "sample_size": 5}],
                "comparability": {"consistent": True, "dimensions": {"unit": "JPY/sqm", "asset_type": "公寓"}},
            }

    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = OnePeriodStore
    try:
        response = TestClient(app).get(
            "/api/org/region-stats/trend",
            params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_periods"
    assert payload["period_count"] == 1
    assert payload["periods"] == []


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


def test_region_stats_returns_an_explicit_empty_result_without_fabricated_provenance():
    class NoDataStore:
        async def get(self, user, prefecture, city, ward, asset_type, period):
            return {
                "status": "insufficient_sample", "sample_size": 0, "period": period,
                "asset_type": asset_type, "sources": [], "license": {},
                "rent_sale_ratio": {"available": False, "reason": "没有可用成交样本"},
            }

    app.dependency_overrides[require_user] = lambda: AuthUser(USER, "hidden@example.com", "Member")
    app.dependency_overrides[get_region_stats_store] = NoDataStore
    try:
        response = TestClient(app).get(
            "/api/org/region-stats",
            params={"prefecture": "北海道", "city": "不存在市", "asset_type": "公寓", "year": 2025, "quarter": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_sample"
    assert payload["sample_size"] == 0
    assert {"data_class", "source_url", "retrieved_at", "source_period"}.isdisjoint(payload)


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


def test_db_region_stats_returns_city_from_the_monthly_rent_row(monkeypatch):
    class Connection:
        async def fetchval(self, query, *args):
            return 1

        async def fetch(self, query, *args):
            if "mlit_transactions" in query:
                return []
            raise AssertionError(f"unexpected fetch query: {query}")

        async def fetchrow(self, query, *args):
            if "source_key='estat_kouri_3001'" in query:
                return {
                    "city": "东京23区", "rent_jpy_per_sqm_month": 3045,
                    "observed_month": "2026-08", "source_label": "e-Stat",
                    "source_url": "https://www.e-stat.go.jp/", "license_label": "e-Stat",
                }
            if "from public.sources" in query:
                return None
            if "rent_reference_stats" in query:
                return None
            raise AssertionError(f"unexpected fetchrow query: {query}")

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr("backend.app.region_stats_routes.get_pool", lambda: Pool())
    result = __import__("asyncio").run(
        DbRegionStatsStore().get(AuthUser(USER, "member@example.test", "Member"), "东京都", "港区", None, "公寓", "2025Q1")
    )

    assert result["monthly_rent_reference"]["city"] == "东京23区"
