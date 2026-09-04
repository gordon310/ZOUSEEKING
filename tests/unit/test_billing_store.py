"""Tests for ``backend.app.billing.store.PostgresBillingStore``.

The adapter needs the real V1 schema, so the tests apply
``20260905000100``, ``20260905000200`` and ``20260905000500`` to a
fresh disposable database named ``billing_store_test`` on the server
referenced by ``DATABASE_URL``, then exercise every ``BillingStore``
method against real PostgreSQL.

* Without ``DATABASE_URL`` the whole module is skipped.
* For safety, real-database tests only run when the ``DATABASE_URL``
  host is ``localhost`` / ``127.0.0.1`` / ``::1`` (the module never drops
  a database on a remote server).  Point ``DATABASE_URL`` at the
  disposable container when validating locally.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from backend.app.billing.ports import (
    AuditRecord,
    BillingSubject,
    OutboxAction,
    ProviderEvent,
)
from backend.app.billing.store import PostgresBillingStore

UTC = timezone.utc
FIXED_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
FIXED_NOW_ISO = "2026-08-31T12:00:00+00:00"

USER_ID = UUID("00000000-0000-0000-0000-000000000030")  # personal buyer
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000031")  # no data
ORG_USER_ID = UUID("00000000-0000-0000-0000-000000000032")  # org member
ORG_ID = UUID("00000000-0000-0000-0000-000000000040")

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260905000100_v1_organizations.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260905000200_v1_products_subscriptions.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260905000500_v1_finance_admin_audit.sql",
]

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

pytestmark = pytest.mark.asyncio


def _db_path(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _local_server(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _is_valid_test_url(url: str) -> bool:
    return bool(url) and _local_server(url)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


async def _bootstrap_and_migrate(url: str) -> None:
    """Create billing_store_test on the local server and apply the V1 batch."""
    admin = await asyncpg.connect(url, database="postgres")
    try:
        await admin.execute("drop database if exists billing_store_test with (force)")
        await admin.execute("create database billing_store_test")
    finally:
        await admin.close()

    test_url = _db_path(url, "billing_store_test")
    conn = await asyncpg.connect(test_url)
    try:
        bootstrap = """
        do $$
        begin
          if to_regrole('anon') is null then execute 'create role anon nologin'; end if;
          if to_regrole('authenticated') is null then execute 'create role authenticated nologin'; end if;
          if to_regrole('service_role') is null then execute 'create role service_role nologin'; end if;
        end $$;
        create schema if not exists auth;
        create table if not exists auth.users (
          id uuid primary key,
          email text
        );
        create or replace function auth.uid()
        returns uuid language sql stable as $$
          select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
        $$;
        create or replace function public.set_updated_at()
        returns trigger language plpgsql as $$
        begin
          new.updated_at = now();
          return new;
        end
        $$;
        """
        await conn.execute(bootstrap)
        for path in MIGRATIONS:
            await conn.execute(path.read_text(encoding="utf-8"))
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Apply the V1 migrations once to a fresh billing_store_test database."""
    if not _is_valid_test_url(DATABASE_URL):
        pytest.skip(
            "DATABASE_URL must point at a disposable local PostgreSQL server"
            " (localhost/127.0.0.1) to run the real-Postgres store tests"
        )
    asyncio.run(_bootstrap_and_migrate(DATABASE_URL))
    return _db_path(DATABASE_URL, "billing_store_test")


@pytest_asyncio.fixture
async def test_pool(_migrated_database: str) -> asyncpg.Pool:
    async def _init_jsonb(conn: asyncpg.Connection) -> None:
        # asyncpg returns jsonb as text by default; decode for assertions while
        # passing through the JSON strings the store already encodes.
        def _encode(value: object) -> object:
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

        await conn.set_type_codec(
            "jsonb",
            schema="pg_catalog",
            encoder=_encode,
            decoder=json.loads,
        )

    pool = await asyncpg.create_pool(_migrated_database, init=_init_jsonb)
    async with pool.acquire() as conn:
        for user_id, email in (
            (USER_ID, "member@example.com"),
            (OTHER_USER_ID, "other@example.com"),
            (ORG_USER_ID, "orgbuyer@example.com"),
        ):
            await conn.execute(
                "insert into auth.users (id, email) values ($1, $2)"
                " on conflict (id) do nothing",
                user_id,
                email,
            )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def store(test_pool: asyncpg.Pool) -> PostgresBillingStore:
    return PostgresBillingStore(pool=test_pool)


