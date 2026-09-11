"""FastAPI billing boundary with disabled-by-default provider wiring."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth import AuthUser, require_user
from .catalog import PriceCatalog, PriceUnavailable
from .gateway import StripeHttpGateway
from .service import (
    BillingError,
    BillingNotConfigured,
    BillingService,
)
from .signatures import SignatureVerificationError
from .store import PostgresBillingStore


router = APIRouter(prefix="/api/billing", tags=["billing"])
_PUBLIC_CATALOG = PriceCatalog({})


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_code: str = Field(..., min_length=1)
    billing_region: str = Field(..., min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    query_key: Optional[str] = Field(default=None, min_length=1, max_length=500)


class RefundRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_intent_id: str = Field(..., min_length=1, max_length=255)


def get_billing_service() -> BillingService:
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret_key or not webhook_secret:
        raise HTTPException(status_code=503, detail=BillingNotConfigured.public_message)
    try:
        raw_prices = os.getenv("STRIPE_PRICE_IDS", "{}")
        price_ids = json.loads(raw_prices) if raw_prices.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="billing price configuration invalid") from exc
    price_ids = {str(k): str(v) for k, v in price_ids.items()}
    return BillingService(
        catalog=PriceCatalog(price_ids),
        gateway=StripeHttpGateway(secret_key),
        store=PostgresBillingStore(),
        webhook_secret=webhook_secret,
        success_url=os.getenv("BILLING_SUCCESS_URL", "https://zouseeking-web-staging.onrender.com/mypage.html"),
        cancel_url=os.getenv("BILLING_CANCEL_URL", "https://zouseeking-web-staging.onrender.com/mypage.html"),
        portal_return_url=os.getenv("BILLING_PORTAL_RETURN_URL", "https://zouseeking-web-staging.onrender.com/mypage.html"),
    )


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, SignatureVerificationError):
        return HTTPException(status_code=400, detail="invalid webhook signature or payload")
    if isinstance(error, PriceUnavailable):
        return HTTPException(status_code=409, detail="requested price is unavailable")
    if isinstance(error, BillingError):
        return HTTPException(status_code=error.status_code, detail=error.public_message)
    return HTTPException(status_code=500, detail="billing operation failed")


def _status_payload(status: Any) -> dict[str, Any]:
    return {
        "subject_id": str(status.subject_id),
        "product_code": status.product_code,
        "subscription_id": status.subscription_id,
        "subscription_status": status.subscription_status,
        "payment_status": status.payment_status,
        "current_period_start": status.current_period_start.isoformat() if status.current_period_start else None,
        "current_period_end": status.current_period_end.isoformat() if status.current_period_end else None,
        "cancel_at_period_end": status.cancel_at_period_end,
        "entitlement_active": status.entitlement_active,
    }


@router.get("/prices")
async def list_prices() -> List[dict[str, Any]]:
    """Expose amounts and availability, never provider price identifiers."""

    return await _PUBLIC_CATALOG.list_public_async()


@router.post("/checkout")
async def create_checkout(
    request: CheckoutRequest,
    user: AuthUser = Depends(require_user),
    service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    try:
        outcome = await service.create_checkout(
            user.user_id,
            user.email,
            request.product_code,
            request.billing_region,
            report_key=request.query_key,
            now=datetime.now(timezone.utc),
        )
    except (PriceUnavailable, BillingError) as error:
        raise _http_error(error) from error
    return {
        "session_id": outcome.session_id,
        "url": outcome.url,
        "product_code": outcome.product_code,
        "price_version": outcome.price_version,
        "currency": outcome.currency,
        "amount_minor": outcome.amount_minor,
        "mode": outcome.mode,
    }


@router.post("/portal")
async def create_portal(
    user: AuthUser = Depends(require_user),
    service: BillingService = Depends(get_billing_service),
) -> dict[str, str]:
    try:
        outcome = await service.create_portal(user.user_id)
    except BillingError as error:
        raise _http_error(error) from error
    return {"url": outcome.url}


@router.get("/status")
async def get_status(
    user: AuthUser = Depends(require_user),
    service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    try:
        return _status_payload(await service.get_status(user.user_id))
    except BillingError as error:
        raise _http_error(error) from error


@router.get("/subscription")
async def get_subscription(
    user: AuthUser = Depends(require_user),
    service: BillingService = Depends(get_billing_service),
) -> Optional[dict[str, Any]]:
    try:
        subscription = await service.get_subscription_for_read(user.user_id)
    except BillingError as error:
        raise _http_error(error) from error
    if subscription is None:
        return None
    return {
        "plan": subscription.product_code,
        "status": "active" if subscription.status == "trialing" else "past_due" if subscription.status == "unpaid" else subscription.status,
        "current_period_end": subscription.current_period_end.isoformat()
        if subscription.current_period_end
        else None,
        "cancel_at_period_end": subscription.cancel_at_period_end,
    }


@router.post("/cancel")
async def cancel_subscription(
    user: AuthUser = Depends(require_user),
    service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    try:
        outcome = await service.request_cancel(user.user_id)
    except BillingError as error:
        raise _http_error(error) from error
    return {
        "subscription_id": outcome.subscription_id,
        "at_period_end": outcome.at_period_end,
        "already_requested": outcome.already_requested,
    }


@router.post("/refunds")
async def request_refund(
    request: RefundRequestBody,
    user: AuthUser = Depends(require_user),
    service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    try:
        result = await service.request_refund(
            user.user_id,
            request.payment_intent_id,
            now=datetime.now(timezone.utc),
        )
    except BillingError as error:
        raise _http_error(error) from error
    return {
        "request_id": result.request_id,
        "payment_intent_id": result.payment_intent_id,
        "status": result.status,
    }


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    service: BillingService = Depends(get_billing_service),
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, Any]:
    raw_body = await request.body()
    try:
        result = await service.handle_webhook(
            raw_body,
            stripe_signature or "",
            now=datetime.now(timezone.utc),
        )
    except (SignatureVerificationError, BillingError) as error:
        raise _http_error(error) from error
    return {
        "status": result.status,
        "event_id": result.event_id,
        "duplicate": result.duplicate,
        "ignored": result.ignored,
    }
