from __future__ import annotations

from backend.app.billing.catalog import _PRICE_SPECS
from scripts.seed_pricing_catalog import PLANS, PRODUCTS, REGIONS


def test_seed_catalog_contains_expected_idempotent_dimensions() -> None:
    assert len(PRODUCTS) == 3
    assert len(_PRICE_SPECS) == 18
    assert len({(product, currency, amount) for product, _mode, currency, amount in _PRICE_SPECS}) == 18
    assert REGIONS == {"CN": "CNY", "JP": "JPY", "US": "USD", "TW": "TWD", "HK": "HKD", "SG": "SGD", "MO": "HKD"}
    assert set(PLANS) == {"free", "c_plus", "b_data_pro"}


def test_seed_script_uses_conflict_or_not_exists_guards() -> None:
    source = open("scripts/seed_pricing_catalog.py", encoding="utf-8").read()
    assert "on conflict (product_code) do nothing" in source
    assert "where not exists" in source