@pytest_asyncio.fixture(autouse=True)
async def _wipe_tables(test_pool: asyncpg.Pool) -> None:
    async with test_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "alter table public.audit_events disable trigger audit_events_no_truncate"
            )
            await conn.execute(
                "truncate table"
                " public.audit_events, public.payment_events, public.refunds,"
                " public.payment_orders, public.subscriptions,"
                " public.billing_customers, public.organization_members,"
                " public.organizations"
                " restart identity cascade"
            )
            await conn.execute(
                "alter table public.audit_events enable trigger audit_events_no_truncate"
            )


# --------------------------------------------------------------------------
# seed helpers (raw SQL set-up only; assertions always go through the store)
# --------------------------------------------------------------------------


async def seed_org(pool: asyncpg.Pool, *, org_id: UUID = ORG_ID, name: str = "Acme") -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into public.organizations (id, name) values ($1, $2)", org_id, name
        )


async def seed_membership(
    pool: asyncpg.Pool,
    *,
    user_id: UUID = ORG_USER_ID,
    org_id: UUID = ORG_ID,
    role: str = "member",
    status: str = "active",
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into public.organization_members"
            " (organization_id, user_id, role, status)"
            " values ($1, $2, $3, $4)",
            org_id,
            user_id,
            role,
            status,
        )


async def seed_customer(
    pool: asyncpg.Pool,
    *,
    user_id: UUID | None = USER_ID,
    org_id: UUID | None = None,
    customer_id: str = "cus_1",
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into public.billing_customers"
            " (owner_user_id, organization_id, stripe_customer_id)"
            " values ($1, $2, $3)",
            user_id,
            org_id,
            customer_id,
        )


async def seed_subscription(
    pool: asyncpg.Pool,
    *,
    user_id: UUID | None = USER_ID,
    org_id: UUID | None = None,
    product_code: str = "c_plus_monthly",
    stripe_subscription_id: str = "sub_1",
    status: str = "active",
    currency: str = "CNY",
    amount_minor: int = 4900,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    cancel_at_period_end: bool = False,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into public.subscriptions"
            " (user_id, organization_id, product_code, price_version, currency,"
            "  amount_minor, stripe_customer_id, stripe_subscription_id, status,"
            "  current_period_start, current_period_end, cancel_at_period_end)"
            " values ($1, $2, $3, 1, $4, $5, 'cus_1', $6, $7, $8, $9, $10)",
            user_id,
            org_id,
            product_code,
            currency,
            amount_minor,
            stripe_subscription_id,
            status,
            period_start,
            period_end,
            cancel_at_period_end,
        )


async def seed_order(
    pool: asyncpg.Pool,
    *,
    user_id: UUID = USER_ID,
    org_id: UUID | None = None,
    order_no: str = "ord_seed_1",
    product_code: str = "risk_report_single",
    currency: str = "CNY",
    amount_minor: int = 500,
    status: str = "paid",
    intent: str = "pi_seed_1",
    session: str | None = "cs_seed_1",
    paid_at: datetime = FIXED_NOW,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into public.payment_orders"
            " (order_no, owner_user_id, organization_id, product_code, price_version,"
            "  currency, amount_minor, status, provider, provider_session_id,"
            "  provider_payment_intent_id, paid_at)"
            " values ($1, $2, $3, $4, 1, $5, $6, $7, 'stripe', $8, $9, $10)",
            order_no,
            user_id,
            org_id,
            product_code,
            currency,
            amount_minor,
            status,
            session,
            intent,
            paid_at,
        )


def event_payload(
    event_id: str,
    event_type: str,
    object_: dict,
    *,
    user_id: UUID,
    product_code: str = "risk_report_single",
) -> dict:
    """Build a minimal Stripe-style webhook payload dict."""
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "metadata": {
                    "user_id": str(user_id),
                    "subject_id": str(user_id),
                    "product_code": product_code,
                    "price_version": "v1-2026-08",
                },
                **object_,
            }
        },
    }


def expected_digest(payload: dict) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# --------------------------------------------------------------------------
# subjects
# --------------------------------------------------------------------------


