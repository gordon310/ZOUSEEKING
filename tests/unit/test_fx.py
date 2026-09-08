"""Tests for fx conversion service and report integration (D5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.intake.fx import convert_jpy, fx_provenance, load_fx
from backend.app.intake.market_engine import (
    build_sale_report,
    load_snapshots,
    match_snapshot,
)

REPO = Path(__file__).resolve().parents[2]


def test_fx_snapshot_is_dated_and_sourced():
    fx = load_fx()
    assert fx is not None
    assert fx["as_of"] and fx["source"]  # type: ignore[index]
    assert fx["rates"]["CNY"] > 0 and fx["rates"]["USD"] > 0  # type: ignore[index]
    prov = fx_provenance()
    assert prov["as_of"] and prov["version"]  # type: ignore[index]


def test_convert_jpy_roundtrip_magnitudes():
    # 100 JPY = 4.3098 CNY central parity snapshot -> 10,000 JPY ~ 431 CNY
    cny = convert_jpy(10_000, "CNY")
    assert cny is not None
    assert cny["currency"] == "CNY"
    assert cny["amount"] == 431  # 10_000 * 0.043098 = 430.98
    assert cny["as_of"] and cny["source"]
    usd = convert_jpy(10_000, "USD")
    assert usd is not None and usd["amount"] == 64  # 10_000 * 0.006357 = 63.57


def test_convert_missing_or_unknown_returns_none():
    assert convert_jpy(None, "CNY") is None
    assert convert_jpy(100, "EUR") is None


def test_report_rows_carry_cny_usd_and_fx_provenance():
    snapshots = load_snapshots(REPO / "data" / "collected")
    row = match_snapshot(snapshots, "东京都", "渋谷区", "塔楼")
    assert row is not None
    report = build_sale_report(row, {"prefecture": "东京都", "ward": "渋谷区", "asset_type": "塔楼"})
    sale_row = report["sale"][0]
    assert sale_row["amount_yen"] > 0
    assert sale_row.get("amount_cny") and sale_row["amount_cny"] > 0
    assert sale_row.get("amount_usd") and sale_row["amount_usd"] > 0
    # provenance rides in raw_record, not duplicated per row
    fx = report["raw_record"].get("fx")
    assert fx and fx["as_of"] and fx["rates"]["CNY"]
    # spot check: 1LDK 10,257 man-yen = 102,570,000 JPY -> CNY
    one_ldk = next(r for r in report["sale"] if r["layout"] == "1LDK")
    assert abs(one_ldk["amount_cny"] - round(102_570_000 * fx["rates"]["CNY"])) <= 1
