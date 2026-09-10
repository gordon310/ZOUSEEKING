from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from backend.app.billing.gateway import StripeHttpGateway


class StubResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body


def test_create_checkout_session_sends_authenticated_form_request() -> None:
    gateway = StripeHttpGateway("sk_test_secret")
    requests = []

    def urlopen(request, *, timeout):
        requests.append((request, timeout))
        return StubResponse(
            {
                "id": "cs_test_1",
                "url": "https://checkout.stripe.com/c/pay/cs_test_1",
            }
        )

    gateway._urlopen = urlopen

    result = asyncio.run(gateway.create_checkout_session({"mode": "payment", "quantity": 1}))

    assert result.session_id == "cs_test_1"
    assert result.url == "https://checkout.stripe.com/c/pay/cs_test_1"
    request, timeout = requests[0]
    assert request.get_header("Authorization") == "Basic " + base64.b64encode(
        b"sk_test_secret:"
    ).decode()
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert request.data == b"mode=payment&quantity=1"
    assert timeout == 30.0


def test_http_error_includes_stripe_error_message() -> None:
    gateway = StripeHttpGateway("sk_test_secret")

    def urlopen(request, *, timeout):
        raise HTTPError(
            request.full_url,
            402,
            "Payment Required",
            {},
            BytesIO(b'{"error":{"message":"card declined"}}'),
        )

    gateway._urlopen = urlopen

    with pytest.raises(Exception, match="card declined"):
        asyncio.run(gateway.create_portal_session("cus_test", "https://app.test/billing"))


def test_network_error_is_raised_to_service_for_translation() -> None:
    gateway = StripeHttpGateway("sk_test_secret")

    def urlopen(request, *, timeout):
        raise URLError("temporary outage")

    gateway._urlopen = urlopen

    with pytest.raises(Exception):
        asyncio.run(gateway.create_portal_session("cus_test", "https://app.test/billing"))


def test_create_refund_returns_refund_result_and_posts_parameters() -> None:
    gateway = StripeHttpGateway("sk_test_secret")
    requests = []

    def urlopen(request, *, timeout):
        requests.append(request)
        return StubResponse({"id": "re_test_1", "status": "succeeded"})

    gateway._urlopen = urlopen

    result = asyncio.run(gateway.create_refund("pi_test_1", reason="requested_by_customer"))

    assert result.refund_id == "re_test_1"
    assert result.status == "succeeded"
    assert requests[0].full_url == "https://api.stripe.com/v1/refunds"
    assert requests[0].data == b"payment_intent=pi_test_1&reason=requested_by_customer"


def test_cancel_subscription_deletes_with_encoded_id_and_period_flag() -> None:
    gateway = StripeHttpGateway("sk_test_secret")
    requests = []

    def urlopen(request, *, timeout):
        requests.append(request)
        return StubResponse({"id": "sub_test_1"})

    gateway._urlopen = urlopen

    asyncio.run(gateway.cancel_subscription("sub/test 1", at_period_end=True))

    assert requests[0].method == "DELETE"
    assert requests[0].full_url == (
        "https://api.stripe.com/v1/subscriptions/sub%2Ftest%201?at_period_end=true"
    )


def test_create_portal_session_returns_url_and_posts_customer_parameters() -> None:
    gateway = StripeHttpGateway("sk_test_secret")
    requests = []

    def urlopen(request, *, timeout):
        requests.append(request)
        return StubResponse({"url": "https://billing.stripe.com/session/test"})

    gateway._urlopen = urlopen

    result = asyncio.run(gateway.create_portal_session("cus_test", "https://app.test/billing"))

    assert result.url == "https://billing.stripe.com/session/test"
    assert requests[0].full_url == "https://api.stripe.com/v1/billing_portal/sessions"
    assert requests[0].data == b"customer=cus_test&return_url=https%3A%2F%2Fapp.test%2Fbilling"