async def test_get_subject_user_scope(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_customer(test_pool, customer_id="cus_member")

    subject = await store.get_subject(USER_ID, "c_plus_monthly")
    assert isinstance(subject, BillingSubject)
    assert (subject.subject_type, subject.subject_id) == ("user", USER_ID)
    assert subject.stripe_customer_id == "cus_member"
    assert subject.billing_email == "member@example.com"

    # Same user scope for one-time reports; unknown user raises.
    subject_single = await store.get_subject(USER_ID, "risk_report_single")
    assert subject_single.subject_id == USER_ID
    with pytest.raises(LookupError):
        await store.get_subject(UUID("00000000-0000-0000-0000-0000000000ff"), "risk_report_single")


async def test_get_subject_organization_scope(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_org(test_pool)
    await seed_membership(test_pool)
    await seed_customer(test_pool, user_id=None, org_id=ORG_ID, customer_id="cus_org")

    subject = await store.get_subject(ORG_USER_ID, "b_data_pro_monthly")
    assert (subject.subject_type, subject.subject_id) == ("organization", ORG_ID)
    assert subject.stripe_customer_id == "cus_org"
    assert subject.billing_email is None

    # No membership and an inactive-only membership both raise LookupError.
    with pytest.raises(LookupError):
        await store.get_subject(USER_ID, "b_data_pro_monthly")
    with pytest.raises(LookupError):
        await store.get_subject(UUID("00000000-0000-0000-0000-0000000000ee"), "b_data_pro_monthly")

    # A user whose only membership is inactive resolves nothing.
    await seed_org(test_pool, org_id=UUID("00000000-0000-0000-0000-000000000041"), name="Dormant")
    await seed_membership(
        test_pool,
        user_id=OTHER_USER_ID,
        org_id=UUID("00000000-0000-0000-0000-000000000041"),
        status="inactive",
    )
    with pytest.raises(LookupError):
        await store.get_subject(OTHER_USER_ID, "b_data_pro_monthly")

    with pytest.raises(LookupError):
        await store.get_subject(USER_ID, "not_a_product")


async def test_get_portal_subject(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_customer(test_pool, customer_id="cus_portal")
    subject = await store.get_portal_subject(USER_ID)
    assert subject.subject_id == USER_ID
    assert subject.stripe_customer_id == "cus_portal"

    # No customer row yet: subject still resolves with a null customer id so
    # the service can raise its 409 "nothing to manage" conflict.
    bare = await store.get_portal_subject(ORG_USER_ID)
    assert bare.stripe_customer_id is None

    with pytest.raises(LookupError):
        await store.get_portal_subject(UUID("00000000-0000-0000-0000-0000000000ff"))


# --------------------------------------------------------------------------
# subscription status / cancel
# --------------------------------------------------------------------------


async def test_status_snapshot_and_cancel(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_subscription(
        test_pool,
        stripe_subscription_id="sub_active",
        status="active",
        period_start=FIXED_NOW - timedelta(days=10),
        period_end=FIXED_NOW + timedelta(days=20),
    )

    status = await store.get_status(USER_ID)
    assert status.subject_id == USER_ID
    assert status.product_code == "c_plus_monthly"
    assert status.subscription_id == "sub_active"
    assert status.subscription_status == "active"
    assert status.payment_status == "paid"
    assert status.entitlement_active is True
    assert status.cancel_at_period_end is False
    assert status.current_period_start == FIXED_NOW - timedelta(days=10)
    assert status.current_period_end == FIXED_NOW + timedelta(days=20)

    snapshot = await store.get_subscription(USER_ID)
    assert snapshot is not None
    assert (snapshot.subscription_id, snapshot.product_code, snapshot.status) == (
        "sub_active",
        "c_plus_monthly",
        "active",
    )

    await store.record_cancel(USER_ID, at_period_end=True)
    snapshot_after = await store.get_subscription(USER_ID)
    assert snapshot_after is not None
    assert snapshot_after.cancel_at_period_end is True
    assert (await store.get_status(USER_ID)).cancel_at_period_end is True

    # A second cancel keeps the flag true (idempotent).
    await store.record_cancel(USER_ID, at_period_end=True)
    assert (await store.get_subscription(USER_ID)).cancel_at_period_end is True


async def test_status_missing_and_terminal_rows(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    with pytest.raises(LookupError):
        await store.get_status(OTHER_USER_ID)
    assert await store.get_subscription(OTHER_USER_ID) is None

    # Only a cancelled mirror exists: reported, but not cancellable.
    await seed_subscription(test_pool, stripe_subscription_id="sub_cancelled", status="canceled")
    status = await store.get_status(USER_ID)
    assert status.subscription_status == "canceled"
    assert status.entitlement_active is False
    assert await store.get_subscription(USER_ID) is None


# --------------------------------------------------------------------------
# webhook event ledger
# --------------------------------------------------------------------------


async def test_claim_and_process_payment_checkout(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    payload = event_payload(
        "evt_pay_1",
        "checkout.session.completed",
        {
            "id": "cs_pay_1",
            "mode": "payment",
            "payment_status": "paid",
            "amount_total": 500,
            "currency": "cny",
            "customer": "cus_member",
            "payment_intent": "pi_pay_1",
        },
        user_id=USER_ID,
    )
    event = ProviderEvent("evt_pay_1", "checkout.session.completed", payload, FIXED_NOW)

    claim = await store.claim_provider_event(event)
    assert (claim.state, claim.attempt_count) == ("new", 1)

    audit = AuditRecord(
        actor_id=None,
        subject_id=str(USER_ID),
        action="billing.webhook.checkout_session_completed",
        provider_object_id="cs_pay_1",
        event_id="evt_pay_1",
        reason=None,
        metadata={"event_type": "checkout.session.completed", "status": "complete"},
        occurred_at=FIXED_NOW,
    )
    await store.process_provider_event(event, audit, None)

    # Duplicate replay of the same delivery is answered as processed.
    replay = await store.claim_provider_event(event)
    assert replay.state == "processed"

    async with test_pool.acquire() as conn:
        ledger = await conn.fetchrow(
            "select * from public.payment_events where provider_event_id = 'evt_pay_1'"
        )
        assert ledger["status"] == "processed"
        assert ledger["processed_at"] is not None
        assert ledger["payload_sha256"] == expected_digest(payload)
        assert len(ledger["payload_sha256"]) == 64

        order = await conn.fetchrow(
            "select * from public.payment_orders where order_no = 'ord_cs_pay_1'"
        )
        assert order is not None
        assert order["owner_user_id"] == USER_ID
        assert order["product_code"] == "risk_report_single"
        assert order["currency"] == "CNY"  # uppercased from the Stripe payload
        assert order["amount_minor"] == 500
        assert order["status"] == "paid"
        assert order["provider_session_id"] == "cs_pay_1"
        assert order["provider_payment_intent_id"] == "pi_pay_1"
        assert order["paid_at"] is not None

        customer = await conn.fetchrow(
            "select * from public.billing_customers where owner_user_id = $1", USER_ID
        )
        assert customer["stripe_customer_id"] == "cus_member"

        audit_row = await conn.fetchrow(
            "select summary, target_type, target_id from public.audit_events"
            " where target_type = 'provider_object' and target_id = 'cs_pay_1'"
        )
        assert audit_row is not None
        assert audit_row["summary"]["metadata"]["event_type"] == "checkout.session.completed"


async def test_claim_concurrency_window(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    payload = event_payload(
        "evt_race_1",
        "customer.subscription.deleted",
        {"id": "sub_race_1"},
        user_id=USER_ID,
    )
    event = ProviderEvent("evt_race_1", "customer.subscription.deleted", payload, FIXED_NOW)
    first = await store.claim_provider_event(event)
    assert first.state == "new"

    # Second delivery while the first owner has not processed yet.
    second = await store.claim_provider_event(event)
    assert second.state == "in_progress"

    audit = AuditRecord(
        actor_id=None,
        subject_id=str(USER_ID),
        action="billing.webhook.customer_subscription_deleted",
        provider_object_id="sub_race_1",
        event_id="evt_race_1",
        reason=None,
        metadata={"event_type": "customer.subscription.deleted", "status": "canceled"},
        occurred_at=FIXED_NOW,
    )
    await store.process_provider_event(event, audit, None)
    third = await store.claim_provider_event(event)
    assert third.state == "processed"


async def test_failed_event_claim_transient_then_dead_letter(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    transient_payload = event_payload(
        "evt_fail_t",
        "customer.subscription.deleted",
        {"id": "sub_fail_1"},
        user_id=USER_ID,
    )
    transient = ProviderEvent(
        "evt_fail_t", "customer.subscription.deleted", transient_payload, FIXED_NOW
    )
    assert (await store.claim_provider_event(transient)).state == "new"

    # Simulate a failed processing attempt exactly as the service does after
    # a raised TransientBillingError.
    await store.mark_provider_event_failed(
        "evt_fail_t",
        failure_class="transient",
        error_code="event_processing_failed",
        next_attempt_at=FIXED_NOW + timedelta(seconds=5),
    )
    retry_claim = await store.claim_provider_event(transient)
    assert retry_claim.state == "retry"
    assert retry_claim.attempt_count == 2

    audit = AuditRecord(
        actor_id=None,
        subject_id=str(USER_ID),
        action="billing.webhook.customer_subscription_deleted",
        provider_object_id="sub_fail_1",
        event_id="evt_fail_t",
        reason=None,
        metadata={"event_type": "customer.subscription.deleted"},
        occurred_at=FIXED_NOW,
    )
    await store.process_provider_event(transient, audit, None)
    assert (await store.claim_provider_event(transient)).state == "processed"

    # Permanent failure: dead-letter on replay, never retried.
    permanent_payload = event_payload(
        "evt_fail_p",
        "customer.subscription.deleted",
        {"id": "sub_fail_2"},
        user_id=USER_ID,
    )
    permanent = ProviderEvent(
        "evt_fail_p", "customer.subscription.deleted", permanent_payload, FIXED_NOW
    )
    await store.claim_provider_event(permanent)
    await store.mark_provider_event_failed(
        "evt_fail_p",
        failure_class="permanent",
        error_code="invalid_event",
        next_attempt_at=None,
    )
    dead = await store.claim_provider_event(permanent)
    assert dead.state == "dead_letter"

    async with test_pool.acquire() as conn:
        failure_audit = await conn.fetchrow(
            "select summary from public.audit_events"
            " where action = 'billing.event.failed' and target_id = 'evt_fail_t'"
        )
        assert failure_audit["summary"]["failure_class"] == "transient"
        assert failure_audit["summary"]["error_code"] == "event_processing_failed"
        assert failure_audit["summary"]["next_attempt_at"] == (
            FIXED_NOW + timedelta(seconds=5)
        ).isoformat()


async def test_subscription_created_event_inserts_mirror(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    period_end = int(FIXED_NOW.timestamp()) + 30 * 86400
    payload = event_payload(
        "evt_sub_c_1",
        "customer.subscription.created",
        {
            "id": "sub_webhook_1",
            "customer": "cus_web",
            "status": "trialing",
            "current_period_start": int(FIXED_NOW.timestamp()),
            "current_period_end": period_end,
            "cancel_at_period_end": False,
            "items": {
                "data": [
                    {
                        "price": {
                            "currency": "usd",
                            "unit_amount": 990,
                        },
                        "quantity": 1,
                    }
                ]
            },
        },
        user_id=USER_ID,
    )
    payload["data"]["object"]["metadata"] = {
        "user_id": str(USER_ID),
        "subject_id": str(USER_ID),
        "product_code": "c_plus_monthly",
        "price_version": "v1-2026-08",
    }
    event = ProviderEvent("evt_sub_c_1", "customer.subscription.created", payload, FIXED_NOW)
    await store.claim_provider_event(event)
    audit = AuditRecord(
        actor_id=None,
        subject_id=str(USER_ID),
        action="billing.webhook.customer_subscription_created",
        provider_object_id="sub_webhook_1",
        event_id="evt_sub_c_1",
        reason=None,
        metadata={"event_type": "customer.subscription.created", "status": "trialing"},
        occurred_at=FIXED_NOW,
    )
    await store.process_provider_event(event, audit, None)

    status = await store.get_status(USER_ID)
    assert status.subscription_id == "sub_webhook_1"
    assert status.subscription_status == "trialing"
    assert status.entitlement_active is True
    assert status.product_code == "c_plus_monthly"
    assert status.current_period_end == datetime.fromtimestamp(period_end, tz=UTC)


async def test_subscription_deleted_and_invoice_events(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_subscription(test_pool, stripe_subscription_id="sub_life", status="active")

    deleted = ProviderEvent(
        "evt_del_1",
        "customer.subscription.deleted",
        event_payload(
            "evt_del_1",
            "customer.subscription.deleted",
            {"id": "sub_life"},
            user_id=USER_ID,
        ),
        FIXED_NOW,
    )
    await store.claim_provider_event(deleted)
    await store.process_provider_event(
        deleted,
        AuditRecord(
            actor_id=None,
            subject_id=str(USER_ID),
            action="billing.webhook.customer_subscription_deleted",
            provider_object_id="sub_life",
            event_id="evt_del_1",
            reason=None,
            metadata={},
            occurred_at=FIXED_NOW,
        ),
        None,
    )
    assert (await store.get_status(USER_ID)).subscription_status == "canceled"

    # invoice.payment_failed marks the mirror past_due (a cancelled mirror is
    # not resurrected by the subscription id lookup ordering below: this
    # invoice is for a different subscription).
    await seed_subscription(test_pool, stripe_subscription_id="sub_pd", status="active")
    failed = ProviderEvent(
        "evt_pd_1",
        "invoice.payment_failed",
        event_payload(
            "evt_pd_1",
            "invoice.payment_failed",
            {"id": "in_1", "subscription": "sub_pd"},
            user_id=USER_ID,
        ),
        FIXED_NOW,
    )
    await store.claim_provider_event(failed)
    outbox = OutboxAction(
        kind="billing.dunning", dedupe_key="dunning:evt_pd_1", payload={}
    )
    await store.process_provider_event(
        failed,
        AuditRecord(
            actor_id=None,
            subject_id=str(USER_ID),
            action="billing.webhook.invoice_payment_failed",
            provider_object_id="in_1",
            event_id="evt_pd_1",
            reason=None,
            metadata={"event_type": "invoice.payment_failed", "status": "open"},
            occurred_at=FIXED_NOW,
        ),
        outbox,
    )
    status_pd = await store.get_status(USER_ID)
    # Newest non-terminal row for USER_ID is sub_pd (past_due).
    assert status_pd.subscription_status == "past_due"
    assert status_pd.payment_status == "failed"
    assert status_pd.entitlement_active is False

    async with test_pool.acquire() as conn:
        outbox_audit = await conn.fetchrow(
            "select summary from public.audit_events"
            " where target_id = 'in_1' and target_type = 'provider_object'"
        )
        assert outbox_audit["summary"]["outbox"]["kind"] == "billing.dunning"
        assert outbox_audit["summary"]["outbox"]["dedupe_key"] == "dunning:evt_pd_1"

    # invoice.paid restores the mirror to active and records the charge order.
    paid = ProviderEvent(
        "evt_paid_1",
        "invoice.paid",
        event_payload(
            "evt_paid_1",
            "invoice.paid",
            {
                "id": "in_2",
                "subscription": "sub_pd",
                "payment_intent": "pi_sub_charge_1",
                "amount_paid": 4900,
                "currency": "cny",
            },
            user_id=USER_ID,
        ),
        FIXED_NOW,
    )
    await store.claim_provider_event(paid)
    await store.process_provider_event(
        paid,
        AuditRecord(
            actor_id=None,
            subject_id=str(USER_ID),
            action="billing.webhook.invoice_paid",
            provider_object_id="in_2",
            event_id="evt_paid_1",
            reason=None,
            metadata={"event_type": "invoice.paid", "status": "paid"},
            occurred_at=FIXED_NOW,
        ),
        None,
    )
    assert (await store.get_status(USER_ID)).subscription_status == "active"

    async with test_pool.acquire() as conn:
        charge_order = await conn.fetchrow(
            "select * from public.payment_orders where order_no = 'ord_pi_sub_charge_1'"
        )
        assert charge_order is not None
        assert charge_order["status"] == "paid"
        assert charge_order["amount_minor"] == 4900
        assert charge_order["currency"] == "CNY"


async def test_ignored_event_marked_and_replayed(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    payload = event_payload(
        "evt_unknown_1",
        "charge.succeeded",
        {"id": "ch_1"},
        user_id=USER_ID,
    )
    event = ProviderEvent("evt_unknown_1", "charge.succeeded", payload, FIXED_NOW)
    await store.claim_provider_event(event)
    await store.process_provider_event(
        event,
        AuditRecord(
            actor_id=None,
            subject_id=None,
            action="billing.event.ignored",
            provider_object_id="ch_1",
            event_id="evt_unknown_1",
            reason=None,
            metadata={"event_type": "charge.succeeded"},
            occurred_at=FIXED_NOW,
        ),
        None,
    )
    claim = await store.claim_provider_event(event)
    assert claim.state == "processed"
    async with test_pool.acquire() as conn:
        ledger = await conn.fetchrow(
            "select status from public.payment_events where provider_event_id = 'evt_unknown_1'"
        )
        assert ledger["status"] == "ignored"


async def test_org_checkout_creates_org_customer_and_subscription(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_org(test_pool)
    await seed_membership(test_pool, user_id=ORG_USER_ID)

    payload = event_payload(
        "evt_org_1",
        "checkout.session.completed",
        {
            "id": "cs_org_1",
            "mode": "subscription",
            "payment_status": "paid",
            "amount_total": 19900,
            "currency": "cny",
            "customer": "cus_org_buy",
            "subscription": "sub_org_1",
        },
        user_id=ORG_USER_ID,
    )
    payload["data"]["object"]["metadata"] = {
        "user_id": str(ORG_USER_ID),
        "subject_id": str(ORG_ID),
        "product_code": "b_data_pro_monthly",
        "price_version": "v1-2026-08",
    }
    event = ProviderEvent("evt_org_1", "checkout.session.completed", payload, FIXED_NOW)
    await store.claim_provider_event(event)
    await store.process_provider_event(
        event,
        AuditRecord(
            actor_id=None,
            subject_id=str(ORG_ID),
            action="billing.webhook.checkout_session_completed",
            provider_object_id="cs_org_1",
            event_id="evt_org_1",
            reason=None,
            metadata={},
            occurred_at=FIXED_NOW,
        ),
        None,
    )

    async with test_pool.acquire() as conn:
        customer = await conn.fetchrow(
            "select stripe_customer_id from public.billing_customers"
            " where organization_id = $1",
            ORG_ID,
        )
        assert customer["stripe_customer_id"] == "cus_org_buy"
        subscription = await conn.fetchrow(
            "select * from public.subscriptions where stripe_subscription_id = 'sub_org_1'"
        )
        assert subscription["organization_id"] == ORG_ID
        assert subscription["user_id"] is None
        assert subscription["product_code"] == "b_data_pro_monthly"
        assert subscription["currency"] == "CNY"
        assert subscription["amount_minor"] == 19900
        assert subscription["status"] == "active"


# --------------------------------------------------------------------------
# refunds
# --------------------------------------------------------------------------


async def test_refund_full_lifecycle(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_order(test_pool, order_no="ord_ref_1", intent="pi_ref_1")

    candidate = await store.get_refund_candidate(USER_ID, "pi_ref_1")
    assert candidate is not None
    assert candidate.payment_intent_id == "pi_ref_1"
    assert candidate.currency == "CNY"
    assert candidate.amount_minor == 500
    assert candidate.status == "eligible"
    assert candidate.used_entitlement is False
    assert candidate.charged_at == FIXED_NOW

    requested = await store.create_refund_request(
        USER_ID, candidate, FIXED_NOW
    )
    assert requested.status == "pending"
    assert requested.payment_intent_id == "pi_ref_1"
    assert requested.provider_refund_id is None

    # Idempotent double-click: a second request returns the same row.
    again = await store.create_refund_request(USER_ID, candidate, FIXED_NOW)
    assert again.request_id == requested.request_id

    fetched = await store.get_refund_request(requested.request_id)
    assert fetched.request_id == requested.request_id
    assert fetched.status == "pending"

    await store.mark_refund_succeeded(requested.request_id, "re_1", FIXED_NOW)
    done = await store.get_refund_request(requested.request_id)
    assert done.status == "succeeded"
    assert done.provider_refund_id == "re_1"

    # The paid order was fully refunded.
    spent = await store.get_refund_candidate(USER_ID, "pi_ref_1")
    assert spent is not None
    assert spent.status == "refunded"
    async with test_pool.acquire() as conn:
        order = await conn.fetchrow(
            "select status from public.payment_orders where order_no = 'ord_ref_1'"
        )
        assert order["status"] == "refunded"


async def test_refund_candidate_subscription_entitlement_use(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_subscription(test_pool, stripe_subscription_id="sub_used", status="active")
    await seed_order(
        test_pool,
        order_no="ord_ref_2",
        product_code="c_plus_monthly",
        amount_minor=4900,
        intent="pi_ref_2",
    )
    candidate = await store.get_refund_candidate(USER_ID, "pi_ref_2")
    assert candidate is not None
    assert candidate.used_entitlement is True  # an active subscription exists

    # A report order for a user with no subscription reads as unused.
    report = await store.get_refund_candidate(OTHER_USER_ID, "pi_ref_2")
    assert report is None
    await seed_order(
        test_pool,
        user_id=OTHER_USER_ID,
        order_no="ord_ref_3",
        intent="pi_ref_3",
    )
    unused = await store.get_refund_candidate(OTHER_USER_ID, "pi_ref_3")
    assert unused is not None
    assert unused.used_entitlement is False

    assert await store.get_refund_candidate(USER_ID, "pi_does_not_exist") is None
    assert await store.get_refund_candidate(OTHER_USER_ID, "pi_ref_1") is None


async def test_mark_refund_retry_keeps_pending_and_audits(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_order(test_pool, order_no="ord_retry_1", intent="pi_retry_1")
    candidate = await store.get_refund_candidate(USER_ID, "pi_retry_1")
    assert candidate is not None
    request = await store.create_refund_request(USER_ID, candidate, FIXED_NOW)

    next_attempt = FIXED_NOW + timedelta(seconds=10)
    await store.mark_refund_retry(
        request.request_id, error_code="provider_transient", next_attempt_at=next_attempt
    )
    assert (await store.get_refund_request(request.request_id)).status == "pending"

    async with test_pool.acquire() as conn:
        retry_audit = await conn.fetchrow(
            "select summary from public.audit_events"
            " where action = 'billing.refund.retry_scheduled'"
            "   and target_type = 'refund' and target_id = $1",
            request.request_id,
        )
        assert retry_audit is not None
        assert retry_audit["summary"]["error_code"] == "provider_transient"
        assert retry_audit["summary"]["next_attempt_at"] == next_attempt.isoformat()

    with pytest.raises(LookupError):
        await store.mark_refund_retry(
            str(UUID("00000000-0000-0000-0000-0000000000ff")),
            error_code="x",
            next_attempt_at=FIXED_NOW,
        )


async def test_mark_refund_succeeded_unknown_request_raises(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    with pytest.raises(LookupError):
        await store.mark_refund_succeeded(
            str(UUID("00000000-0000-0000-0000-0000000000ff")), "re_x", FIXED_NOW
        )
    with pytest.raises(LookupError):
        await store.get_refund_request("not-a-uuid")


async def test_refund_events_sync_external_stripe_refund(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await seed_order(test_pool, order_no="ord_ext_1", intent="pi_ext_1")
    payload = event_payload(
        "evt_refund_1",
        "refund.created",
        {
            "id": "re_ext_1",
            "payment_intent": "pi_ext_1",
            "amount": 500,
            "currency": "cny",
            "status": "succeeded",
        },
        user_id=USER_ID,
    )
    event = ProviderEvent("evt_refund_1", "refund.created", payload, FIXED_NOW)
    await store.claim_provider_event(event)
    await store.process_provider_event(
        event,
        AuditRecord(
            actor_id=None,
            subject_id=None,
            action="billing.webhook.refund_created",
            provider_object_id="re_ext_1",
            event_id="evt_refund_1",
            reason=None,
            metadata={"event_type": "refund.created", "status": "succeeded"},
            occurred_at=FIXED_NOW,
        ),
        None,
    )
    async with test_pool.acquire() as conn:
        refund = await conn.fetchrow(
            "select * from public.refunds where provider_refund_id = 're_ext_1'"
        )
        assert refund is not None
        assert refund["status"] == "succeeded"
        assert refund["amount_minor"] == 500
        assert refund["reason"] == "other"
        order = await conn.fetchrow(
            "select status from public.payment_orders where order_no = 'ord_ext_1'"
        )
        assert order["status"] == "refunded"


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------


async def test_append_audit_redacts_and_maps_targets(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    await store.append_audit(
        AuditRecord(
            actor_id=str(USER_ID),
            subject_id=str(USER_ID),
            action="billing.checkout.created",
            provider_object_id="cs_audit_1",
            event_id=None,
            reason=None,
            metadata={
                "product_code": "risk_report_single",
                "contact": "member@example.com",
                "nested": {"email": "member@example.com", "token": "secret-value"},
            },
            occurred_at=FIXED_NOW,
        )
    )
    await store.append_audit(
        AuditRecord(
            actor_id=str(OTHER_USER_ID),
            subject_id=str(USER_ID),
            action="billing.subscription.cancel_requested",
            provider_object_id="sub_audit_1",
            event_id=None,
            reason=None,
            metadata={},
            occurred_at=FIXED_NOW,
        )
    )
    async with test_pool.acquire() as conn:
        checkout_audit = await conn.fetchrow(
            "select * from public.audit_events where target_type = 'checkout_session'"
        )
        assert checkout_audit["target_id"] == "cs_audit_1"
        assert checkout_audit["actor_user_id"] == USER_ID
        summary = checkout_audit["summary"]
        assert summary["subject_id"] == str(USER_ID)
        assert summary["schema_version"] == "billing-audit-v1"
        assert summary["metadata"]["product_code"] == "risk_report_single"
        assert "member@example.com" not in json.dumps(summary)
        assert "secret-value" not in json.dumps(summary)
        assert summary["metadata"]["contact"] == "[redacted-email]"
        assert summary["metadata"]["nested"]["email"] == "[redacted]"
        assert summary["metadata"]["nested"]["token"] == "[redacted]"

        cancel_audit = await conn.fetchrow(
            "select * from public.audit_events where target_type = 'subscription'"
        )
        assert cancel_audit["target_id"] == "sub_audit_1"


async def test_append_audit_without_timestamps_and_service_actor(
    store: PostgresBillingStore, test_pool: asyncpg.Pool
) -> None:
    # occurred_at None -> DB default now(); actor None -> NULL (service actor).
    await store.append_audit(
        AuditRecord(
            actor_id=None,
            subject_id=None,
            action="billing.refund.approved",
            provider_object_id="re_audit_1",
            event_id=None,
            reason=None,
            metadata={"request_id": "00000000-0000-0000-0000-0000000000aa"},
            occurred_at=None,
        )
    )
    async with test_pool.acquire() as conn:
        row = await conn.fetchrow(
            "select * from public.audit_events where target_id = 're_audit_1'"
        )
        assert row["occurred_at"] is not None
        assert row["actor_user_id"] is None
        assert row["target_type"] == "refund"
        assert row["summary"]["metadata"]["request_id"].endswith("aa")
