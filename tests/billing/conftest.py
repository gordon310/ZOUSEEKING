from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional
from uuid import UUID

import pytest

from backend.app.billing.ports import (
    AuditRecord,
    BillingStatus,
    BillingSubject,
    CheckoutSessionResult,
    EventClaim,
    OutboxAction,
    PortalSessionResult,
    ProviderEvent,
    RefundCandidate,
    RefundRequest,
    RefundResult,
    SubscriptionSnapshot,
)
from backend.app.billing.service import TransientBillingError


TEST_USER_ID = UUID("00000000-0000-0000-0000-000000000030")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")
FIXED_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
SECRET = "whsec_test_secret"


class FakeGateway:
    def __init__(self) -> None:
        self.checkout_calls: List[Mapping[str, Any]] = []
        self.portal_calls: List[tuple[str, str]] = []
        self.cancel_calls: List[tuple[str, bool]] = []
        self.refund_calls: List[tuple[str, str]] = []
        self.fail_refund_once = False

    def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
        self.checkout_calls.append(dict(params))
        return CheckoutSessionResult("cs_test_123", "https://checkout.test/session/cs_test_123")

    def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
        self.portal_calls.append((customer_id, return_url))
        return PortalSessionResult("https://billing.test/session/bps_test_123")

    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
        self.cancel_calls.append((subscription_id, at_period_end))

    def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
        self.refund_calls.append((payment_intent_id, reason))
        if self.fail_refund_once:
            self.fail_refund_once = False
            raise TransientBillingError("provider timeout")
        return RefundResult("re_test_123", "succeeded")


