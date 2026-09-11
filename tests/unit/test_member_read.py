from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.member.routes import _period, get_member_read_store
from backend.app.member.routes import MemberReadStore


TEST_USER = AuthUser(UUID("00000000-0000-0000-0000-000000000099"), "member@example.com", "Member")
FIXED_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


class _FakeConnection:
    def __init__(self, *, profile, plan, entitlements, usage=None):
        self.profile = profile
        self.plan = plan
        self.entitlements = entitlements
        self.usage = usage or []
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
            selected = query.lower().split("from", 1)[0]
            return [
                {key: value for key, value in row.items() if key in selected}
                for row in self.usage
            ]
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
async def test_business_audience_selects_free_b_entitlements(monkeypatch):
    connection = _FakeConnection(
        profile={"membership_tier": "free", "audience": "b"},
        plan={"plan_code": "free_b", "monthly_query_limit": 30, "monthly_report_quota": 5, "subscription_slots": None, "export_rows_monthly": None},
        entitlements=[
            {"metric": "query", "period": "month", "limit_units": 30, "active": True},
            {"metric": "stats_query", "period": "month", "limit_units": 5, "active": True},
        ],
    )
    monkeypatch.setattr("backend.app.member.routes.get_pool", lambda: _FakePool(connection))

    snapshot = await MemberReadStore().get_me(TEST_USER, now=FIXED_NOW)

    assert snapshot["audience"] == "b"
    assert snapshot["entitlements"]["queries"]["limit"] == 30
    assert snapshot["entitlements"]["stats_queries"]["limit"] == 5
    assert any("pricing_plans" in query and args == ("free_b",) for query, args in connection.fetchrow_args)


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


@pytest.mark.asyncio
async def test_api_me_with_usage_rows_returns_current_consumption(monkeypatch):
    connection = _FakeConnection(
        profile={"membership_tier": "free"},
        plan={"plan_code": "free_c", "monthly_query_limit": None, "monthly_report_quota": None, "subscription_slots": None, "export_rows_monthly": None},
        entitlements=[
            {"metric": "query", "period": "day", "limit_units": 5, "active": True},
            {"metric": "stats_query", "period": "month", "limit_units": 10, "active": True},
            {"metric": "export_row", "period": "month", "limit_units": 100, "active": True},
        ],
        usage=[
            {"usage_kind": "query", "period_key": "2026-08-31", "consumed_units": 2, "limit_units": 5},
            {"usage_kind": "stats_query", "period_key": "2026-08", "consumed_units": 3, "limit_units": 10},
            {"usage_kind": "export_row", "period_key": "2026-08", "consumed_units": 4, "limit_units": 100},
        ],
    )
    monkeypatch.setattr("backend.app.member.routes.get_pool", lambda: _FakePool(connection))
    monkeypatch.setattr("backend.app.member.routes.utcnow", lambda: FIXED_NOW)

    app.dependency_overrides[require_user] = lambda: TEST_USER
    app.dependency_overrides[get_member_read_store] = lambda: MemberReadStore()
    try:
        response = TestClient(app).get("/api/me")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["entitlements"]["queries"]["used"] == 2
    assert response.json()["entitlements"]["stats_queries"]["used"] == 3
    assert response.json()["entitlements"]["exports_rows"]["used"] == 4


def test_member_read_period_switches_at_utc_plus_8_midnight() -> None:
    before = _period(datetime(2026, 8, 31, 15, 59, 59, tzinfo=timezone.utc))
    after = _period(datetime(2026, 8, 31, 16, 0, 0, tzinfo=timezone.utc))

    assert before[0] == "2026-08"
    assert after[0] == "2026-09"
    assert before[1].astimezone(timezone.utc).isoformat() == "2026-07-31T16:00:00+00:00"
    assert after[1].astimezone(timezone.utc).isoformat() == "2026-08-31T16:00:00+00:00"
