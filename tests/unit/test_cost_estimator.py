"""Tests for acquisition-cost estimation (dated sourced rules, no hard-coded rates)."""

from __future__ import annotations

import pytest

from backend.app.intake.completeness import FieldValue, build_free_preview
from backend.app.intake.cost_estimator import estimate_acquisition_costs, load_rules


def _ask(value) -> dict[str, FieldValue]:
    return {
        "asking_price_jpy": FieldValue(
            value=value,
            confirmation_status="confirmed",
            confidence="high",
            has_evidence=True,
        )
    }


def test_rules_file_has_version_and_sources():
    rules = load_rules()
    assert rules["version"]
    assert rules["effective_from"]
    assert rules["sources"], "rules must cite sources (AGENTS dated/verifiable)"
    assert all(s["url"] for s in rules["sources"])


def test_5000man_broker_and_stamp():
    # 5,000万JPY asking: broker 3% + 6万 = 156万; stamp band 1,000万超5,000万 = 2万
    result = estimate_acquisition_costs(_ask("50,000,000"))
    assert result["status"] == "partial"
    items = {i["item"]: i for i in result["items"]}
    assert items["中介手续费"]["estimated_jpy"] == 1_560_000
    assert items["印花税"]["estimated_jpy"] == 20_000
    assert result["estimated_total_jpy"] == 1_580_000
    assert items["不动产取得税"]["status"] == "needs_input"
    assert result["calculation_version"].startswith("acquisition-cost-")


def test_300man_uses_lower_tiers():
    # 300万: broker 4%+2万 = 14万; stamp band 100万超500万 = 2千
    result = estimate_acquisition_costs(_ask(3_000_000))
    items = {i["item"]: i for i in result["items"]}
    assert items["中介手续费"]["estimated_jpy"] == 140_000
    assert items["印花税"]["estimated_jpy"] == 2_000


def test_150man_uses_5pct_tier():
    result = estimate_acquisition_costs(_ask(1_500_000))
    items = {i["item"]: i for i in result["items"]}
    assert items["中介手续费"]["estimated_jpy"] == 75_000
    assert items["印花税"]["estimated_jpy"] == 2_000


def test_missing_asking_price_is_honest():
    result = estimate_acquisition_costs({})
    assert result["status"] == "insufficient_input"
    assert result["estimated_total_jpy"] is None
    assert all(i["status"] == "needs_input" for i in result["items"])


def test_build_free_preview_integrates_estimator():
    from typing import Any, cast

    preview = build_free_preview(_ask("50,000,000"))
    costs = cast(dict[str, Any], preview["acquisition_costs"])
    assert costs["status"] == "partial"
    assert costs["estimated_total_jpy"] == 1_580_000
    assert costs["items"], "item list must no longer be an empty placeholder"
