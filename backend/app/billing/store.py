"""PostgreSQL adapter for the :class:`backend.app.billing.ports.BillingStore` port.

One transaction per operation
-----------------------------
Every public method acquires a connection from an ``asyncpg`` pool and performs
all of its reads/writes inside a single ``async with conn.transaction()``
block.  ``claim_provider_event``, ``process_provider_event`` and
``mark_provider_event_failed`` deliberately use *separate* transactions: a
claim must be durable before the (potentially long) provider side effects run,
and a failed processing attempt must be able to mark the event ``failed`` even
though the processing transaction rolled back.

Schema gate
-----------
This adapter reads/writes the V1 billing tables created by (in order):

* ``supabase/migrations/20260905000100_v1_organizations.sql``
  (public.organizations, public.organization_members)
* ``supabase/migrations/20260905000200_v1_products_subscriptions.sql``
  (public.product_prices, public.billing_customers, public.subscriptions)
* ``supabase/migrations/20260905000500_v1_finance_admin_audit.sql``
  (public.payment_orders, public.refunds, public.payment_events,
   public.audit_events)

Before those migrations are applied to a database every call raises an
``asyncpg.UndefinedTableError``; no schema is created lazily and nothing is
initialized on import (repository rule: never run schema initialization from
application startup).  The caller must connect as a role that bypasses RLS
(the table owner or ``service_role``): these tables are service-internal and
browsers hold no grants.

Frozen-field constraints honoured
---------------------------------
* Money is stored as ``integer`` minor units plus a 3-letter uppercase
  ``currency`` (Stripe reports lowercase codes, so the adapter uppercases).
* ``billing_customers`` / ``subscriptions`` / ``payment_orders`` scopes are
  exactly one of ``owner_user_id`` or ``organization_id`` (XOR column checks).
* ``subscriptions`` snapshots product/price/currency/amount at insert time and
  mirrors Stripe status; product/price/currency/amount columns are never
  rewritten by later events.
* ``payment_events`` stores only the sha256 of the canonical (sorted-key)
  JSON payload, never the payload itself.
* ``audit_events`` is append-only; the adapter only inserts.  ``summary`` is
  redacted (no email addresses, tokens, raw payloads, payment credentials).

Representation notes (no schema change is allowed in this batch)
----------------------------------------------------------------
* ``payment_events`` has no ``attempt_count`` / ``next_attempt_at`` /
  failure-class columns.  The failure class, error code and next attempt time
  of a failed webhook event are persisted as an ``audit_events`` row with
  ``action = 'billing.event.failed'``, ``target_type = 'provider_event'``,
  ``target_id = <provider event id>`` and a ``summary`` containing
  ``failure_class``, ``error_code`` and ``next_attempt_at``.  Retry scheduling
  itself is driven by the provider redelivering after the 5xx response; there
  is no local scheduler in V1.  ``EventClaim.attempt_count`` is derived as
  ``(number of recorded billing.event.failed rows) + 1``.
* Transient refund failures are *not* written as ``refunds.status='failed'``
  (that would make a later retry indistinguishable from a permanent failure).
  ``mark_refund_retry`` keeps the row ``pending`` and records the retry in
  ``audit_events`` (``action='billing.refund.retry_scheduled'``).
* ``OutboxAction`` has no table in V1 (the durable worker/outbox table is a
  later migration).  ``process_provider_event`` accepts the argument for port
  compatibility and records the pending outbox intent (kind + dedupe key) in
  the audit ``summary`` so the information survives until a worker exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Union
from uuid import UUID

import asyncpg

from ..db import get_pool
from .ports import (
    AuditRecord,
    BillingStatus,
    BillingSubject,
    EventClaim,
    OutboxAction,
    ProviderEvent,
    RefundCandidate,
    RefundRequest,
    SubscriptionSnapshot,
)

# Personal products belong to the authenticated user; the B-side product
# belongs to the user's organization (membership-resolved).
_USER_SCOPE_PRODUCTS = frozenset({"risk_report_single", "c_plus_monthly"})
_ORG_SCOPE_PRODUCTS = frozenset({"b_data_pro_monthly"})
_SUBSCRIPTION_PRODUCTS = frozenset({"c_plus_monthly", "b_data_pro_monthly"})

# Stripe statuses that V1's subscriptions_status_allowed check can store.
_ALLOWED_SUBSCRIPTION_STATUSES = frozenset(
    {"trialing", "active", "past_due", "canceled", "unpaid", "incomplete", "incomplete_expired"}
)
# Stripe "paused" has no V1 column value; raising here dead-letters the event
# so operators inspect it instead of the adapter guessing a status.
_STATUS_CANNOT_PROCESS = frozenset({"paused"})

# The checkout metadata carries the catalog's version label (e.g.
# "v1-2026-08") while the frozen tables store an integer price_version.
# Known labels are mapped; anything else falls back to 1 and is noted.
_KNOWN_PRICE_VERSION_LABELS = {"v1": 1, "v1-2026-08": 1}

_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_SENSITIVE_KEYS = frozenset(
    {
        "email",
        "token",
        "authorization",
        "client_secret",
        "raw",
        "payload",
        "card",
        "payment_method",
    }
)
# Redaction is defence in depth: the service layer already sanitises audit
# records, the store re-checks before anything reaches jsonb.

_SUMMARY_STRING_CAP = 2000


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    utc = _as_utc(value)
    return utc.isoformat() if utc is not None else None


def _redact(value: Any, *, key: Optional[str] = None) -> Any:
    """Recursively strip sensitive values before they reach the audit jsonb."""
    if key is not None and str(key).lower() in _SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(name): _redact(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _EMAIL_RE.sub("[redacted-email]", value)[:_SUMMARY_STRING_CAP]
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse_uuid(value: Any) -> Optional[UUID]:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _coerce_price_version(value: Any) -> int:
    """Coerce catalog/checkout version labels to the integer column value."""
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return value if value >= 1 else 1
    text = str(value or "").strip().lower()
    if not text:
        return 1
    if text in _KNOWN_PRICE_VERSION_LABELS:
        return _KNOWN_PRICE_VERSION_LABELS[text]
    match = re.match(r"\d+", text)
    if match:
        return max(int(match.group()), 1)
    return 1


def _currency(value: Any) -> str:
    """Normalise a provider currency code to the uppercase form in CHECKs."""
    text = str(value or "").strip().upper()
    return text if len(text) == 3 else ""


def _stripe_datetime(value: Any) -> Optional[datetime]:
    """Coerce Stripe epoch seconds / ISO-8601 strings to aware datetimes."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                return datetime.fromisoformat(value[:-1] + "+00:00")
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def _first_line_item_price(obj: Mapping[str, Any]) -> tuple[str, Optional[int]]:
    """Return (uppercase currency, unit_amount) of the first line item."""
    items = obj.get("items")
    data = items.get("data") if isinstance(items, Mapping) else None
    if not isinstance(data, list) or not data:
        return "", None
    first = data[0]
    price = first.get("price") if isinstance(first, Mapping) else None
    if not isinstance(price, Mapping):
        return "", None
    currency = _currency(price.get("currency"))
    amount = price.get("unit_amount")
    if not isinstance(amount, (int, float)) or amount <= 0:
        return currency, None
    return currency, int(amount)


