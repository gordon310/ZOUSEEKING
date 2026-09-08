"""Tests for the market data engine (numeric report path, D6a sale-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.intake.market_engine import (
    LAYOUTS,
    MAN_YEN_TO_YEN,
    build_sale_report,
    load_snapshots,
    match_snapshot,
)

REPO = Path(__file__).resolve().parents[2]

# Pinned copies of the collected ward snapshots (data/collected/*_sources.json is
# gitignored runtime data and does not exist in CI; tests must run on committed
# deterministic fixtures, per AGENTS.md analytics-fixture rule).
FIXTURE_DIR = REPO / "tests" / "fixtures" / "market_snapshots"


@pytest.fixture(scope="module")
def snapshots():
    return load_snapshots(FIXTURE_DIR)


def test_loads_all_family_snapshots(snapshots):
    # 23ku + Osaka 23 + Yokohama 18 ward-level numeric snapshots
    assert len(snapshots) >= 64
    families = {s.family for s in snapshots}
    assert families == {"jphouse_23ku", "jphouse_osaka_wards", "jphouse_yokohama_wards"}
    for s in snapshots:
        assert set(LAYOUTS) <= set(s.rents)
        assert s.sale_period  # data period must be present (provenance)


def test_match_shibuya_sale_numerics(snapshots):
    row = match_snapshot(snapshots, "东京都", "渋谷区", "塔楼")
    assert row is not None
    assert row.family == "jphouse_23ku"
    # 1LDK layout price 10,257 man-yen -> yen
    assert row.layout_amount_yen("1LDK") == 10_257 * MAN_YEN_TO_YEN
    # unit 198.6079 man-yen/sqm -> yen/sqm
    assert row.unit_yen_per_sqm == round(198.6079 * MAN_YEN_TO_YEN)


def test_match_gates_asset_and_coverage(snapshots):
    assert match_snapshot(snapshots, "东京都", "渋谷区", "一户建") is None
    assert match_snapshot(snapshots, "东京都", "渋谷区", None) is not None
    # ward outside the three covered families
    assert match_snapshot(snapshots, "东京都", "三鹰市", "塔楼") is None
    assert match_snapshot(snapshots, "冲绳县", "那霸市", "塔楼") is None


def test_report_is_sale_only_and_numeric(snapshots):
    row = match_snapshot(snapshots, "大阪府", "北区", "塔楼")
    assert row is not None
    report = build_sale_report(row, {"prefecture": "大阪府", "city": "大阪市", "ward": "北区", "asset_type": "塔楼", "year": 2026, "month": 8})
    # D6a: rental side empty (SUUMO rents not licensed for display)
    assert report["rental"] == []
    assert report["sale"], "sale rows must exist for a covered ward"
    sale_row = report["sale"][0]
    assert sale_row["data_class"] == "scraped_aggregate"
    assert isinstance(sale_row["amount_yen"], int)
    assert sale_row["amount_yen"] > 0
    assert isinstance(sale_row["unit_yen_per_sqm"], (int, float))
    assert sale_row["period"]
    # no SUUMO/rents leakage into the emitted report
    text = (report["markdown"] + " " + str(report["data_sources"]) + " " + str(report["summary"])).lower()
    assert "suumo" not in text
    assert "待授权" in report["summary"]["note"] or "租金" in report["summary"]["note"]


def test_out_of_coverage_report_is_none(snapshots):
    assert match_snapshot(snapshots, "东京都", "三鹰市", "塔楼") is None


def test_markdown_carries_fx_provenance_note(snapshots):
    row = match_snapshot(snapshots, "东京都", "渋谷区", "塔楼")
    assert row is not None
    report = build_sale_report(row, {"prefecture": "东京都", "ward": "渋谷区", "asset_type": "塔楼"})
    assert "汇率参考(" in report["markdown"]
    assert "人民币/美元换算仅作显示参考" in report["markdown"]
