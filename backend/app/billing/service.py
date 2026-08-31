"""Provider-independent billing orchestration and safety rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional
from uuid import UUID

from .catalog import PriceCatalog, PriceUnavailable
from .ports import (
    AuditRecord,
    BillingStatus,
    BillingStore,
    InternalActor,
    OutboxAction,
    ProviderEvent,
    RefundRequest,
    StripeGateway,
)
from .signatures import construct_event


class BillingError(Exception):
    """Base error whose public response is mapped by the route layer."""

    status_code = 500
    public_message = "billing operation failed"


class BillingNotConfigured(BillingError):
    status_code = 503
    public_message = "billing is not configured"


class BillingNotFound(BillingError):
    status_code = 404
    public_message = "billing record not found"


class BillingConflict(BillingError):
    status_code = 409
    public_message = "billing operation cannot be completed"


class ForbiddenBillingOperation(BillingError):
    status_code = 403
    public_message = "billing operation is not permitted"


class RefundNotEligible(BillingError):
    status_code = 409
    public_message = "refund is not eligible"


class PermanentBillingError(BillingError):
    status_code = 400
    public_message = "billing event is not processable"


class TransientBillingError(BillingError):
    status_code = 500
    public_message = "billing service temporarily unavailable"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: int = 5
    max_delay_seconds: int = 300

    def next_retry_at(self, attempt_count: int, now: datetime) -> Optional[datetime]:
        """Return the next deterministic retry time, or None when exhausted."""

        if attempt_count <= 0 or attempt_count >= self.max_attempts:
            return None
        delay = min(self.base_delay_seconds * (2 ** (attempt_count - 1)), self.max_delay_seconds)
        return _as_utc(now) + timedelta(seconds=delay)


@dataclass(frozen=True)
class CheckoutOutcome:
    session_id: str
    url: str
    product_code: str
    price_version: str
    currency: str
    amount_minor: int
    mode: str


@dataclass(frozen=True)
class PortalOutcome:
    url: str


@dataclass(frozen=True)
class WebhookResult:
    status: str
    event_id: str
    duplicate: bool = False
    ignored: bool = False


@dataclass(frozen=True)
class CancelOutcome:
    subscription_id: str
    at_period_end: bool
    already_requested: bool


_SUPPORTED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
    "refund.created",
    "refund.updated",
}
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_SENSITIVE_KEYS = {
    "email",
    "token",
    "authorization",
    "client_secret",
    "raw",
    "payload",
    "card",
    "payment_method",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sanitize_value(value: Any, *, key: Optional[str] = None) -> Any:
    if key and key.lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(name): _sanitize_value(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _EMAIL_RE.sub("[redacted-email]", value)
    return value


def sanitize_reason(reason: Optional[str]) -> Optional[str]:
    if reason is None:
        return None
    return str(_sanitize_value(reason))[:500]


class BillingService:
    """Orchestrate billing without trusting browser-provided billing fields."""

    def __init__(
        self,
        *,
        catalog: PriceCatalog,
        gateway: StripeGateway,
        store: BillingStore,
        webhook_secret: str,
        success_url: str,
        cancel_url: str,
        portal_return_url: str,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self.catalog = catalog
        self.gateway = gateway
        self.store = store
        self.webhook_secret = webhook_secret
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.portal_return_url = portal_return_url
        self.retry_policy = retry_policy or RetryPolicy()

    def create_checkout(
        self,
        user_id: UUID,
        email: str,
        product_code: str,
        billing_region: str,
        *,
        now: datetime,
    ) -> CheckoutOutcome:
        price = self.catalog.resolve(product_code, billing_region)
        try:
            subject = self.store.get_subject(user_id, product_code)
        except (KeyError, LookupError) as exc:
            raise BillingNotFound() from exc

        metadata = {
            "user_id": str(user_id),
            "subject_id": str(subject.subject_id),
            "product_code": price.product_code,
            "price_version": price.price_version,
            "billing_region": str(billing_region).strip().upper(),
        }
        params: dict[str, Any] = {
            "mode": price.mode,
            "line_items": [{"price": price.stripe_price_id, "quantity": 1}],
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "allow_promotion_codes": True,
            "client_reference_id": str(subject.subject_id),
            "metadata": metadata,
        }
        if price.mode == "subscription":
            params["subscription_data"] = {"metadata": dict(metadata)}
        if subject.stripe_customer_id:
            params["customer"] = subject.stripe_customer_id
        else:
            customer_email = str(email or "").strip()
            if not customer_email:
                raise BillingConflict()
            params["customer_email"] = customer_email

        try:
            result = self.gateway.create_checkout_session(params)
        except TransientBillingError:
            raise
        except Exception as exc:
            raise TransientBillingError() from exc
        self.store.append_audit(
            AuditRecord(
                actor_id=str(user_id),
                subject_id=str(subject.subject_id),
                action="billing.checkout.created",
                provider_object_id=result.session_id,
                event_id=None,
                reason=None,
                metadata={
                    "product_code": price.product_code,
                    "price_version": price.price_version,
                    "currency": price.currency,
                    "amount_minor": price.amount_minor,
                    "mode": price.mode,
                },
                occurred_at=_as_utc(now),
            )
        )
        return CheckoutOutcome(
            session_id=result.session_id,
            url=result.url,
            product_code=price.product_code,
            price_version=price.price_version,
            currency=price.currency,
            amount_minor=price.amount_minor,
            mode=price.mode,
        )

    def create_portal(self, user_id: UUID) -> PortalOutcome:
        try:
            subject = self.store.get_portal_subject(user_id)
        except (AttributeError, KeyError, LookupError) as exc:
            raise BillingNotFound() from exc
        if not subject.stripe_customer_id:
            raise BillingConflict()
        try:
            result = self.gateway.create_portal_session(subject.stripe_customer_id, self.portal_return_url)
        except TransientBillingError:
            raise
        except Exception as exc:
            raise TransientBillingError() from exc
        self.store.append_audit(
            AuditRecord(
                actor_id=str(user_id),
                subject_id=str(subject.subject_id),
                action="billing.portal.created",
                provider_object_id=None,
                event_id=None,
                reason=None,
                metadata={},
                occurred_at=datetime.now(timezone.utc),
            )
        )
        return PortalOutcome(result.url)

    def get_status(self, user_id: UUID) -> BillingStatus:
        try:
            return self.store.get_status(user_id)
        except (KeyError, LookupError) as exc:
            raise BillingNotFound() from exc

    def request_cancel(self, user_id: UUID) -> CancelOutcome:
        try:
            subscription = self.store.get_subscription(user_id)
        except (KeyError, LookupError) as exc:
            raise BillingNotFound() from exc
        if not subscription:
            raise BillingNotFound()
        if subscription.cancel_at_period_end:
            return CancelOutcome(subscription.subscription_id, True, True)
        try:
            self.gateway.cancel_subscription(subscription.subscription_id, at_period_end=True)
        except TransientBillingError:
            raise
        except Exception as exc:
            raise TransientBillingError() from exc
        self.store.record_cancel(user_id, at_period_end=True)
        self.store.append_audit(
            AuditRecord(
                actor_id=str(user_id),
                subject_id=str(user_id),
                action="billing.subscription.cancel_requested",
                provider_object_id=subscription.subscription_id,
                event_id=None,
                reason=None,
                metadata={"at_period_end": True},
                occurred_at=datetime.now(timezone.utc),
            )
        )
        return CancelOutcome(subscription.subscription_id, True, False)

    def request_refund(self, user_id: UUID, payment_intent_id: str, *, now: datetime) -> RefundRequest:
        try:
            candidate = self.store.get_refund_candidate(user_id, payment_intent_id)
        except (KeyError, LookupError) as exc:
            raise RefundNotEligible() from exc
        if not candidate:
            raise RefundNotEligible()
        age = _as_utc(now) - _as_utc(candidate.charged_at)
        if (
            candidate.status != "eligible"
            or age.total_seconds() < 0
            or age > timedelta(hours=48)
            or candidate.used_entitlement
        ):
            raise RefundNotEligible()
        request = self.store.create_refund_request(user_id, candidate, _as_utc(now))
        self.store.append_audit(
            AuditRecord(
                actor_id=str(user_id),
                subject_id=str(user_id),
                action="billing.refund.requested",
                provider_object_id=payment_intent_id,
                event_id=None,
                reason=None,
                metadata={"currency": candidate.currency, "amount_minor": candidate.amount_minor},
                occurred_at=_as_utc(now),
            )
        )
        return request

    def approve_refund(
        self,
        actor: InternalActor,
        request_id: str,
        reason: str,
        *,
        now: datetime,
    ) -> RefundRequest:
        if "finance" not in set(actor.roles):
            raise ForbiddenBillingOperation()
        try:
            request = self.store.get_refund_request(request_id)
        except (KeyError, LookupError) as exc:
            raise BillingNotFound() from exc
        if request.status == "succeeded":
            return request
        try:
            result = self.gateway.create_refund(request.payment_intent_id, reason=sanitize_reason(reason) or "approved")
        except TransientBillingError:
            retry_at = self.retry_policy.next_retry_at(1, now)
            if retry_at is not None:
                self.store.mark_refund_retry(request_id, error_code="provider_transient", next_attempt_at=retry_at)
            raise
        except Exception as exc:
            raise TransientBillingError() from exc
        self.store.mark_refund_succeeded(request_id, result.refund_id, _as_utc(now))
        self.store.append_audit(
            AuditRecord(
                actor_id=str(actor.actor_id),
                subject_id=None,
                action="billing.refund.approved",
                provider_object_id=result.refund_id,
                event_id=None,
                reason=sanitize_reason(reason),
                metadata={"request_id": request_id, "provider_status": result.status},
                occurred_at=_as_utc(now),
            )
        )
        return RefundRequest(
            request_id=request.request_id,
            payment_intent_id=request.payment_intent_id,
            status="succeeded",
            requested_at=request.requested_at,
            reason=request.reason,
            provider_refund_id=result.refund_id,
        )

    def handle_webhook(
        self,
        raw_body: bytes,
        signature_header: str,
        *,
        now: datetime,
    ) -> WebhookResult:
        event = construct_event(raw_body, signature_header, self.webhook_secret, now=_as_utc(now))
        try:
            claim = self.store.claim_provider_event(event)
        except TransientBillingError:
            raise
        except Exception as exc:
            # A failed claim did not establish ownership of the event, so no
            # provider-event row is marked.  The caller receives a safe 5xx.
            raise TransientBillingError() from exc
        if claim.state == "in_progress":
            # An in-flight claim is not proof that its side effects committed.
            # Return a retryable error so Stripe can redeliver if the owner dies.
            raise TransientBillingError()
        if claim.state in {"processed", "dead_letter"}:
            return WebhookResult("duplicate", event.event_id, duplicate=True)

        try:
            audit, outbox, ignored = self._event_side_effects(event)
            self.store.process_provider_event(event, audit, outbox)
        except PermanentBillingError:
            self.store.mark_provider_event_failed(
                event.event_id,
                failure_class="permanent",
                error_code="invalid_event",
                next_attempt_at=None,
            )
            raise
        except TransientBillingError:
            retry_at = self.retry_policy.next_retry_at(claim.attempt_count, _as_utc(now))
            self.store.mark_provider_event_failed(
                event.event_id,
                failure_class="transient" if retry_at is not None else "permanent",
                error_code="event_processing_failed",
                next_attempt_at=retry_at,
            )
            raise
        except Exception as exc:
            retry_at = self.retry_policy.next_retry_at(claim.attempt_count, _as_utc(now))
            self.store.mark_provider_event_failed(
                event.event_id,
                failure_class="transient" if retry_at is not None else "permanent",
                error_code="event_processing_failed",
                next_attempt_at=retry_at,
            )
            raise TransientBillingError() from exc
        return WebhookResult(
            "ignored" if ignored else "processed",
            event.event_id,
            ignored=ignored,
        )

    def _event_side_effects(self, event: ProviderEvent) -> tuple[AuditRecord, Optional[OutboxAction], bool]:
        event_data = event.payload.get("data")
        event_object = event_data.get("object") if isinstance(event_data, Mapping) else None
        if not isinstance(event_object, Mapping):
            raise PermanentBillingError()
        provider_object_id = event_object.get("id")
        if not isinstance(provider_object_id, str) or not provider_object_id:
            raise PermanentBillingError()
        if event.event_type not in _SUPPORTED_EVENTS:
            return (
                AuditRecord(
                    actor_id=None,
                    subject_id=None,
                    action="billing.event.ignored",
                    provider_object_id=provider_object_id,
                    event_id=event.event_id,
                    reason=None,
                    metadata={"event_type": event.event_type},
                    occurred_at=event.received_at,
                ),
                None,
                True,
            )

        metadata = event_object.get("metadata")
        subject_id = metadata.get("user_id") if isinstance(metadata, Mapping) else None
        if subject_id is not None and not isinstance(subject_id, str):
            subject_id = None
        audit = AuditRecord(
            actor_id=None,
            subject_id=subject_id,
            action=f"billing.webhook.{event.event_type.replace('.', '_')}",
            provider_object_id=provider_object_id,
            event_id=event.event_id,
            reason=None,
            metadata=_sanitize_value(
                {
                    "event_type": event.event_type,
                    "status": event_object.get("status"),
                    "subscription_id": event_object.get("subscription"),
                }
            ),
            occurred_at=event.received_at,
        )
        outbox = None
        if event.event_type == "invoice.payment_failed":
            outbox = OutboxAction(
                kind="billing.dunning",
                dedupe_key=f"dunning:{event.event_id}",
                payload={"event_id": event.event_id, "invoice_id": provider_object_id},
            )
        return audit, outbox, False
