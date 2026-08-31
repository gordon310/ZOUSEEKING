from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from backend.app.billing.catalog import PriceCatalog, PriceUnavailable
from backend.app.billing.ports import InternalActor, RefundCandidate
from backend.app.billing.service import (
    BillingService,
    ForbiddenBillingOperation,
    PermanentBillingError,
    RefundNotEligible,
    RetryPolicy,
    TransientBillingError,
)
from conftest import FIXED_NOW, OTHER_USER_ID, SECRET, TEST_USER_ID


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
    body = json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": event_type,
            "created": int(FIXED_NOW.timestamp()),
            "data": {"object": event_object},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    signed = str(int(FIXED_NOW.timestamp())).encode("ascii") + b"." + body
    digest = hmac.new(SECRET.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return body, f"t={int(FIXED_NOW.timestamp())},v1={digest}"


@pytest.fixture
def billing_service(fake_gateway, fake_store) -> BillingService:
    return BillingService(
        catalog=PriceCatalog(PRICE_IDS),
        gateway=fake_gateway,
        store=fake_store,
        webhook_secret=SECRET,
        success_url="https://app.test/billing/success",
        cancel_url="https://app.test/billing/cancel",
        portal_return_url="https://app.test/billing",
    )


def test_checkout_reuses_existing_customer_and_server_owned_subscription_metadata(
    billing_service, fake_gateway
) -> None:
    result = billing_service.create_checkout(
        TEST_USER_ID,
        "ignored@example.com",
        "c_plus_monthly",
        "JP",
        now=FIXED_NOW,
    )

    params = fake_gateway.checkout_calls[0]
    assert result.mode == "subscription"
    assert params["customer"] == "cus_existing"
    assert "customer_email" not in params
    assert params["line_items"] == [{"price": "price_test_cplus_jpy", "quantity": 1}]
    assert params["metadata"] == {
        "user_id": str(TEST_USER_ID),
        "subject_id": str(TEST_USER_ID),
        "product_code": "c_plus_monthly",
        "price_version": "v1-2026-08",
        "billing_region": "JP",
    }
    assert params["subscription_data"]["metadata"] == params["metadata"]


def test_checkout_uses_authenticated_email_only_when_customer_does_not_exist(
    billing_service, fake_gateway
) -> None:
    result = billing_service.create_checkout(
        TEST_USER_ID,
        "member@example.com",
        "risk_report_single",
        "CN",
        now=FIXED_NOW,
    )

    params = fake_gateway.checkout_calls[0]
    assert result.mode == "payment"
    assert params["customer_email"] == "member@example.com"
    assert params["mode"] == "payment"
    assert params["allow_promotion_codes"] is True


def test_checkout_cannot_select_an_unapproved_price_or_currency(
    billing_service,
) -> None:
    with pytest.raises(PriceUnavailable):
        billing_service.create_checkout(TEST_USER_ID, "member@example.com", "unknown", "CN", now=FIXED_NOW)
    with pytest.raises(PriceUnavailable):
        billing_service.create_checkout(TEST_USER_ID, "member@example.com", "c_plus_monthly", "HK", now=FIXED_NOW)


def test_portal_uses_store_owned_customer_and_return_url(billing_service, fake_gateway) -> None:
    result = billing_service.create_portal(TEST_USER_ID)

    assert result.url.endswith("bps_test_123")
    assert fake_gateway.portal_calls == [("cus_existing", "https://app.test/billing")]


def test_webhook_duplicate_event_is_processed_once(billing_service, fake_store) -> None:
    body, header = signed_event("evt_duplicate", "invoice.paid", {"id": "in_123", "customer": "cus_existing"})

    first = billing_service.handle_webhook(body, header, now=FIXED_NOW)
    second = billing_service.handle_webhook(body, header, now=FIXED_NOW)

    assert (first.status, first.duplicate) == ("processed", False)
    assert (second.status, second.duplicate) == ("duplicate", True)
    assert fake_store.processed_events == ["evt_duplicate"]


def test_webhook_in_progress_event_is_retryable_not_acknowledged(
    billing_service, fake_store
) -> None:
    body, header = signed_event("evt_in_progress", "invoice.paid", {"id": "in_progress"})
    fake_store.events["evt_in_progress"] = {"state": "in_progress", "attempt_count": 1}

    with pytest.raises(TransientBillingError):
        billing_service.handle_webhook(body, header, now=FIXED_NOW)

    assert fake_store.processed_events == []
    assert fake_store.failed_events == []


def test_webhook_rejects_a_non_mapping_event_object_as_permanent(
    billing_service, fake_store
) -> None:
    body, header = signed_event("evt_malformed_object", "invoice.paid", "not-an-object")

    with pytest.raises(PermanentBillingError):
        billing_service.handle_webhook(body, header, now=FIXED_NOW)

    assert fake_store.failed_events[0]["failure_class"] == "permanent"
    assert fake_store.processed_events == []


def test_webhook_transient_failure_is_recorded_and_replay_succeeds(
    billing_service, fake_store
) -> None:
    fake_store.fail_event_once = True
    body, header = signed_event("evt_retry", "invoice.paid", {"id": "in_retry", "customer": "cus_existing"})

    with pytest.raises(TransientBillingError):
        billing_service.handle_webhook(body, header, now=FIXED_NOW)

    assert fake_store.failed_events[0]["failure_class"] == "transient"
    result = billing_service.handle_webhook(body, header, now=FIXED_NOW + timedelta(seconds=6))

    assert result.status == "processed"
    assert fake_store.processed_events == ["evt_retry"]


def test_failed_invoice_updates_status_and_enqueues_one_dunning_action(
    billing_service, fake_store
) -> None:
    body, header = signed_event(
        "evt_failed_invoice",
        "invoice.payment_failed",
        {"id": "in_failed", "customer": "cus_existing", "subscription": "sub_test_123"},
    )

    billing_service.handle_webhook(body, header, now=FIXED_NOW)

    assert fake_store.status.subscription_status == "past_due"
    assert fake_store.status.entitlement_active is False
    assert [(item.kind, item.dedupe_key) for item in fake_store.outbox] == [
        ("billing.dunning", "dunning:evt_failed_invoice")
    ]


def test_unknown_webhook_is_acknowledged_without_provider_side_effects(
    billing_service, fake_store
) -> None:
    body, header = signed_event("evt_unknown", "product.created", {"id": "prod_123"})

    result = billing_service.handle_webhook(body, header, now=FIXED_NOW)

    assert (result.status, result.ignored) == ("ignored", True)
    assert fake_store.processed_events == ["evt_unknown"]
    assert fake_store.audits[0].action == "billing.event.ignored"


def test_cancel_is_at_period_end_and_repeated_request_is_idempotent(
    billing_service, fake_gateway, fake_store
) -> None:
    first = billing_service.request_cancel(TEST_USER_ID)
    second = billing_service.request_cancel(TEST_USER_ID)

    assert first.at_period_end is True
    assert second.at_period_end is True
    assert fake_gateway.cancel_calls == [("sub_test_123", True)]
    assert fake_store.subscription.cancel_at_period_end is True


def test_refund_request_requires_unused_payment_within_48_hours(
    billing_service, fake_store
) -> None:
    payment_id = "pi_unused"
    fake_store.refund_candidates[payment_id] = RefundCandidate(
        request_id=f"{TEST_USER_ID}:refund-1",
        payment_intent_id=payment_id,
        charged_at=FIXED_NOW - timedelta(hours=47),
        used_entitlement=False,
        currency="JPY",
        amount_minor=990,
    )

    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
    duplicate = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)

    assert request.status == "requested"
    assert duplicate.request_id == request.request_id


