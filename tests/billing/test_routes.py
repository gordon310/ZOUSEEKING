from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.billing.catalog import PriceCatalog
from backend.app.billing.routes import get_billing_service
from backend.app.billing.service import BillingService
from backend.app.main import app
from conftest import FIXED_NOW, SECRET, TEST_USER_ID


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


def signed_event(event_id: str, event_type: str, event_object: dict) -> tuple[bytes, str]:
    timestamp = int(datetime.now(timezone.utc).timestamp())
    body = json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": event_type,
            "created": timestamp,
            "data": {"object": event_object},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hmac.new(SECRET.encode(), str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return body, f"t={timestamp},v1={digest}"


@pytest.fixture
def route_context(fake_gateway, fake_store):
    service = BillingService(
        catalog=PriceCatalog(PRICE_IDS),
        gateway=fake_gateway,
        store=fake_store,
        webhook_secret=SECRET,
        success_url="https://app.test/billing/success",
        cancel_url="https://app.test/billing/cancel",
        portal_return_url="https://app.test/billing",
    )
    app.dependency_overrides[require_user] = lambda: AuthUser(TEST_USER_ID, "member@example.com", "测试用户")
    app.dependency_overrides[get_billing_service] = lambda: service
    client = TestClient(app)
    yield client, service, fake_gateway, fake_store
    app.dependency_overrides.clear()


def test_billing_route_is_disabled_without_explicit_service_configuration() -> None:
    app.dependency_overrides[require_user] = lambda: AuthUser(TEST_USER_ID, "member@example.com", "测试用户")
    try:
        response = TestClient(app).post(
            "/api/billing/checkout",
            json={"product_code": "c_plus_monthly", "billing_region": "JP"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "billing is not configured"}


def test_public_prices_expose_confirmed_amounts_without_provider_identifiers() -> None:
    response = TestClient(app).get("/api/billing/prices")

    assert response.status_code == 200
    cny_cplus = next(
        row
        for row in response.json()
        if row["product_code"] == "c_plus_monthly" and row["currency"] == "CNY"
    )
    assert cny_cplus["amount_minor"] == 4900
    assert cny_cplus["available"] is False
    assert all("stripe_price_id" not in row for row in response.json())


def test_checkout_rejects_client_owned_price_amount_currency_and_redirect_fields(route_context) -> None:
    client, _service, gateway, _store = route_context

    response = client.post(
        "/api/billing/checkout",
        json={
            "product_code": "c_plus_monthly",
            "billing_region": "JP",
            "price_id": "price_attacker",
            "amount_minor": 1,
            "currency": "USD",
            "success_url": "https://attacker.test",
        },
    )

    assert response.status_code == 422
    assert gateway.checkout_calls == []


def test_authenticated_routes_return_server_owned_checkout_portal_status_and_cancel(route_context) -> None:
    client, _service, gateway, store = route_context

    checkout = client.post(
        "/api/billing/checkout",
        json={"product_code": "c_plus_monthly", "billing_region": "JP"},
    )
    portal = client.post("/api/billing/portal")
    status = client.get("/api/billing/status")
    cancel = client.post("/api/billing/cancel")

    assert checkout.status_code == 200
    assert checkout.json()["session_id"] == "cs_test_123"
    assert portal.status_code == 200
    assert portal.json()["url"].endswith("bps_test_123")
    assert status.status_code == 200
    assert status.json()["subscription_status"] == "active"
    assert cancel.status_code == 200
    assert cancel.json()["at_period_end"] is True
    assert gateway.portal_calls == [("cus_existing", "https://app.test/billing")]
    assert store.subscription.cancel_at_period_end is True


def test_webhook_reads_raw_body_invalid_signature_is_400_and_valid_duplicate_is_200(route_context) -> None:
    client, _service, _gateway, store = route_context
    body, header = signed_event("evt_route", "invoice.paid", {"id": "in_route", "customer": "cus_existing"})

    invalid = client.post(
        "/api/billing/webhook",
        content=body,
        headers={"Stripe-Signature": header[:-2] + "00"},
    )
    first = client.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": header})
    duplicate = client.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": header})

    assert invalid.status_code == 400
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json() == {"status": "duplicate", "event_id": "evt_route", "duplicate": True, "ignored": False}
    assert store.processed_events == ["evt_route"]


def test_webhook_transient_processing_error_returns_generic_500(route_context) -> None:
    client, _service, _gateway, store = route_context
    store.fail_event_once = True
    body, header = signed_event("evt_route_retry", "invoice.paid", {"id": "in_retry", "customer": "cus_existing"})

    response = client.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": header})

    assert response.status_code == 500
    assert response.json() == {"detail": "billing service temporarily unavailable"}
    assert "database" not in response.text


def test_webhook_claim_failure_returns_generic_500_without_internal_error(route_context) -> None:
    client, _service, _gateway, store = route_context
    store.fail_claim_once = True
    body, header = signed_event("evt_claim_failure", "invoice.paid", {"id": "in_claim", "customer": "cus_existing"})

    response = client.post("/api/billing/webhook", content=body, headers={"Stripe-Signature": header})

    assert response.status_code == 500
    assert response.json() == {"detail": "billing service temporarily unavailable"}
    assert "claim" not in response.text