class PostgresBillingStore:
    """Asyncpg implementation of :class:`BillingStore` against the V1 tables.

    :param pool: an optional asyncpg pool; defaults to the application-wide
        pool from :func:`backend.app.db.get_pool`.
    """

    def __init__(self, pool: Optional[asyncpg.Pool] = None) -> None:
        self._pool = pool

    def _acquire(self) -> asyncpg.Pool:
        return self._pool if self._pool is not None else get_pool()

    # -- subjects -------------------------------------------------------------

    async def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
        """Resolve the billing subject for a checkout.

        Personal products map to the user scope; ``b_data_pro_monthly`` maps
        to the organization of the user's active membership (oldest first).
        The Stripe customer id comes from ``billing_customers`` and may be
        ``None`` before the first successful checkout.  Raises
        ``LookupError`` when no subject exists for the product.
        """
        product = str(product_code)
        pool = self._acquire()
        if product in _USER_SCOPE_PRODUCTS:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    user_row = await conn.fetchrow(
                        "select email from auth.users where id = $1", user_id
                    )
                    if user_row is None:
                        raise LookupError(f"user {user_id} not found")
                    customer_row = await conn.fetchrow(
                        "select stripe_customer_id from public.billing_customers"
                        " where owner_user_id = $1",
                        user_id,
                    )
                    return BillingSubject(
                        subject_type="user",
                        subject_id=user_id,
                        stripe_customer_id=_row_value(customer_row, "stripe_customer_id"),
                        billing_email=_row_value(user_row, "email"),
                    )
        if product in _ORG_SCOPE_PRODUCTS:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    org_row = await conn.fetchrow(
                        "select om.organization_id"
                        " from public.organization_members om"
                        " where om.user_id = $1 and om.status = 'active'"
                        " order by om.created_at, om.id"
                        " limit 1",
                        user_id,
                    )
                    if org_row is None:
                        raise LookupError(
                            f"no active organization membership for user {user_id}"
                        )
                    organization_id: UUID = _row_value(org_row, "organization_id")
                    customer_row = await conn.fetchrow(
                        "select stripe_customer_id from public.billing_customers"
                        " where organization_id = $1",
                        organization_id,
                    )
                    return BillingSubject(
                        subject_type="organization",
                        subject_id=organization_id,
                        stripe_customer_id=_row_value(customer_row, "stripe_customer_id"),
                        billing_email=None,
                    )
        raise LookupError(f"unknown billing product: {product_code}")

    async def get_portal_subject(self, user_id: UUID) -> BillingSubject:
        """Resolve the personal subject whose Stripe customer owns the portal.

        A subject is returned for any known user (their customer id may be
        ``None``, in which case the service raises a conflict because there is
        nothing to manage).  ``LookupError`` is raised only for unknown users.
        """
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                user_row = await conn.fetchrow(
                    "select email from auth.users where id = $1", user_id
                )
                if user_row is None:
                    raise LookupError(f"user {user_id} not found")
                customer_row = await conn.fetchrow(
                    "select stripe_customer_id from public.billing_customers"
                    " where owner_user_id = $1",
                    user_id,
                )
                return BillingSubject(
                    subject_type="user",
                    subject_id=user_id,
                    stripe_customer_id=_row_value(customer_row, "stripe_customer_id"),
                    billing_email=_row_value(user_row, "email"),
                )

    # -- provider webhook event ledger ---------------------------------------

    async def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
        """Atomically claim a provider webhook delivery.

        The first delivery inserts a ``payment_events`` row (status
        ``received``) and claims it as ``new``.  Duplicate deliveries fall
        through to the existing row:

        * ``processed`` / ``ignored`` -> ``processed`` (safe duplicate reply)
        * ``received`` -> ``in_progress`` (another worker is applying side
          effects; the caller returns 5xx so the provider redelivers later)
        * ``failed`` after a transient failure -> the event is re-claimed to
          ``received`` and returned as ``retry``
        * ``failed`` after a permanent failure -> ``dead_letter``

        ``attempt_count`` is derived from the number of recorded
        ``billing.event.failed`` audit rows plus one (V1 has no attempt
        column).  Only the sha256 of the canonical payload is stored.
        """
        digest = _payload_sha256(event.payload)
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    "insert into public.payment_events"
                    " (provider, provider_event_id, event_type, status, payload_sha256)"
                    " values ('stripe', $1, $2, 'received', $3)"
                    " on conflict (provider_event_id) do nothing"
                    " returning id",
                    event.event_id,
                    event.event_type,
                    digest,
                )
                if inserted is not None:
                    return EventClaim("new", 1)

                row = await conn.fetchrow(
                    "select status from public.payment_events"
                    " where provider_event_id = $1",
                    event.event_id,
                )
                failure = await conn.fetchrow(
                    "select summary->>'failure_class' as failure_class"
                    " from public.audit_events"
                    " where action = 'billing.event.failed'"
                    "   and target_type = 'provider_event' and target_id = $1"
                    " order by occurred_at desc, id desc limit 1",
                    event.event_id,
                )
                failed_count = await conn.fetchval(
                    "select count(*) from public.audit_events"
                    " where action = 'billing.event.failed'"
                    "   and target_type = 'provider_event' and target_id = $1",
                    event.event_id,
                )
                attempts = int(failed_count or 0) + 1
                status = _row_value(row, "status", "received")
                if status in ("processed", "ignored"):
                    return EventClaim("processed", attempts)
                if status == "received":
                    return EventClaim("in_progress", attempts)
                failure_class = _row_value(failure, "failure_class", "transient")
                if failure_class == "permanent":
                    return EventClaim("dead_letter", attempts)
                # Transient failure: re-claim so concurrent deliveries see an
                # in-progress event instead of both retrying at once.
                await conn.execute(
                    "update public.payment_events set status = 'received'"
                    " where provider_event_id = $1 and status = 'failed'",
                    event.event_id,
                )
                return EventClaim("retry", attempts)

    async def process_provider_event(
        self,
        event: ProviderEvent,
        audit: AuditRecord,
        outbox: Optional[OutboxAction],
    ) -> None:
        """Apply webhook domain side effects, audit and the processed marker.

        Single transaction: event-object side effects, the audit row and the
        ``payment_events`` terminal marker commit together or not at all.  A
        raised error rolls everything back so ``mark_provider_event_failed``
        can record the failure against the still-``received`` event row.

        Side effects (mirroring the state machine in
        ``docs/superpowers/specs/2026-08-31-stripe-billing-boundary-design.md``):

        * ``checkout.session.completed`` - upsert ``billing_customers``; for
          subscription mode upsert the ``subscriptions`` mirror (snapshot from
          the session line items plus checkout metadata); for payment mode
          upsert a ``payment_orders`` row keyed by a deterministic order_no
          derived from the session id.
        * ``customer.subscription.created/updated`` - upsert the subscription
          mirror by ``stripe_subscription_id`` (product/price/amount/currency
          are set only on insert and never rewritten by later events).
        * ``customer.subscription.deleted`` - mark the mirror ``canceled`` and
          keep the paid-period columns.
        * ``invoice.paid`` - restore the subscription to ``active`` and record
          the charge as a ``paid`` payment order when a payment intent is
          available (this is what later makes unused-period refunds possible).
        * ``invoice.payment_failed`` - mark the subscription ``past_due``.
        * ``refund.created/updated`` - sync ``refunds`` by
          ``provider_refund_id`` (creating a row when Stripe refunded a known
          order outside our flow), and downgrade the parent order to
          ``refunded`` / ``partially_refunded`` on success.

        Events whose object cannot be mapped to a row are still audited and
        marked ``processed``; the audit summary records why no side effect
        ran.  Events the service classifies as ignored (unsupported type) are
        marked ``ignored`` in the ledger and are reported as ``processed`` by
        later claims.  ``OutboxAction`` has no V1 table: its intent is stored
        in the audit summary until a durable worker table exists.
        """
        data = _mapping(event.payload.get("data"))
        event_object = _mapping(data.get("object"))
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                ignored = audit.action == "billing.event.ignored"
                summary: dict[str, Any] = {}
                if event_object:
                    summary = await self._apply_event_side_effects(
                        conn, event, event_object
                    )
                if outbox is not None:
                    summary.setdefault("outbox", {})["kind"] = outbox.kind
                    summary.setdefault("outbox", {})["dedupe_key"] = outbox.dedupe_key
                await self._insert_audit_row(conn, audit, extra=summary)
                await conn.execute(
                    "update public.payment_events"
                    " set status = $2, processed_at = now()"
                    " where provider_event_id = $1",
                    event.event_id,
                    "ignored" if ignored else "processed",
                )

    async def _apply_event_side_effects(
        self,
        conn: asyncpg.Connection,
        event: ProviderEvent,
        event_object: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return a redacted note describing what was (or was not) applied."""
        event_type = event.event_type
        if event_type == "checkout.session.completed":
            return await self._on_checkout_completed(conn, event_object)
        if event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            return await self._on_subscription_mirror_event(
                conn, event_type, event_object
            )
        if event_type == "invoice.paid":
            return await self._on_invoice_paid(conn, event_object)
        if event_type == "invoice.payment_failed":
            return await self._on_invoice_payment_failed(conn, event_object)
        if event_type in ("refund.created", "refund.updated"):
            return await self._on_refund_event(conn, event_object)
        return {"applied": "no_side_effect", "event_type": event_type}

    # -- shared row helpers (inside an open transaction) ----------------------

    async def _upsert_billing_customer(
        self,
        conn: asyncpg.Connection,
        *,
        owner_user_id: Optional[UUID],
        organization_id: Optional[UUID],
        stripe_customer_id: str,
    ) -> None:
        if owner_user_id is not None:
            await conn.execute(
                "insert into public.billing_customers"
                " (owner_user_id, organization_id, stripe_customer_id)"
                " values ($1, null, $2)"
                " on conflict (owner_user_id) where owner_user_id is not null"
                " do update set stripe_customer_id = excluded.stripe_customer_id",
                owner_user_id,
                stripe_customer_id,
            )
        else:
            await conn.execute(
                "insert into public.billing_customers"
                " (owner_user_id, organization_id, stripe_customer_id)"
                " values (null, $1, $2)"
                " on conflict (organization_id) where organization_id is not null"
                " do update set stripe_customer_id = excluded.stripe_customer_id",
                organization_id,
                stripe_customer_id,
            )

    async def _metadata_scope(
        self, conn: asyncpg.Connection, metadata: Mapping[str, Any]
    ) -> tuple[Optional[UUID], Optional[UUID], Optional[str]]:
        """Map checkout/subscription metadata to (user_id, org_id, product)."""
        meta = _mapping(metadata)
        product_code = str(meta.get("product_code") or "") or None
        subject_id = _parse_uuid(meta.get("subject_id"))
        user_id = _parse_uuid(meta.get("user_id"))
        if product_code in _ORG_SCOPE_PRODUCTS:
            organization_id = subject_id or (
                await self._resolve_org_for_user(conn, user_id) if user_id else None
            )
            return None, organization_id, product_code
        if product_code in _USER_SCOPE_PRODUCTS:
            return user_id, None, product_code
        return user_id, None, None

    async def _resolve_org_for_user(
        self, conn: asyncpg.Connection, user_id: Optional[UUID]
    ) -> Optional[UUID]:
        if user_id is None:
            return None
        row = await conn.fetchrow(
            "select om.organization_id"
            " from public.organization_members om"
            " where om.user_id = $1 and om.status = 'active'"
            " order by om.created_at, om.id limit 1",
            user_id,
        )
        return _row_value(row, "organization_id") if row else None

    async def _existing_subscription(
        self, conn: asyncpg.Connection, stripe_subscription_id: str
    ) -> Optional[asyncpg.Record]:
        if not stripe_subscription_id:
            return None
        return await conn.fetchrow(
            "select * from public.subscriptions where stripe_subscription_id = $1",
            stripe_subscription_id,
        )

    async def _update_subscription_mirror(
        self,
        conn: asyncpg.Connection,
        stripe_subscription_id: str,
        *,
        status: str,
        period_start: Optional[datetime],
        period_end: Optional[datetime],
        cancel_at_period_end: bool,
        stripe_customer_id: Optional[str],
    ) -> None:
        await conn.execute(
            "update public.subscriptions set"
            "  status = $2,"
            "  current_period_start = coalesce($3, current_period_start),"
            "  current_period_end = coalesce($4, current_period_end),"
            "  cancel_at_period_end = $5,"
            "  stripe_customer_id = coalesce($6, stripe_customer_id)"
            " where stripe_subscription_id = $1",
            stripe_subscription_id,
            status,
            period_start,
            period_end,
            bool(cancel_at_period_end),
            stripe_customer_id,
        )

    async def _insert_subscription(
        self,
        conn: asyncpg.Connection,
        *,
        user_id: Optional[UUID],
        organization_id: Optional[UUID],
        product_code: str,
        price_version: int,
        currency: str,
        amount_minor: int,
        stripe_customer_id: Optional[str],
        stripe_subscription_id: str,
        status: str,
        period_start: Optional[datetime],
        period_end: Optional[datetime],
        cancel_at_period_end: bool,
    ) -> None:
        if status not in _ALLOWED_SUBSCRIPTION_STATUSES:
            status = "incomplete"
        await conn.execute(
            "insert into public.subscriptions"
            " (user_id, organization_id, product_code, price_version, currency,"
            "  amount_minor, stripe_customer_id, stripe_subscription_id, status,"
            "  current_period_start, current_period_end, cancel_at_period_end)"
            " values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
            user_id,
            organization_id,
            product_code,
            price_version,
            currency,
            amount_minor,
            stripe_customer_id,
            stripe_subscription_id,
            status,
            period_start,
            period_end,
            cancel_at_period_end,
        )

    async def _upsert_subscription_mirror(
        self,
        conn: asyncpg.Connection,
        *,
        stripe_subscription_id: str,
        user_id: Optional[UUID],
        organization_id: Optional[UUID],
        product_code: Optional[str],
        price_version: int,
        currency: str,
        amount_minor: Optional[int],
        stripe_customer_id: Optional[str],
        status: str,
        period_start: Optional[datetime],
        period_end: Optional[datetime],
        cancel_at_period_end: bool,
    ) -> dict[str, Any]:
        """Update an existing mirror or insert one when a full snapshot exists.

        Inserting needs product_code, currency and a positive amount because
        those columns are NOT NULL; without them the event is recorded as an
        orphan in the returned note instead of fabricating price data.
        """
        note: dict[str, Any] = {"subscription_id": stripe_subscription_id}
        existing = await self._existing_subscription(conn, stripe_subscription_id)
        if existing is not None:
            await self._update_subscription_mirror(
                conn,
                stripe_subscription_id,
                status=status,
                period_start=period_start,
                period_end=period_end,
                cancel_at_period_end=cancel_at_period_end,
                stripe_customer_id=stripe_customer_id,
            )
            note["subscription_updated"] = True
            return note
        if (
            product_code not in _SUBSCRIPTION_PRODUCTS
            or not currency
            or not isinstance(amount_minor, int)
            or amount_minor <= 0
        ):
            note["orphan"] = "no mirror row and no complete price snapshot"
            return note
        if organization_id is None and user_id is None:
            note["orphan"] = "no mirror row and unresolvable scope"
            return note
        await self._insert_subscription(
            conn,
            user_id=user_id,
            organization_id=organization_id,
            product_code=product_code,
            price_version=price_version,
            currency=currency,
            amount_minor=amount_minor,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            period_start=period_start,
            period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
        )
        note["subscription_created"] = True
        return note

    # -- webhook event handlers ----------------------------------------------

    async def _on_checkout_completed(
        self, conn: asyncpg.Connection, obj: Mapping[str, Any]
    ) -> dict[str, Any]:
        note: dict[str, Any] = {"applied": "checkout.session.completed"}
        session_id = str(obj.get("id") or "")
        stripe_customer_id = str(obj.get("customer") or "")
        if not session_id:
            note["skipped"] = "missing session id"
            return note
        metadata = _mapping(obj.get("metadata"))
        product_code = str(metadata.get("product_code") or "")
        if not product_code:
            note["skipped"] = "missing metadata.product_code"
            return note
        user_id, organization_id, product_code = await self._metadata_scope(conn, metadata)
        if product_code in _SUBSCRIPTION_PRODUCTS and user_id is None and organization_id is None:
            note["skipped"] = "unresolvable scope"
            return note
        if stripe_customer_id:
            await self._upsert_billing_customer(
                conn,
                owner_user_id=user_id,
                organization_id=organization_id,
                stripe_customer_id=stripe_customer_id,
            )
            note["customer_upserted"] = True

        currency = _currency(obj.get("currency"))
        amount_minor = obj.get("amount_total")
        if not isinstance(amount_minor, (int, float)) or amount_minor <= 0:
            currency, amount_minor = _first_line_item_price(obj)
        else:
            amount_minor = int(amount_minor)

        mode = str(obj.get("mode") or "")
        if mode == "subscription":
            stripe_subscription_id = str(obj.get("subscription") or "")
            if not stripe_subscription_id:
                note["skipped"] = "subscription event without stripe_subscription_id"
                return note
            status = "active" if obj.get("payment_status") == "paid" else "incomplete"
            if currency and isinstance(amount_minor, int):
                amount_minor_for_insert: Optional[int] = amount_minor
            else:
                # Session without a charge amount (for example a trial): only
                # an existing mirror can be refreshed.
                currency, unit = _first_line_item_price(obj)
                amount_minor_for_insert = unit
            note.update(
                await self._upsert_subscription_mirror(
                    conn,
                    stripe_subscription_id=stripe_subscription_id,
                    user_id=user_id,
                    organization_id=organization_id,
                    product_code=product_code,
                    price_version=_coerce_price_version(metadata.get("price_version")),
                    currency=currency,
                    amount_minor=amount_minor_for_insert,
                    stripe_customer_id=stripe_customer_id or None,
                    status=status,
                    period_start=None,
                    period_end=None,
                    cancel_at_period_end=False,
                )
            )
        elif mode == "payment":
            order_no = f"ord_{session_id}"
            if not currency or not isinstance(amount_minor, int) or amount_minor <= 0:
                note["order_skipped"] = "missing charge amount or currency"
                return note
            price_version = _coerce_price_version(metadata.get("price_version"))
            is_paid = str(obj.get("payment_status") or "unpaid") == "paid"
            await conn.execute(
                "insert into public.payment_orders"
                " (order_no, owner_user_id, organization_id, product_code, price_version,"
                "  currency, amount_minor, status, provider, provider_session_id,"
                "  provider_payment_intent_id, paid_at)"
                " values ($1, $2, $3, $4, $5, $6, $7, $8, 'stripe', $9, $10, $11)"
                " on conflict (order_no) do update set"
                "  provider_session_id = coalesce(excluded.provider_session_id,"
                "                                 payment_orders.provider_session_id),"
                "  provider_payment_intent_id = coalesce(excluded.provider_payment_intent_id,"
                "                                 payment_orders.provider_payment_intent_id),"
                "  status = case when payment_orders.status = 'pending' then excluded.status"
                "                 else payment_orders.status end,"
                "  paid_at = case when payment_orders.paid_at is null then excluded.paid_at"
                "                  else payment_orders.paid_at end",
                order_no,
                user_id,
                organization_id,
                product_code,
                price_version,
                currency,
                amount_minor,
                "paid" if is_paid else "pending",
                session_id,
                str(obj.get("payment_intent") or "") or None,
                datetime.now(timezone.utc) if is_paid else None,
            )
            note["order_upserted"] = order_no
        else:
            note["skipped"] = f"unknown checkout mode {mode!r}"
        return note

    async def _on_subscription_mirror_event(
        self,
        conn: asyncpg.Connection,
        event_type: str,
        obj: Mapping[str, Any],
    ) -> dict[str, Any]:
        note: dict[str, Any] = {"applied": event_type}
        stripe_subscription_id = str(obj.get("id") or "")
        if not stripe_subscription_id:
            note["skipped"] = "missing subscription id"
            return note
        status = str(obj.get("status") or "active")
        if status in _STATUS_CANNOT_PROCESS:
            raise ValueError(f"subscription status {status!r} has no V1 representation")
        if event_type == "customer.subscription.deleted":
            status = "canceled"
        metadata = _mapping(obj.get("metadata"))
        user_id, organization_id, product_code = await self._metadata_scope(conn, metadata)
        currency, amount_minor = _first_line_item_price(obj)
        if not currency:
            currency = _currency(obj.get("currency"))
        stripe_customer_id = str(obj.get("customer") or "") or None
        note.update(
            await self._upsert_subscription_mirror(
                conn,
                stripe_subscription_id=stripe_subscription_id,
                user_id=user_id,
                organization_id=organization_id,
                product_code=product_code,
                price_version=_coerce_price_version(metadata.get("price_version")),
                currency=currency,
                amount_minor=amount_minor,
                stripe_customer_id=stripe_customer_id,
                status=status,
                period_start=_stripe_datetime(obj.get("current_period_start")),
                period_end=_stripe_datetime(obj.get("current_period_end")),
                cancel_at_period_end=bool(obj.get("cancel_at_period_end", False)),
            )
        )
        return note

    async def _on_invoice_paid(
        self, conn: asyncpg.Connection, obj: Mapping[str, Any]
    ) -> dict[str, Any]:
        note: dict[str, Any] = {"applied": "invoice.paid"}
        stripe_subscription_id = str(obj.get("subscription") or "")
        if not stripe_subscription_id:
            # One-time (payment-mode) invoice: reconcile the matching order.
            intent = str(obj.get("payment_intent") or "")
            if not intent:
                note["skipped"] = "invoice without subscription or payment_intent"
                return note
            updated = await conn.execute(
                "update public.payment_orders set"
                "  status = case when status in ('pending', 'paid') then 'paid' else status end,"
                "  paid_at = coalesce(paid_at, now()),"
                "  provider_payment_intent_id = coalesce(provider_payment_intent_id, $2)"
                " where provider_payment_intent_id = $1",
                intent,
                intent,
            )
            count = int(updated.split()[-1]) if updated else 0
            note["orders_marked_paid"] = count
            if count == 0:
                note["orphan"] = "no payment order matched payment_intent"
            return note

        sub = await self._existing_subscription(conn, stripe_subscription_id)
        if sub is None:
            note["orphan"] = f"unknown subscription {stripe_subscription_id}"
            return note
        await conn.execute(
            "update public.subscriptions set status = 'active'"
            " where stripe_subscription_id = $1 and status <> 'canceled'",
            stripe_subscription_id,
        )
        note["subscription_reactivated"] = stripe_subscription_id

        amount_minor = obj.get("amount_paid")
        currency = _currency(obj.get("currency"))
        intent = str(obj.get("payment_intent") or "")
        if not isinstance(amount_minor, int) or amount_minor <= 0 or not currency:
            note["order_skipped"] = "zero amount or missing currency"
            return note
        if not intent:
            note["order_skipped"] = "no payment_intent to key the order"
            return note
        user_id = _row_value(sub, "user_id")
        organization_id = _row_value(sub, "organization_id")
        order_no = f"ord_{intent}"
        await conn.execute(
            "insert into public.payment_orders"
            " (order_no, owner_user_id, organization_id, product_code, price_version,"
            "  currency, amount_minor, status, provider, provider_payment_intent_id, paid_at)"
            " values ($1, $2, $3, $4, $5, $6, $7, 'paid', 'stripe', $8, now())"
            " on conflict (order_no) do update set"
            "  provider_payment_intent_id = coalesce(excluded.provider_payment_intent_id,"
            "                                 payment_orders.provider_payment_intent_id),"
            "  status = case when payment_orders.status = 'pending' then 'paid'"
            "                 else payment_orders.status end,"
            "  paid_at = coalesce(payment_orders.paid_at, now())",
            order_no,
            user_id,
            organization_id,
            _row_value(sub, "product_code"),
            _row_value(sub, "price_version"),
            currency,
            int(amount_minor),
            intent,
        )
        note["order_upserted"] = order_no
        return note

    async def _on_invoice_payment_failed(
        self, conn: asyncpg.Connection, obj: Mapping[str, Any]
    ) -> dict[str, Any]:
        note: dict[str, Any] = {"applied": "invoice.payment_failed"}
        stripe_subscription_id = str(obj.get("subscription") or "")
        if not stripe_subscription_id:
            note["skipped"] = "invoice without subscription"
            return note
        updated = await conn.execute(
            "update public.subscriptions set status = 'past_due'"
            " where stripe_subscription_id = $1 and status in"
            " ('trialing', 'active', 'past_due', 'unpaid')",
            stripe_subscription_id,
        )
        count = int(updated.split()[-1]) if updated else 0
        note["subscriptions_past_due"] = count
        if count == 0:
            note["orphan"] = f"unknown subscription {stripe_subscription_id}"
        return note

    async def _on_refund_event(
        self, conn: asyncpg.Connection, obj: Mapping[str, Any]
    ) -> dict[str, Any]:
        note: dict[str, Any] = {"applied": "refund"}
        provider_refund_id = str(obj.get("id") or "")
        intent = str(obj.get("payment_intent") or "")
        amount_minor = obj.get("amount")
        currency = _currency(obj.get("currency"))
        raw_status = str(obj.get("status") or "pending")
        status = "failed" if raw_status == "canceled" else raw_status
        if status not in ("pending", "succeeded", "failed"):
            status = "failed"
        if not provider_refund_id or not isinstance(amount_minor, int):
            note["skipped"] = "missing refund id or amount"
            return note

        existing = await conn.fetchrow(
            "select id, order_id from public.refunds where provider_refund_id = $1",
            provider_refund_id,
        )
        if existing is not None:
            await conn.execute(
                "update public.refunds set status = $2"
                " where provider_refund_id = $1",
                provider_refund_id,
                status,
            )
            order_id = _row_value(existing, "order_id")
        else:
            if not intent:
                note["orphan"] = "unknown refund without payment_intent"
                return note
            order = await conn.fetchrow(
                "select id from public.payment_orders"
                " where provider_payment_intent_id = $1"
                " order by paid_at desc nulls last limit 1",
                intent,
            )
            if order is None:
                note["orphan"] = f"no payment order for intent {intent}"
                return note
            order_id = _row_value(order, "id")
            await conn.execute(
                "insert into public.refunds"
                " (order_id, amount_minor, currency, reason, status, provider_refund_id)"
                " values ($1, $2, $3, 'other', $4, $5)"
                " on conflict (provider_refund_id) do nothing",
                order_id,
                int(amount_minor),
                currency or "USD",
                status,
                provider_refund_id,
            )
        note["refund_synced"] = provider_refund_id
        if status == "succeeded":
            await self._recompute_order_refund_status(conn, order_id)
            note["order_refund_state_recomputed"] = True
        return note

    async def _recompute_order_refund_status(
        self, conn: asyncpg.Connection, order_id: UUID
    ) -> None:
        await conn.execute(
            "update public.payment_orders po set status ="
            "  case when coalesce((select sum(r.amount_minor) from public.refunds r"
            "                      where r.order_id = po.id"
            "                        and r.status = 'succeeded'), 0)"
            "            >= po.amount_minor then 'refunded' else 'partially_refunded' end"
            " where po.id = $1 and po.status in ('paid', 'refunded', 'partially_refunded')",
            order_id,
        )

    async def mark_provider_event_failed(
        self,
        event_id: str,
        *,
        failure_class: str,
        error_code: str,
        next_attempt_at: Optional[datetime],
    ) -> None:
        """Record a failed webhook processing attempt.

        The ``payment_events`` row is marked ``failed`` (never downgrading an
        event another worker already processed) and one append-only audit row
        (``action='billing.event.failed'``) carries the failure class, error
        code and next attempt time.  V1 has no failure columns on the event
        table, so ``next_attempt_at`` is stored in the audit summary; retry
        execution is driven by the provider redelivering after 5xx responses.
        """
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                updated = await conn.execute(
                    "update public.payment_events set status = 'failed'"
                    " where provider_event_id = $1 and status in ('received', 'failed')",
                    event_id,
                )
                await conn.execute(
                    "insert into public.audit_events"
                    " (actor_user_id, action, target_type, target_id, summary, occurred_at)"
                    " values (null, 'billing.event.failed', 'provider_event', $1, $2, now())",
                    event_id,
                    json.dumps(
                        _redact(
                            {
                                "schema_version": "billing-audit-v1",
                                "failure_class": failure_class,
                                "error_code": error_code,
                                "next_attempt_at": _iso(next_attempt_at),
                                "note": (
                                    "retry scheduling is server-side; V1 stores no attempt/"
                                    "next_attempt_at columns, so this value lives in the audit"
                                    " summary and provider redelivery drives retries"
                                ),
                            }
                        ),
                        ensure_ascii=False,
                    ),
                )
                if updated and int(updated.split()[-1]) == 0:
                    # Event may have been processed by another worker between
                    # the claim and this failure record; the audit row above
                    # still documents the failed attempt.
                    return

    # -- subscription status --------------------------------------------------

    async def get_status(self, user_id: UUID) -> BillingStatus:
        """Return the entitlement status for the user's personal subscription.

        Resolves the newest non-terminal subscription row; when every row is
        terminal the newest row is reported so a cancelled subscription is
        still visible.  Raises ``LookupError`` when the user has none.
        """
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "select * from public.subscriptions"
                    " where user_id = $1"
                    " order by created_at desc, id desc",
                    user_id,
                )
        if not rows:
            raise LookupError(f"no subscription for user {user_id}")
        row = next(
            (
                r
                for r in rows
                if _row_value(r, "status") not in ("canceled", "incomplete_expired")
            ),
            rows[0],
        )
        status = _row_value(row, "status")
        payment_status = {
            "active": "paid",
            "trialing": "paid",
            "canceled": "paid",
            "incomplete": "pending",
            "past_due": "failed",
            "unpaid": "failed",
            "incomplete_expired": "failed",
        }.get(status, "pending")
        subscription_id = _row_value(row, "stripe_subscription_id")
        if not subscription_id:
            subscription_id = str(_row_value(row, "id"))
        return BillingStatus(
            subject_id=user_id,
            product_code=_row_value(row, "product_code"),
            subscription_id=subscription_id,
            subscription_status=status,
            payment_status=payment_status,
            current_period_start=_as_utc(_row_value(row, "current_period_start")),
            current_period_end=_as_utc(_row_value(row, "current_period_end")),
            cancel_at_period_end=bool(_row_value(row, "cancel_at_period_end", False)),
            entitlement_active=status in ("active", "trialing"),
        )

    async def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
        """Return the user's cancellable subscription mirror, or ``None``."""
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "select * from public.subscriptions"
                    " where user_id = $1"
                    "   and status in ('trialing', 'active', 'past_due', 'unpaid', 'incomplete')"
                    "   and stripe_subscription_id is not null"
                    " order by created_at desc, id desc"
                    " limit 1",
                    user_id,
                )
        if row is None:
            return None
        return SubscriptionSnapshot(
            subscription_id=str(_row_value(row, "stripe_subscription_id")),
            product_code=_row_value(row, "product_code"),
            status=_row_value(row, "status"),
            cancel_at_period_end=bool(_row_value(row, "cancel_at_period_end", False)),
        )

    async def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
        """Set ``cancel_at_period_end`` on the user's current subscription."""
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "update public.subscriptions set cancel_at_period_end = $2"
                    " where user_id = $1"
                    "   and status in ('trialing', 'active', 'past_due', 'unpaid', 'incomplete')"
                    "   and stripe_subscription_id is not null"
                    "   and id = (select s.id from public.subscriptions s"
                    "             where s.user_id = $1"
                    "               and s.status in ('trialing', 'active', 'past_due',"
                    "                                'unpaid', 'incomplete')"
                    "               and s.stripe_subscription_id is not null"
                    "             order by s.created_at desc, s.id desc limit 1)",
                    user_id,
                    bool(at_period_end),
                )

    # -- refunds --------------------------------------------------------------

    async def get_refund_candidate(
        self, user_id: UUID, payment_intent_id: str
    ) -> Optional[RefundCandidate]:
        """Find a refundable charge: the user's paid order for the intent.

        ``request_id`` is the payment order id (one refund row per order).
        ``charged_at`` is the order's paid time.  ``used_entitlement`` is true
        when the charge activated a still-active subscription product (report
        orders have no entitlement rows in V1, so they read false here).
        """
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                order = await conn.fetchrow(
                    "select po.* from public.payment_orders po"
                    " where po.owner_user_id = $1"
                    "   and po.provider_payment_intent_id = $2"
                    "   and po.status in ('paid', 'refunded', 'partially_refunded')"
                    " order by po.paid_at desc nulls last, po.created_at desc"
                    " limit 1",
                    user_id,
                    payment_intent_id,
                )
                if order is None:
                    return None
                paid_at = _as_utc(_row_value(order, "paid_at")) or _as_utc(
                    _row_value(order, "created_at")
                )
                product_code = _row_value(order, "product_code")
                used_entitlement = False
                if product_code in _SUBSCRIPTION_PRODUCTS:
                    active = await conn.fetchrow(
                        "select 1 from public.subscriptions"
                        " where user_id = $1 and status in ('trialing', 'active')"
                        " limit 1",
                        user_id,
                    )
                    used_entitlement = active is not None
        order_status = _row_value(order, "status", "paid")
        candidate_status = (
            "eligible"
            if order_status == "paid"
            else order_status
            if order_status in ("refunded", "partially_refunded")
            else "ineligible"
        )
        charged_at = paid_at or datetime.now(timezone.utc)
        return RefundCandidate(
            request_id=str(_row_value(order, "id")),
            payment_intent_id=payment_intent_id,
            charged_at=charged_at,
            used_entitlement=used_entitlement,
            currency=str(_row_value(order, "currency")),
            amount_minor=int(_row_value(order, "amount_minor")),
            status=candidate_status,
        )

    async def create_refund_request(
        self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
    ) -> RefundRequest:
        """Insert one ``pending`` refund row for the candidate order.

        Reuses the newest existing refund row for the same order so repeated
        requests are idempotent (double-click guard).  Raises ``LookupError``
        when the order does not belong to the user.
        """
        order_id = _parse_uuid(candidate.request_id)
        if order_id is None:
            raise LookupError(f"invalid request_id {candidate.request_id!r}")
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                owned = await conn.fetchval(
                    "select id from public.payment_orders"
                    " where id = $1 and owner_user_id = $2",
                    order_id,
                    user_id,
                )
                if owned is None:
                    raise LookupError(f"order {order_id} not found for user {user_id}")
                existing = await conn.fetchrow(
                    "select r.*, po.provider_payment_intent_id as payment_intent_id"
                    " from public.refunds r"
                    " join public.payment_orders po on po.id = r.order_id"
                    " where r.order_id = $1"
                    " order by r.created_at desc, r.id desc"
                    " limit 1",
                    order_id,
                )
                if existing is not None:
                    return RefundRequest(
                        request_id=str(_row_value(existing, "id")),
                        payment_intent_id=str(
                            _row_value(existing, "payment_intent_id") or ""
                        ),
                        status=_row_value(existing, "status", "pending"),
                        requested_at=_as_utc(_row_value(existing, "created_at"))
                        or _as_utc(requested_at),
                        reason=_row_value(existing, "reason"),
                        provider_refund_id=_row_value(existing, "provider_refund_id"),
                    )
                refund_id = await conn.fetchval(
                    "insert into public.refunds"
                    " (order_id, amount_minor, currency, reason, status)"
                    " values ($1, $2, $3, 'customer_request', 'pending')"
                    " returning id",
                    order_id,
                    candidate.amount_minor,
                    candidate.currency,
                )
                return RefundRequest(
                    request_id=str(refund_id),
                    payment_intent_id=candidate.payment_intent_id,
                    status="pending",
                    requested_at=_as_utc(requested_at) or datetime.now(timezone.utc),
                    reason="customer_request",
                    provider_refund_id=None,
                )

    async def get_refund_request(self, request_id: str) -> RefundRequest:
        """Return a refund request row joined to its payment intent."""
        request_uuid = _parse_uuid(request_id)
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = None
                if request_uuid is not None:
                    row = await conn.fetchrow(
                        "select r.*, po.provider_payment_intent_id as payment_intent_id"
                        " from public.refunds r"
                        " join public.payment_orders po on po.id = r.order_id"
                        " where r.id = $1",
                        request_uuid,
                    )
        if row is None:
            raise LookupError(f"refund request {request_id} not found")
        return RefundRequest(
            request_id=request_id,
            payment_intent_id=str(_row_value(row, "payment_intent_id") or ""),
            status=_row_value(row, "status", "pending"),
            requested_at=_as_utc(_row_value(row, "created_at"))
            or datetime.now(timezone.utc),
            reason=_row_value(row, "reason"),
            provider_refund_id=_row_value(row, "provider_refund_id"),
        )

    async def mark_refund_succeeded(
        self, request_id: str, refund_id: str, completed_at: datetime
    ) -> None:
        """Mark a refund succeeded, store the provider id and downgrade the order.

        Runs in one transaction: the refund row and the parent order state
        move together.  ``refunds.provider_refund_id`` is unique, so a
        duplicate provider refund id surfaces as a constraint error.
        """
        request_uuid = _parse_uuid(request_id)
        if request_uuid is None:
            raise LookupError(f"invalid request_id {request_id!r}")
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "select order_id from public.refunds where id = $1", request_uuid
                )
                if row is None:
                    raise LookupError(f"refund request {request_id} not found")
                await conn.execute(
                    "update public.refunds"
                    " set status = 'succeeded', provider_refund_id = $2"
                    " where id = $1",
                    request_uuid,
                    refund_id,
                )
                await self._recompute_order_refund_status(
                    conn, _row_value(row, "order_id")
                )

    async def mark_refund_retry(
        self, request_id: str, *, error_code: str, next_attempt_at: datetime
    ) -> None:
        """Record a transient refund failure for later retry.

        The refund row stays ``pending`` (a later approval retry can still
        execute it) and an append-only audit row
        (``action='billing.refund.retry_scheduled'``) records the error code
        and the next attempt time.  V1 has no refund attempt columns, so the
        schedule is carried in the audit summary; a durable worker table is a
        later migration.  Raises ``LookupError`` when the request is unknown.
        """
        request_uuid = _parse_uuid(request_id)
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                exists = None
                if request_uuid is not None:
                    exists = await conn.fetchrow(
                        "select 1 from public.refunds where id = $1", request_uuid
                    )
                if request_uuid is None or exists is None:
                    raise LookupError(f"refund request {request_id} not found")
                await conn.execute(
                    "insert into public.audit_events"
                    " (actor_user_id, action, target_type, target_id, summary, occurred_at)"
                    " values (null, 'billing.refund.retry_scheduled', 'refund', $1, $2, now())",
                    request_id,
                    json.dumps(
                        _redact(
                            {
                                "schema_version": "billing-audit-v1",
                                "error_code": error_code,
                                "next_attempt_at": _iso(next_attempt_at),
                                "status_kept": "pending",
                                "note": (
                                    "transient provider failure; row stays pending so a later"
                                    " approval retry can execute it"
                                ),
                            }
                        ),
                        ensure_ascii=False,
                    ),
                )

    # -- audit ----------------------------------------------------------------

    async def append_audit(self, record: AuditRecord) -> None:
        """Insert one append-only audit row (single transaction)."""
        pool = self._acquire()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await self._insert_audit_row(conn, record)

    @staticmethod
    def _audit_target(record: AuditRecord) -> tuple[str, Optional[str]]:
        """Map an audit record to (target_type, target_id).

        The V1 table has a single target.  Provider object ids identify the
        Stripe-side object; otherwise the subject id is the target.  Action
        prefixes refine the target type so finance queries can find refunds,
        checkout sessions, customers and subscriptions directly.
        """
        if record.provider_object_id is not None:
            action = record.action or ""
            if "billing.refund." in action:
                return "refund", record.provider_object_id
            if "billing.checkout." in action:
                return "checkout_session", record.provider_object_id
            if "billing.portal." in action:
                return "billing_customer", record.provider_object_id
            if "billing.subscription." in action:
                return "subscription", record.provider_object_id
            return "provider_object", record.provider_object_id
        if record.subject_id is not None:
            return "subject", record.subject_id
        return "system", None

    async def _insert_audit_row(
        self,
        conn: asyncpg.Connection,
        record: AuditRecord,
        *,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> None:
        actor_id = _parse_uuid(record.actor_id)
        target_type, target_id = self._audit_target(record)
        summary: dict[str, Any] = {
            "schema_version": record.schema_version or "billing-audit-v1"
        }
        for key, value in (
            ("subject_id", record.subject_id),
            ("event_id", record.event_id),
            ("reason", record.reason),
        ):
            if value is not None:
                summary[key] = value
        summary["metadata"] = dict(record.metadata)
        if extra:
            summary.update(extra)
        occurred_at = _as_utc(record.occurred_at)
        await conn.execute(
            "insert into public.audit_events"
            " (actor_user_id, action, target_type, target_id, summary, occurred_at)"
            " values ($1, $2, $3, $4, $5, $6)",
            actor_id,
            record.action,
            target_type,
            target_id,
            json.dumps(_redact(summary), ensure_ascii=False),
            occurred_at if occurred_at is not None else datetime.now(timezone.utc),
        )