@pytest.mark.parametrize(
    "charged_at,used_entitlement",
    [
        (FIXED_NOW - timedelta(hours=49), False),
        (FIXED_NOW - timedelta(hours=1), True),
    ],
)
def test_refund_request_rejects_expired_or_used_payment(
    billing_service, fake_store, charged_at, used_entitlement
) -> None:
    payment_id = f"pi_{int(charged_at.timestamp())}_{used_entitlement}"
    fake_store.refund_candidates[payment_id] = RefundCandidate(
        request_id=f"{TEST_USER_ID}:{payment_id}",
        payment_intent_id=payment_id,
        charged_at=charged_at,
        used_entitlement=used_entitlement,
        currency="JPY",
        amount_minor=990,
    )

    with pytest.raises(RefundNotEligible):
        billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)


def test_refund_request_rejects_a_payment_that_is_not_still_eligible(
    billing_service, fake_store
) -> None:
    payment_id = "pi_already_refunded"
    fake_store.refund_candidates[payment_id] = RefundCandidate(
        request_id=f"{TEST_USER_ID}:{payment_id}",
        payment_intent_id=payment_id,
        charged_at=FIXED_NOW - timedelta(hours=1),
        used_entitlement=False,
        currency="JPY",
        amount_minor=990,
        status="succeeded",
    )

    with pytest.raises(RefundNotEligible):
        billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)


