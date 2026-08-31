from __future__ import annotations

import pytest

from backend.app.billing.catalog import PriceCatalog, PriceUnavailable


PRICE_IDS = {
    "risk_report_single:CNY": "price_test_risk_cny",
    "risk_report_single:JPY": "price_test_risk_jpy",
    "risk_report_single:USD": "price_test_risk_usd",
    "c_plus_monthly:CNY": "price_test_cplus_cny",
    "c_plus_monthly:JPY": "price_test_cplus_jpy",
    "c_plus_monthly:USD": "price_test_cplus_usd",
    "b_data_pro_monthly:CNY": "price_test_bpro_cny",
    "b_data_pro_monthly:JPY": "price_test_bpro_jpy",
    "b_data_pro_monthly:USD": "price_test_bpro_usd",
}


def test_catalog_keeps_currency_minor_units_and_checkout_mode() -> None:
    catalog = PriceCatalog(PRICE_IDS)

    cny = catalog.resolve("c_plus_monthly", "CN")
    jpy = catalog.resolve("b_data_pro_monthly", "JP")
    usd = catalog.resolve("risk_report_single", "US")

    assert (cny.currency, cny.amount_minor, cny.mode) == ("CNY", 4900, "subscription")
    assert (jpy.currency, jpy.amount_minor, jpy.mode) == ("JPY", 3999, "subscription")
    assert (usd.currency, usd.amount_minor, usd.mode) == ("USD", 99, "payment")


def test_catalog_rejects_unknown_product_and_client_currency_switch() -> None:
    catalog = PriceCatalog(PRICE_IDS)

    with pytest.raises(PriceUnavailable):
        catalog.resolve("unknown_product", "CN")
    with pytest.raises(PriceUnavailable):
        catalog.resolve("c_plus_monthly", "CN", currency="USD")


def test_catalog_does_not_sell_unpublished_region_without_local_price() -> None:
    catalog = PriceCatalog(PRICE_IDS)

    with pytest.raises(PriceUnavailable):
        catalog.resolve("c_plus_monthly", "HK")


def test_catalog_marks_missing_server_price_id_unavailable() -> None:
    catalog = PriceCatalog({"c_plus_monthly:CNY": ""})

    item = next(item for item in catalog.list_public() if item["product_code"] == "c_plus_monthly")
    assert item["available"] is False
    with pytest.raises(PriceUnavailable):
        catalog.resolve("c_plus_monthly", "CN")


def test_catalog_public_rows_are_safe_to_render_without_provider_identifiers() -> None:
    catalog = PriceCatalog(PRICE_IDS)

    rows = catalog.list_public()

    assert rows
    assert all("stripe_price_id" not in row for row in rows)
    assert all(set(row) == {"product_code", "price_version", "currency", "amount_minor", "mode", "available"} for row in rows)