class FakeStore:
    def __init__(self) -> None:
        self.subjects: Dict[str, BillingSubject] = {
            "risk_report_single": BillingSubject("user", TEST_USER_ID, None, "member@example.com"),
            "c_plus_monthly": BillingSubject("user", TEST_USER_ID, "cus_existing", None),
            "b_data_pro_monthly": BillingSubject("organization", UUID("00000000-0000-0000-0000-000000000040"), "cus_org", None),
        }
        self.portal_subject = BillingSubject("user", TEST_USER_ID, "cus_existing", None)
        self.events: Dict[str, Dict[str, Any]] = {}
        self.processed_events: List[str] = []
        self.failed_events: List[Dict[str, Any]] = []
        self.fail_event_once = False
        self.fail_claim_once = False
        self.status = BillingStatus(
            subject_id=TEST_USER_ID,
            product_code="c_plus_monthly",
            subscription_id="sub_test_123",
            subscription_status="active",
            payment_status="paid",
            current_period_start=FIXED_NOW - timedelta(days=10),
            current_period_end=FIXED_NOW + timedelta(days=20),
            cancel_at_period_end=False,
            entitlement_active=True,
        )
        self.subscription = SubscriptionSnapshot("sub_test_123", "c_plus_monthly", "active", False)
        self.audits: List[AuditRecord] = []
        self.outbox: List[OutboxAction] = []
        self.refund_candidates: Dict[str, RefundCandidate] = {}
        self.refund_requests: Dict[str, RefundRequest] = {}
        self.refund_retries: List[Dict[str, Any]] = []

    def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
        subject = self.subjects[product_code]
        if subject.subject_type == "user" and subject.subject_id != user_id:
            raise LookupError("subject not found")
        return subject

    def get_portal_subject(self, user_id: UUID) -> BillingSubject:
        if self.portal_subject.subject_type == "user" and self.portal_subject.subject_id != user_id:
            raise LookupError("subject not found")
        return self.portal_subject

    def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
        if self.fail_claim_once:
            self.fail_claim_once = False
            raise RuntimeError("database claim unavailable")
        existing = self.events.get(event.event_id)
        if existing:
            if existing["state"] == "processed":
                return EventClaim("processed", existing["attempt_count"])
            if existing["state"] == "in_progress":
                return EventClaim("in_progress", existing["attempt_count"])
            if existing["state"] == "dead_letter":
                return EventClaim("dead_letter", existing["attempt_count"])
            existing["attempt_count"] += 1
            existing["state"] = "in_progress"
            return EventClaim("retry", existing["attempt_count"])
        self.events[event.event_id] = {"state": "in_progress", "attempt_count": 1}
        return EventClaim("new", 1)

    def process_provider_event(
        self,
        event: ProviderEvent,
        audit: AuditRecord,
        outbox: Optional[OutboxAction],
    ) -> None:
        if self.fail_event_once:
            self.fail_event_once = False
            raise TransientBillingError("database unavailable")
        self.processed_events.append(event.event_id)
        self.audits.append(audit)
        if outbox:
            self.outbox.append(outbox)
        self.events[event.event_id]["state"] = "processed"
        event_object = ((event.payload.get("data") or {}).get("object") or {})
        if event.event_type == "invoice.payment_failed":
            self.status = replace(self.status, subscription_status="past_due", payment_status="failed", entitlement_active=False)
        elif event.event_type == "invoice.paid":
            self.status = replace(self.status, subscription_status="active", payment_status="paid", entitlement_active=True)
        elif event.event_type == "customer.subscription.deleted":
            self.status = replace(self.status, subscription_status="canceled", entitlement_active=False)
        elif event.event_type in {"customer.subscription.created", "customer.subscription.updated"}:
            self.status = replace(
                self.status,
                subscription_id=str(event_object.get("id") or self.status.subscription_id),
                subscription_status=str(event_object.get("status") or self.status.subscription_status),
                cancel_at_period_end=bool(event_object.get("cancel_at_period_end", self.status.cancel_at_period_end)),
                entitlement_active=str(event_object.get("status") or "") in {"active", "trialing"},
            )

    def mark_provider_event_failed(
        self,
        event_id: str,
        *,
        failure_class: str,
        error_code: str,
        next_attempt_at: Optional[datetime],
    ) -> None:
        self.failed_events.append(
            {
                "event_id": event_id,
                "failure_class": failure_class,
                "error_code": error_code,
                "next_attempt_at": next_attempt_at,
            }
        )
        self.events[event_id]["state"] = "dead_letter" if failure_class == "permanent" else "failed"

    def get_status(self, user_id: UUID) -> BillingStatus:
        if self.status.subject_id != user_id:
            raise LookupError("status not found")
        return self.status

    def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
        if user_id != TEST_USER_ID:
            return None
        return self.subscription

    def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
        self.subscription = replace(self.subscription, cancel_at_period_end=at_period_end)
        self.status = replace(self.status, cancel_at_period_end=at_period_end)

    def get_refund_candidate(self, user_id: UUID, payment_intent_id: str) -> Optional[RefundCandidate]:
        candidate = self.refund_candidates.get(payment_intent_id)
        if candidate and candidate.request_id.startswith(str(user_id)):
            return candidate
        return None

    def create_refund_request(
        self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
    ) -> RefundRequest:
        existing = self.refund_requests.get(candidate.request_id)
        if existing:
            return existing
        request = RefundRequest(candidate.request_id, candidate.payment_intent_id, "requested", requested_at)
        self.refund_requests[candidate.request_id] = request
        return request

    def get_refund_request(self, request_id: str) -> RefundRequest:
        return self.refund_requests[request_id]

    def mark_refund_succeeded(self, request_id: str, refund_id: str, completed_at: datetime) -> None:
        current = self.refund_requests[request_id]
        self.refund_requests[request_id] = replace(current, status="succeeded", provider_refund_id=refund_id)

    def mark_refund_retry(self, request_id: str, *, error_code: str, next_attempt_at: datetime) -> None:
        self.refund_retries.append(
            {"request_id": request_id, "error_code": error_code, "next_attempt_at": next_attempt_at}
        )

    def append_audit(self, record: AuditRecord) -> None:
        self.audits.append(record)


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def fake_store() -> FakeStore:
    return FakeStore()