def test_refund_request_cannot_cross_user_ownership_boundary(billing_service, fake_store) -> None:
    payment_id = "pi_other_user"
    fake_store.refund_candidates[payment_id] = RefundCandidate(
        request_id=f"{TEST_USER_ID}:{payment_id}",
        payment_intent_id=payment_id,
        charged_at=FIXED_NOW - timedelta(hours=1),
        used_entitlement=False,
        currency="JPY",
        amount_minor=990,
    )

    with pytest.raises(RefundNotEligible):
        billing_service.request_refund(OTHER_USER_ID, payment_id, now=FIXED_NOW)


def test_refund_approval_requires_finance_and_redacts_audit(
    billing_service, fake_store, fake_gateway
) -> None:
    payment_id = "pi_approve"
    fake_store.refund_candidates[payment_id] = RefundCandidate(
        request_id=f"{TEST_USER_ID}:refund-approve",
        payment_intent_id=payment_id,
        charged_at=FIXED_NOW - timedelta(hours=1),
        used_entitlement=False,
        currency="JPY",
        amount_minor=990,
    )
    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)

    with pytest.raises(ForbiddenBillingOperation):
        billing_service.approve_refund(
            InternalActor(TEST_USER_ID, ("member",)), request.request_id, "member@example.com duplicate", now=FIXED_NOW
        )

    approved = billing_service.approve_refund(
        InternalActor(TEST_USER_ID, ("finance",)), request.request_id, "member@example.com duplicate", now=FIXED_NOW
    )

    assert approved.status == "succeeded"
    assert fake_gateway.refund_calls == [(payment_id, "[redacted-email] duplicate")]
    assert all("member@example.com" not in str(record.metadata) for record in fake_store.audits)


def test_refund_provider_timeout_is_retryable_without_premature_success(
    billing_service, fake_store, fake_gateway
) -> None:
    payment_id = "pi_retry_refund"
    fake_store.refund_candidates[payment_id] = RefundCandidate(
        request_id=f"{TEST_USER_ID}:refund-retry",
        payment_intent_id=payment_id,
        charged_at=FIXED_NOW - timedelta(hours=1),
        used_entitlement=False,
        currency="JPY",
        amount_minor=990,
    )
    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
    fake_gateway.fail_refund_once = True

    with pytest.raises(TransientBillingError):
        billing_service.approve_refund(
            InternalActor(TEST_USER_ID, ("finance",)), request.request_id, "duplicate", now=FIXED_NOW
        )

    assert fake_store.refund_requests[request.request_id].status == "requested"
    assert len(fake_store.refund_retries) == 1


def test_retry_policy_is_bounded_and_deterministic() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=5, max_delay_seconds=20)

    assert policy.next_retry_at(1, FIXED_NOW) == FIXED_NOW + timedelta(seconds=5)
    assert policy.next_retry_at(2, FIXED_NOW) == FIXED_NOW + timedelta(seconds=10)
    assert policy.next_retry_at(3, FIXED_NOW) is None
