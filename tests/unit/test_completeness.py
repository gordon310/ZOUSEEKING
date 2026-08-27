from backend.app.intake.completeness import FieldValue, build_free_preview, calculate_completeness


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

    assert preview["acquisition_costs"]["status"] == "rules_not_loaded"
    assert preview["acquisition_costs"]["estimated_total_jpy"] is None
    assert "不动产取得税" in preview["acquisition_costs"]["items"]
    assert preview["comparable_status"] == "not_checked"


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
