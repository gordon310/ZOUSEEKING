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

    assert filtered["collected"] == [
        {
            "ward": "fixture",
            "config": "configs/family/ward.json",
            "sale": {
                "layout_price_man_yen": {"1LDK": 1000},
                "unit_man_yen_per_sqm": 100.0,
                "updated": "official-period",
            },
        }
    ]
    assert set(filtered) == {"collected", "_filtered", "generated_at"}
    assert filtered["_filtered"] == summary
    assert filtered["generated_at"].endswith("Z")
    assert "rents" in filtered["_filtered"]["fields"]
    assert "source_update" in filtered["_filtered"]["fields"]
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

    assert filtered["collected"] == [{"ward": "fixture"}]
    assert filtered["_filtered"] == summary
    assert set(filtered) == {"collected", "_filtered", "generated_at"}


def test_render_markdown_explains_missing_rental_data() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
    import generate_xhs_package as generator

    config = {
        "title": "Fixture report",
        "publish_month": "2026年8月",
        "sections": {
            "rental": {"title": "租房子", "rows": []},
            "sale": {"title": "买房子", "rows": []},
        },
        "summary": {"title": "总而言之", "line": "", "note": ""},
    }

    markdown = generator.render_markdown(config)

    assert "## 租房子" in markdown
    assert "暂无授权租金数据" in markdown
