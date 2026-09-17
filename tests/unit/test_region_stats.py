from backend.app.region_stats import aggregate_region_rows, map_asset_type


def test_maps_mlits_kinds_to_explicit_product_types():
    assert map_asset_type("中古マンション等") == "公寓"
    assert map_asset_type("宅地(土地と建物)") == "独栋"
    assert map_asset_type("宅地(土地)") == "土地"
    assert map_asset_type("未知") is None


def test_aggregates_numeric_unit_prices_with_quartiles_and_buckets():
    result = aggregate_region_rows(
        [{"unit_price_jpy_per_sqm": value} for value in [100_000, 200_000, 300_000, 400_000, 500_000]],
        asset_type="公寓",
        period="2025Q1",
    )
    assert result["sample_size"] == 5
    assert result["mean_unit_price_jpy_per_sqm"] == 300_000
    assert result["median_unit_price_jpy_per_sqm"] == 300_000
    assert result["p25"] == 200_000
    assert result["p75"] == 400_000
    assert result["distribution"] == [
        {"lower": 0, "upper": 250_000, "count": 2},
        {"lower": 250_000, "upper": 500_000, "count": 2},
        {"lower": 500_000, "upper": 1_000_000, "count": 1},
        {"lower": 1_000_000, "upper": None, "count": 0},
    ]


def test_does_not_emit_statistics_below_five_samples():
    result = aggregate_region_rows(
        [{"unit_price_jpy_per_sqm": 123_000}] * 4,
        asset_type="公寓",
        period="2025Q1",
    )
    assert result["status"] == "insufficient_sample"
    assert result["sample_size"] == 4
    assert "median_unit_price_jpy_per_sqm" not in result
    assert "mean_unit_price_jpy_per_sqm" not in result


def test_mean_and_percentiles_share_the_same_valid_positive_source_values():
    result = aggregate_region_rows(
        [{"unit_price_jpy_per_sqm": value} for value in [100_000, 200_000, 300_000, 400_000, 1_000_000, None, 0]],
        asset_type="公寓",
        period="2025Q1",
    )
    assert result["sample_size"] == 5
    assert result["mean_unit_price_jpy_per_sqm"] == 400_000
    assert result["median_unit_price_jpy_per_sqm"] == 300_000
    assert result["p25"] == 200_000
    assert result["p75"] == 400_000


def test_rent_sale_ratio_is_explicitly_unavailable():
    result = aggregate_region_rows([], asset_type="公寓", period="2025Q1")
    assert result["rent_sale_ratio"] == {"available": False, "reason": "租金数据未授权"}
