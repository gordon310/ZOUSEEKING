from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[2] / "scripts" / "build_licensed_aggregate.py"
    spec = importlib.util.spec_from_file_location("build_licensed_aggregate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_filter_aggregate_removes_unlicensed_fields_and_keeps_official_sale() -> None:
    module = _module()
    source = [
        {
            "ward": "fixture",
            "config": "configs/family/ward.json",
            "rents": {"1LDK": 1.0},
            "suumo_updated": "unlicensed-source-marker",
            "sale": {
                "layout_price_man_yen": {"1LDK": 1000},
                "unit_man_yen_per_sqm": 100.0,
                "updated": "official-period",
            },
        }
    ]

    filtered, summary = module.filter_aggregate(source)

    assert filtered[0] == {
        "ward": "fixture",
        "config": "configs/family/ward.json",
        "sale": {
            "layout_price_man_yen": {"1LDK": 1000},
            "unit_man_yen_per_sqm": 100.0,
            "updated": "official-period",
        },
    }
    assert summary["fields"] == ["rents", "source_update"]
    assert summary["reason"] == "unlicensed_source"
    assert summary["rules_version"] == "licensed-aggregate-v1"


def test_filter_wrapped_aggregate_keeps_wrapper_and_adds_metadata() -> None:
    module = _module()
    source = {
        "count": 1,
        "failed_count": 0,
        "collected": [{"ward": "fixture", "rents": {"1LDK": 1.0}}],
    }

    filtered, summary = module.filter_aggregate(source)

    assert filtered["count"] == 1
    assert filtered["failed_count"] == 0
    assert filtered["collected"] == [{"ward": "fixture"}]
    assert filtered["_filtered"] == summary
