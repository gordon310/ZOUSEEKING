"""Stripe HTTP gateway (standard-library urllib; no third-party deps)."""

from __future__ import annotations

import asyncio
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from .ports import (
    CheckoutSessionResult,
    PortalSessionResult,
    RefundResult,
    StripeGateway,
)


class BillingGatewayError(Exception):
    """An error returned by the payment provider or its HTTP transport."""


class StripeHttpGateway(StripeGateway):
    def __init__(self, secret_key: str, *, timeout: float = 30.0) -> None:
        self._api_base = "https://api.stripe.com/v1"
        self._auth = base64.b64encode(f"{secret_key}:".encode()).decode()
        self._timeout = timeout
        self._urlopen = urllib.request.urlopen

    async def _request(
        self, method: str, path: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        body = urllib.parse.urlencode(params) if params else None
        request = urllib.request.Request(
            f"{self._api_base}{path}",
            data=body.encode() if body else None,
            method=method,
        )
        request.add_header("Authorization", f"Basic {self._auth}")
        if body:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            response = await asyncio.to_thread(self._urlopen, request, timeout=self._timeout)
            payload = response.read()
        except urllib.error.HTTPError as exc:
            message = self._error_message(exc)
            raise BillingGatewayError(f"{exc.code}: {message}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise BillingGatewayError() from exc

        try:
            data = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise BillingGatewayError("invalid JSON response") from exc
        if not isinstance(data, dict):
            raise BillingGatewayError("invalid JSON response")
        return data

    @staticmethod
    def _error_message(error: urllib.error.HTTPError) -> str:
        try:
            payload = json.loads(error.read())
            return str(payload.get("error", {}).get("message", "provider request failed"))
        except (TypeError, ValueError, AttributeError):
            return "provider request failed"

    async def create_checkout_session(
        self, params: Mapping[str, Any]
    ) -> CheckoutSessionResult:
        data = await self._request("POST", "/checkout/sessions", dict(params))
        return CheckoutSessionResult(session_id=data["id"], url=data["url"])

    async def create_portal_session(
        self, customer_id: str, return_url: str
    ) -> PortalSessionResult:
        data = await self._request(
            "POST",
            "/billing_portal/sessions",
            {"customer": customer_id, "return_url": return_url},
        )
        return PortalSessionResult(url=data["url"])

    async def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
        path = f"/subscriptions/{urllib.parse.quote(subscription_id, safe='')}"
        path += "?" + urllib.parse.urlencode({"at_period_end": str(at_period_end).lower()})
        await self._request("DELETE", path)

    async def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
        data = await self._request(
            "POST",
            "/refunds",
            {"payment_intent": payment_intent_id, "reason": reason},
        )
        return RefundResult(refund_id=data["id"], status=data["status"])
