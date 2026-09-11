from __future__ import annotations

import pytest

from backend.app.billing.catalog import PRICE_VERSION, PriceCatalog, PriceUnavailable


PRICE_IDS = {
    "risk_report_single:CNY": "price_test_risk_cny",
    "risk_report_single:JPY": "price_test_risk_jpy",
    "risk_report_single:USD": "price_test_risk_usd",
    "risk_report_single:TWD": "price_test_risk_twd",
    "risk_report_single:HKD": "price_test_risk_hkd",
    "risk_report_single:SGD": "price_test_risk_sgd",
    "c_plus_monthly:CNY": "price_test_cplus_cny",
    "c_plus_monthly:JPY": "price_test_cplus_jpy",
    "c_plus_monthly:USD": "price_test_cplus_usd",
    "c_plus_monthly:TWD": "price_test_cplus_twd",
    "c_plus_monthly:HKD": "price_test_cplus_hkd",
    "c_plus_monthly:SGD": "price_test_cplus_sgd",
    "b_data_pro_monthly:CNY": "price_test_bpro_cny",
    "b_data_pro_monthly:JPY": "price_test_bpro_jpy",
    "b_data_pro_monthly:USD": "price_test_bpro_usd",
    "b_data_pro_monthly:TWD": "price_test_bpro_twd",
    "b_data_pro_monthly:HKD": "price_test_bpro_hkd",
    "b_data_pro_monthly:SGD": "price_test_bpro_sgd",
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

    assert catalog.resolve("risk_report_single", "TW").amount_minor == 3000
    assert catalog.resolve("c_plus_monthly", "HK").amount_minor == 8000
    assert catalog.resolve("b_data_pro_monthly", "SG").amount_minor == 6000
    assert catalog.resolve("risk_report_single", "MO").currency == "HKD"


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


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


class _PricingConnection:
    def __init__(self, broken=False):
        self.calls = 0
        self.broken = broken

    async def fetch(self, sql):
        self.calls += 1
        if self.broken:
            raise RuntimeError("db unavailable")
        if "pricing_products" in sql and "pricing_prices" not in sql:
            return [{"product_code": "c_plus_monthly", "mode": "subscription", "active": True}]
        if "pricing_regions" in sql:
            return [{"region_code": "CN", "currency": "CNY"}]
        if "pricing_prices" in sql:
            return [{"product_code": "c_plus_monthly", "currency": "CNY", "amount_minor": 5000, "stripe_price_id": "price_db", "price_version": 2, "active": True, "mode": "subscription"}]
        return [{"plan_code": "c_plus", "name": "C Plus", "monthly_query_limit": 100, "monthly_report_quota": 12, "subscription_slots": 3, "export_rows_monthly": 0}]


@pytest.mark.asyncio
async def test_catalog_prefers_db_snapshot_and_reuses_ttl_cache() -> None:
    connection = _PricingConnection()
    catalog = PriceCatalog(PRICE_IDS, pool=_Pool(connection), cache_ttl=60)

    await catalog.ensure_loaded()
    first = catalog.resolve("c_plus_monthly", "CN")
    await catalog.ensure_loaded()

    assert (first.amount_minor, first.price_version, first.stripe_price_id) == (5000, "2", "price_db")
    assert connection.calls == 4


@pytest.mark.asyncio
async def test_catalog_falls_back_when_db_is_empty_or_unavailable() -> None:
    catalog = PriceCatalog(PRICE_IDS, pool=_Pool(_PricingConnection(broken=True)))

    await catalog.ensure_loaded()

    assert catalog.resolve("risk_report_single", "CN").amount_minor == 500
    assert catalog.resolve("risk_report_single", "CN").price_version == PRICE_VERSION
