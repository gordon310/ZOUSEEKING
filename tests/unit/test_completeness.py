from pathlib import Path

from backend.app.intake.completeness import FieldValue, build_free_preview, calculate_completeness

REPO = Path(__file__).resolve().parents[2]
# data/collected is gitignored runtime data (absent in CI); the ward snapshots
# pinned in tests/fixtures/market_snapshots/ are SHA-identical committed copies.
SNAPSHOT_FIXTURES = REPO / "tests" / "fixtures" / "market_snapshots"


def test_missing_critical_rights_field_cannot_be_hidden_by_other_fields():
    fields = {
        "building_name": FieldValue("Grand Osaka", "confirmed", "high", True),
        "address": FieldValue("大阪市北区", "confirmed", "high", True),
        "asking_price_jpy": FieldValue(35000000, "confirmed", "high", True),
        "area_sqm": FieldValue(45.2, "confirmed", "high", True),
    }

    result = calculate_completeness(fields)

    assert result["legal_transaction"]["status"] == "insufficient_data"
    assert "land_right" in result["legal_transaction"]["missing_critical"]


def test_preview_lists_cost_items_without_inventing_tax_amounts():
    preview = build_free_preview({
        "asking_price_jpy": FieldValue(35000000, "confirmed", "high", True),
    })

    costs = preview["acquisition_costs"]
    # 3,500万: broker 3%+6万 = 111万; stamp band 1,000万超5,000万 = 2万(principal)
    assert costs["status"] == "partial"  # type: ignore[index]
    assert costs["estimated_total_jpy"] == 1_130_000  # type: ignore[index]
    # items dict-like list preserves the acquisition-cost contract
    items = {i["item"]: i for i in costs["items"]}
    assert "不动产取得税" in items
    # valuation-basis taxes are NOT invented
    assert items["不动产取得税"]["status"] == "needs_input"
    assert items["不动产取得税"]["estimated_jpy"] is None
    # estimated lines carry a basis (sourced, not magic)
    assert "宅建业法" in items["中介手续费"]["basis"]
    # no address in fields -> comparable was not checked
    assert preview["comparable_status"] == "not_checked"
    assert preview["comparable"]["reference"] == []  # type: ignore[index]


def test_preview_comparable_available_for_covered_ward_address():
    from typing import Any, cast

    preview = cast(
        dict[str, Any],
        build_free_preview(
            {
                "asking_price_jpy": FieldValue(50000000, "confirmed", "high", True),
                "address": FieldValue("东京都渋谷区神南1-1", "confirmed", "high", True),
            },
            snapshots_dir=SNAPSHOT_FIXTURES,
        ),
    )
    assert preview["comparable_status"] == "sufficient"
    reference = cast(list[Any], preview["comparable"]["reference"])
    assert reference, "covered ward must return numeric reference rows"
    assert reference[0]["amount_yen"] > 0
    assert reference[0]["data_class"] == "scraped_aggregate"
    # never fabricated: rows come from the collected snapshot with a period
    assert reference[0]["period"]


def test_source_trust_counts_only_evidence_with_reviewable_confidence():
    result = calculate_completeness({
        "building_name": FieldValue("Grand Osaka", "confirmed", "high", True),
        "address": FieldValue("大阪市北区", "confirmed", "low", True),
        "asking_price_jpy": FieldValue(35000000, "confirmed", "medium", True),
        "area_sqm": FieldValue(45.2, "unknown", "high", False),
    })

    assert result["source_trust"]["confirmed"] == 2
    assert result["source_trust"]["total"] == 4
    assert result["source_trust"]["percent"] == 50
