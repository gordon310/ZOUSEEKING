"""Every published statistics/data response is checked against the one contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.analysis.routes import get_analysis_store
from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.region_stats_routes import get_region_stats_store
from tests.api.test_renovation_routes import renovation_payload
from backend.app.services.provenance import assert_statistic_provenance


USER = AuthUser(UUID("00000000-0000-0000-0000-000000000030"), "member@example.test", "Member")


def _provenance(**overrides):
    result = {
        "data_class": "verified_observation",
        "source_url": "https://www.reinfolib.mlit.go.jp/realEstatePrices/",
        "retrieved_at": "2026-09-20T00:00:00+00:00",
        "source_period": "2026Q2",
        "transformation_version": "region-stats-v1",
        "rights_status": "rights_confirmed",
        "rights_confirmed": "yes",
        "sample_size": 5,
        "aggregation_method": "mean_median_quartiles",
        "missing_value_policy": "exclude_missing_unit_price",
        "limitations": "Official aggregate; not listing data.",
        "unit": "JPY/sqm",
    }
    result.update(overrides)
    return result


class RegionStore:
    async def get(self, user, prefecture, city, ward, asset_type, period):
        return _provenance(
            status="ok", period=period, asset_type=asset_type,
            mean_unit_price_jpy_per_sqm=300000, median_unit_price_jpy_per_sqm=300000,
            p25=250000, p75=350000, distribution=[], rent_sale_ratio={"available": False},
            sources=[{"name": "MLIT", "url": "https://www.reinfolib.mlit.go.jp/realEstatePrices/"}],
        )


class AnalysisStore:
    async def analyze(self, user, request):
        return _provenance(
            metric=request.metric, layout=request.layout, status="ok",
            points=[{"month": "2026-08", "value": 300000, "sample_count": 5}],
            source_class=["verified_observation"], sources=[],
            aggregation_method="arithmetic_mean", unit="JPY",
            quota={"used": 1, "limit": 5, "remaining": 4, "period": "2026-09"},
        )


def test_published_statistics_endpoints_return_the_shared_contract() -> None:
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[get_region_stats_store] = RegionStore
    app.dependency_overrides[get_analysis_store] = AnalysisStore
    try:
        client = TestClient(app)
        responses = [
            client.get("/api/org/region-stats", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓", "year": 2026, "quarter": 2}),
            client.post("/api/analysis", json={"metric": "sale", "layout": "1LDK"}),
        ]
    finally:
        app.dependency_overrides.clear()

    for response in responses:
        assert response.status_code == 200
        assert_statistic_provenance(response.json())


def test_published_statistics_never_expose_provenance_placeholder_literals(client) -> None:
    """A timestamp or source period must be evidence, never an internal token."""
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[get_region_stats_store] = RegionStore
    app.dependency_overrides[get_analysis_store] = AnalysisStore
    try:
        responses = [
            client.get("/api/org/region-stats", params={"prefecture": "东京都", "city": "港区", "asset_type": "公寓", "year": 2026, "quarter": 2}),
            client.post("/api/analysis", json={"metric": "sale", "layout": "1LDK"}),
            client.post("/api/renovation/estimates", json=renovation_payload()),
        ]
    finally:
        app.dependency_overrides.clear()

    placeholders = ("_created_at", "database_imported_at")
    for response in responses:
        assert response.status_code == 200
        payload = response.json()
        assert_statistic_provenance(payload)
        assert not any(token in str(payload["transformation_version"]) for token in placeholders)
        assert not any(token in str(payload["source_period"]) for token in placeholders)
        assert not any(token in str(payload["retrieved_at"]) for token in placeholders)
        assert datetime.fromisoformat(payload["retrieved_at"].replace("Z", "+00:00"))
        assert payload["rights_confirmed"] in {"yes", "no", "not_applicable"}
