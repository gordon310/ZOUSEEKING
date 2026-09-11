from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.app.auth import AuthUser
from backend.app.member.routes import _period
from backend.app.member.routes import MemberReadStore


TEST_USER = AuthUser(UUID("00000000-0000-0000-0000-000000000099"), "member@example.com", "Member")
FIXED_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


class _FakeConnection:
    def __init__(self, *, profile, plan, entitlements):
        self.profile = profile
        self.plan = plan
        self.entitlements = entitlements
        self.queries = []
        self.fetchrow_args = []

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        self.fetchrow_args.append((query, args))
        if "user_profiles" in query:
            return self.profile
        if "pricing_plans" in query:
            return self.plan
        if "subscriptions" in query:
            return None
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def fetch(self, query, *args):
        self.queries.append(query)
        if "plan_entitlements" in query:
            return self.entitlements
        if "usage_quotas" in query:
            return []
        raise AssertionError(f"unexpected fetch query: {query}")


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return None


class _FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_missing_profile_still_reads_free_c_db_entitlements(monkeypatch):
    connection = _FakeConnection(
        profile=None,
        plan={"plan_code": "free_c", "monthly_query_limit": None, "monthly_report_quota": None, "subscription_slots": None, "export_rows_monthly": None},
        entitlements=[{"metric": "query", "period": "day", "limit_units": 5, "active": True}],
    )
    monkeypatch.setattr("backend.app.member.routes.get_pool", lambda: _FakePool(connection))

    snapshot = await MemberReadStore().get_usage_summary(TEST_USER, now=FIXED_NOW)

    assert snapshot["entitlements"]["queries"]["limit"] == 5
    assert any("plan_entitlements" in query for query in connection.queries)
    assert any("pricing_plans" in query and args == ("free_c",) for query, args in connection.fetchrow_args)


@pytest.mark.asyncio
async def test_empty_db_entitlements_use_code_default(monkeypatch):
    connection = _FakeConnection(
        profile={"membership_tier": ""},
        plan={"plan_code": "free_c", "monthly_query_limit": None, "monthly_report_quota": None, "subscription_slots": None, "export_rows_monthly": None},
        entitlements=[],
    )
    monkeypatch.setattr("backend.app.member.routes.get_pool", lambda: _FakePool(connection))

    snapshot = await MemberReadStore().get_usage_summary(TEST_USER, now=FIXED_NOW)

    assert snapshot["entitlements"]["queries"]["limit"] == 3


@pytest.mark.asyncio
async def test_plan_entitlements_override_legacy_pricing_columns(monkeypatch):
    connection = _FakeConnection(
        profile={"membership_tier": "free"},
        plan={"plan_code": "free_c", "monthly_query_limit": 99, "monthly_report_quota": None, "subscription_slots": None, "export_rows_monthly": None},
        entitlements=[{"metric": "query", "period": "month", "limit_units": 7, "active": True}],
    )
    monkeypatch.setattr("backend.app.member.routes.get_pool", lambda: _FakePool(connection))

    snapshot = await MemberReadStore().get_usage_summary(TEST_USER, now=FIXED_NOW)

    assert snapshot["entitlements"]["queries"]["limit"] == 7


@pytest.mark.asyncio
async def test_day_entitlement_is_primary_when_day_and_month_are_configured(monkeypatch):
    connection = _FakeConnection(
        profile={"membership_tier": "free"},
        plan={"plan_code": "free_c", "monthly_query_limit": 99, "monthly_report_quota": None, "subscription_slots": None, "export_rows_monthly": None},
        entitlements=[
            {"metric": "query", "period": "day", "limit_units": 3, "active": True},
            {"metric": "query", "period": "month", "limit_units": 20, "active": True},
        ],
    )
    monkeypatch.setattr("backend.app.member.routes.get_pool", lambda: _FakePool(connection))

    snapshot = await MemberReadStore().get_usage_summary(TEST_USER, now=FIXED_NOW)

    assert snapshot["entitlements"]["queries"]["limit"] == 3
    assert snapshot["entitlements"]["queries"]["period"] == "day"
    assert snapshot["entitlements"]["queries"]["periods"] == {"day": 3, "month": 20}


def test_member_read_period_switches_at_utc_plus_8_midnight() -> None:
    before = _period(datetime(2026, 8, 31, 15, 59, 59, tzinfo=timezone.utc))
    after = _period(datetime(2026, 8, 31, 16, 0, 0, tzinfo=timezone.utc))

    assert before[0] == "2026-08"
    assert after[0] == "2026-09"
    assert before[1].astimezone(timezone.utc).isoformat() == "2026-07-31T16:00:00+00:00"
    assert after[1].astimezone(timezone.utc).isoformat() == "2026-08-31T16:00:00+00:00"
