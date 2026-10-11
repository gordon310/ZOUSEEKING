"""Offline regression tests for the trusted live-quota boundary.

Real transaction/unique-index behavior is covered separately by
``tests/integration/test_current_quota_postgres.py``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from backend.app.auth import AuthUser
from backend.app.usage.ledger import QuotaExceeded
from backend.app.usage.quota import consume_current_entitlement, select_live_entitlement

USER = AuthUser(UUID("00000000-0000-0000-0000-000000000030"), "", "")
SCOPE = f"user:{USER.user_id}"


class ScriptedConnection:
    def __init__(self, rows, *, in_transaction=True):
        self.rows = list(rows)
        self.in_transaction = in_transaction
        self.calls = []

    def is_in_transaction(self):
        return self.in_transaction

    async def execute(self, sql, *args):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return "OK"

    async def fetchrow(self, sql, *args):
        sql = " ".join(sql.split())
        self.calls.append(("fetchrow", sql, args))
        expected, result = self.rows.pop(0)
        assert expected in sql
        return result


def consume(conn, **kwargs):
    return asyncio.run(consume_current_entitlement(
        conn, user=USER, metric="report", units=1,
        idempotency_key="report:one", fingerprint="report:one", **kwargs,
    ))


def report_rows(*, limit=1, consumed=0, reserved=0):
    return [
        ("from public.usage_idempotency", None),
        ("from public.usage_events", None),
        ("from public.subscriptions", {"id": uuid4()}),
        ("from public.plan_entitlements", {"limit_units": limit, "period": "month"}),
        ("from public.usage_quotas", {"id": uuid4(), "consumed_units": consumed, "reserved_units": reserved, "limit_units": limit}),
        ("set consumed_units=consumed_units", {"consumed_units": consumed + 1, "reserved_units": reserved, "limit_units": limit}),
    ]


def test_report_consumption_uses_personal_subscription_not_profile_or_organization():
    conn = ScriptedConnection(report_rows())
    result = consume(conn)
    assert (result.status, result.used, result.limit, result.remaining) == ("consumed", 1, 1, 0)
    assert not conn.rows
    assert all("user_profiles" not in sql and "organization_members" not in sql for _, sql, _ in conn.calls)
    subscription = next(sql for _, sql, _ in conn.calls if "from public.subscriptions" in sql)
    assert "status in ('active', 'trialing')" in subscription
    assert "current_period_end > now()" in subscription
    assert "current_period_start <= now()" in subscription
    assert "current_period_end is null" not in subscription
    entitlement = next(args for _, sql, args in conn.calls if "from public.plan_entitlements" in sql)
    assert entitlement == ("c_plus", "report", "month")


def test_report_quota_rejects_organization_or_other_user_scope():
    for scope in (f"org:{uuid4()}", f"user:{uuid4()}"):
        conn = ScriptedConnection([])
        with pytest.raises(ValueError, match="authenticated user's scope"):
            consume(conn, scope_key=scope)
        assert not conn.calls


def test_missing_or_inactive_or_expired_subscription_does_not_mutate_quota():
    conn = ScriptedConnection(report_rows()[:2] + [("from public.subscriptions", None)])
    with pytest.raises(QuotaExceeded, match="active report subscription"):
        consume(conn)
    assert all("insert into" not in sql and "update public" not in sql for _, sql, _ in conn.calls)


@pytest.mark.parametrize("limit,consumed,reserved", [(0, 0, 0), (1, 1, 0), (1, 0, 1), (1, 2, 0)])
def test_zero_exhausted_reserved_or_downgraded_quota_does_not_consume(limit, consumed, reserved):
    conn = ScriptedConnection(report_rows(limit=limit, consumed=consumed, reserved=reserved))
    with pytest.raises(QuotaExceeded):
        consume(conn)
    assert all("insert into public.usage_events" not in sql and "insert into public.usage_idempotency" not in sql for _, sql, _ in conn.calls)
    assert all("set consumed_units" not in sql for _, sql, _ in conn.calls)


def test_remaining_excludes_reserved_units():
    conn = ScriptedConnection(report_rows(limit=3, reserved=1))
    result = consume(conn)
    assert result.remaining == 1


@pytest.mark.parametrize("actor", [USER.user_id, None])
def test_report_replay_returns_original_month_without_checking_subscription(actor):
    conn = ScriptedConnection([
        ("from public.usage_idempotency", {"fingerprint": "report:one"}),
        ("from public.usage_events", {"period_key": "2026-09", "units": 1, "actor_user_id": actor}),
        ("from public.usage_quotas", {"consumed_units": 12, "reserved_units": 0, "limit_units": 12}),
    ])
    result = consume(conn)
    assert (result.status, result.period_key, result.used) == ("duplicate", "2026-09", 12)
    assert all("from public.subscriptions" not in sql and "insert into" not in sql for _, sql, _ in conn.calls)


def test_same_fingerprint_with_new_key_returns_duplicate_without_registry_write():
    conn = ScriptedConnection([
        ("from public.usage_idempotency", None),
        ("from public.usage_events", {"period_key": "2026-09", "units": 1, "actor_user_id": USER.user_id}),
        ("from public.usage_quotas", {"consumed_units": 1, "reserved_units": 0, "limit_units": 12}),
    ])
    assert consume(conn).status == "duplicate"
    assert all("insert into" not in sql for _, sql, _ in conn.calls)


def test_reused_key_with_different_fingerprint_is_conflict():
    conn = ScriptedConnection([("from public.usage_idempotency", {"fingerprint": "report:other"})])
    with pytest.raises(ValueError, match="idempotency key was reused"):
        consume(conn)


@pytest.mark.parametrize("units,actor", [(0, USER.user_id), (2, USER.user_id), (1, UUID(int=99))])
def test_report_replay_rejects_wrong_units_or_actor(units, actor):
    conn = ScriptedConnection([
        ("from public.usage_idempotency", {"fingerprint": "report:one"}),
        ("from public.usage_events", {"period_key": "2026-09", "units": units, "actor_user_id": actor}),
    ])
    with pytest.raises(ValueError, match="fingerprint was reused"):
        consume(conn)


def test_orphaned_idempotency_registry_does_not_count_as_successful_consume():
    conn = ScriptedConnection([
        ("from public.usage_idempotency", {"fingerprint": "report:one"}),
        ("from public.usage_events", None),
    ])
    with pytest.raises(ValueError, match="no matching usage event"):
        consume(conn)


def test_transaction_is_required_before_any_database_operation():
    conn = ScriptedConnection([], in_transaction=False)
    with pytest.raises(ValueError, match="requires an open transaction"):
        consume(conn)
    assert not conn.calls


@pytest.mark.parametrize("metric", ["query", "free_preview"])
@pytest.mark.parametrize("plan,period", [("free_c", "day"), ("c_plus", "month")])
def test_query_and_preview_follow_same_live_plan_period(metric, plan, period):
    rows = [
        ("from public.user_profiles", {"membership_tier": plan, "audience": "c"}),
        ("from public.organization_members", None),
        *report_rows(),
    ]
    rows.pop(4)  # Query metrics do not use the report-only subscription gate.
    rows[4] = ("from public.plan_entitlements", {"limit_units": 3, "period": period})
    conn = ScriptedConnection(rows)
    result = asyncio.run(consume_current_entitlement(
        conn, user=USER, metric=metric, units=1,
        idempotency_key="query:one", fingerprint="query:one",
    ))
    assert len(result.period_key) == (10 if period == "day" else 7)
    args = next(args for _, sql, args in conn.calls if "from public.plan_entitlements" in sql)
    assert args == (plan, "query", None)
    lock = next(args[0] for _, sql, args in conn.calls if "pg_advisory_xact_lock" in sql)
    assert lock == f"quota:{SCOPE}:query"


def test_future_dated_entitlement_is_not_current():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = [
        {"metric": "report", "period": "month", "limit_units": 12, "active": True, "effective_from": datetime(2026, 9, 1, tzinfo=timezone.utc)},
        {"metric": "report", "period": "month", "limit_units": 1000, "active": True, "effective_from": datetime(2026, 11, 1, tzinfo=timezone.utc)},
    ]
    assert select_live_entitlement(rows, "report", "month", now=now) == 12
