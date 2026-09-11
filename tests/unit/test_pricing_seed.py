from __future__ import annotations

from backend.app.billing.catalog import _PRICE_SPECS
from scripts.seed_pricing_catalog import PLANS, PRODUCTS, REGIONS, legacy_values


def test_seed_catalog_contains_expected_idempotent_dimensions() -> None:
    assert len(PRODUCTS) == 3
    assert len(_PRICE_SPECS) == 18
    assert len({(product, currency, amount) for product, _mode, currency, amount in _PRICE_SPECS}) == 18
    assert REGIONS == {"CN": "CNY", "JP": "JPY", "US": "USD", "TW": "TWD", "HK": "HKD", "SG": "SGD", "MO": "HKD"}
    assert set(PLANS) == {"free_c", "c_plus", "free_b", "b_data_pro"}
    assert PLANS["free_c"]["entitlements"][("query", "day")] == 3
    assert PLANS["free_b"]["entitlements"][("stats_query", "month")] == 5


def test_seed_uses_null_for_unconfigured_monthly_legacy_columns() -> None:
    assert legacy_values(PLANS["free_c"]) == (None, None, None, None)
    assert legacy_values(PLANS["c_plus"]) == (100, 12, 3, None)


def test_seed_script_uses_conflict_or_not_exists_guards() -> None:
    source = open("scripts/seed_pricing_catalog.py", encoding="utf-8").read()
    assert "on conflict (product_code) do nothing" in source
    assert "where not exists" in source
    assert "on conflict (plan_code,metric,period) where active" in source
    assert "monthly_query_limit=excluded.monthly_query_limit" in source
    assert "export_rows_monthly=excluded.export_rows_monthly" in source
