from __future__ import annotations

import pytest

from backend.app.services.provenance import (
    REQUIRED_STATISTIC_FIELDS,
    assert_statistic_provenance,
)


def _valid_response() -> dict[str, object]:
    return {
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


def test_statistic_contract_has_one_complete_required_field_set() -> None:
    response = _valid_response()

    assert set(REQUIRED_STATISTIC_FIELDS) <= response.keys()
    assert_statistic_provenance(response)


def test_statistic_contract_names_each_missing_field() -> None:
    response = _valid_response()
    del response["data_class"]
    response["source_url"] = ""

    with pytest.raises(ValueError, match=r"data_class, source_url"):
        assert_statistic_provenance(response)


def test_non_synthetic_storage_row_reports_every_missing_provenance_field() -> None:
    with pytest.raises(ValueError, match=r"source_url, retrieved_at, source_period"):
        assert_statistic_provenance({"data_class": "verified_observation"})
