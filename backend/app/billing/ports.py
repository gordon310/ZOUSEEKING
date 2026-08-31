"""Small provider and persistence contracts for the billing service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence
from uuid import UUID


@dataclass(frozen=True)
class BillingSubject:
    subject_type: Literal["user", "organization"]
    subject_id: UUID
    stripe_customer_id: Optional[str]
    billing_email: Optional[str]


@dataclass(frozen=True)
class BillingStatus:
    subject_id: UUID
    product_code: Optional[str]
    subscription_id: Optional[str]
    subscription_status: str
    payment_status: str
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    entitlement_active: bool


@dataclass(frozen=True)
class SubscriptionSnapshot:
    subscription_id: str
    product_code: Optional[str]
    status: str
    cancel_at_period_end: bool


@dataclass(frozen=True)
class RefundCandidate:
    request_id: str
    payment_intent_id: str
    charged_at: datetime
    used_entitlement: bool
    currency: str
    amount_minor: int
    status: str = "eligible"


@dataclass(frozen=True)
class RefundRequest:
    request_id: str
    payment_intent_id: str
    status: str
    requested_at: datetime
    reason: Optional[str] = None
    provider_refund_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderEvent:
    event_id: str
    event_type: str
    payload: Mapping[str, Any]
    received_at: datetime


@dataclass(frozen=True)
class EventClaim:
    state: Literal["new", "retry", "processed", "in_progress", "dead_letter"]
    attempt_count: int


@dataclass(frozen=True)
class AuditRecord:
    actor_id: Optional[str]
    subject_id: Optional[str]
    action: str
    provider_object_id: Optional[str]
    event_id: Optional[str]
    reason: Optional[str]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: Optional[datetime] = None
    schema_version: str = "billing-audit-v1"


@dataclass(frozen=True)
class OutboxAction:
    kind: str
    dedupe_key: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CheckoutSessionResult:
    session_id: str
    url: str


@dataclass(frozen=True)
class PortalSessionResult:
    url: str


@dataclass(frozen=True)
class RefundResult:
    refund_id: str
    status: str


@dataclass(frozen=True)
class InternalActor:
    actor_id: UUID
    roles: Sequence[str]


class StripeGateway(Protocol):
    def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
        ...

    def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
        ...

    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
        ...

    def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
        ...


class BillingStore(Protocol):
    """Persistence boundary; production implementations must use one DB transaction."""

    def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
        ...

    def get_portal_subject(self, user_id: UUID) -> BillingSubject:
        ...

    def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
        ...

    def process_provider_event(
        self,
        event: ProviderEvent,
        audit: AuditRecord,
        outbox: Optional[OutboxAction],
    ) -> None:
        ...

    def mark_provider_event_failed(
        self,
        event_id: str,
        *,
        failure_class: Literal["transient", "permanent"],
        error_code: str,
        next_attempt_at: Optional[datetime],
    ) -> None:
        ...

    def get_status(self, user_id: UUID) -> BillingStatus:
        ...

    def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
        ...

    def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
        ...

    def get_refund_candidate(
        self, user_id: UUID, payment_intent_id: str
    ) -> Optional[RefundCandidate]:
        ...

    def create_refund_request(
        self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
    ) -> RefundRequest:
        ...

    def get_refund_request(self, request_id: str) -> RefundRequest:
        ...

    def mark_refund_succeeded(
        self, request_id: str, refund_id: str, completed_at: datetime
    ) -> None:
        ...

    def mark_refund_retry(
        self, request_id: str, *, error_code: str, next_attempt_at: datetime
    ) -> None:
        ...

    def append_audit(self, record: AuditRecord) -> None:
        ...
