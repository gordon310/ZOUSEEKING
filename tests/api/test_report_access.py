"""Tests for the deep-report paywall gate (D7/D8b: account-level unlock).

The gate lives server-side in /api/reports/{query_key}: without a paid
risk_report_single order the response is locked (metadata only, content fields
never leave the server); with one, the full report is returned.
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.auth import AuthUser, optional_user, require_user
from backend.app.main import LOCKED_REPORT_FIELDS, app
from fastapi.testclient import TestClient

OWNER_ID = uuid.UUID("00000000-0000-0000-0000-000000000030")
OTHER_ID = uuid.UUID("00000000-0000-0000-0000-000000000031")
QUERY_KEY = "东京都::东京23区::渋谷区::塔楼::2026::8"


def _report_row(owner_user_id=OWNER_ID):
    return {
        "slug": "jphouse_23ku_shibuya_tower",
        "title": "东京都渋谷区塔楼成交参考",
        "publish_month": "2026年［令和8年］1～3月",
        "markdown": "# 深度报告全文",
        "xhs_content": "深度报告",
        "rental": "[]",
        "sale": '[{"layout": "1LDK", "amount_yen": 102570000}]',
        "summary": '{"title": "总而言之"}',
        "images": "[]",
        "data_sources": "[]",
        "raw_record": "{}",
        "query_key": QUERY_KEY,
        "created_at": "2026-09-11T12:00:00+00:00",
        "owner_user_id": owner_user_id,
    }


class FakeConnection:
    def __init__(self, report_row: dict | None, paid: bool, paid_key: str | None = None, subscription_quota: bool = False):
        self.report_row = report_row
        self.paid = paid
        self.paid_key = paid_key
        self.subscription_quota = subscription_quota

    async def fetchrow(self, query: str, *args):
        if "payment_orders" in query:
            if self.paid and (self.paid_key is None or args[1] == self.paid_key):
                return {"unlocked": 1}
            if self.subscription_quota:
                return {"unlocked": 1}
            return None
        return dict(self.report_row) if self.report_row is not None else None


class FakeAcquire:
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def acquire(self):
        return FakeAcquire(self._conn)


def _client(pool: FakePool, user: AuthUser | None) -> TestClient:
    if user is not None:
        app.dependency_overrides[optional_user] = lambda: user
    import backend.app.main as main

    main.get_pool = lambda: pool
    return TestClient(app)


def _cleanup() -> None:
    import backend.app.main as main

    app.dependency_overrides.clear()
    # restore nothing else; get_pool monkeypatch is per-test fresh assignment


def test_report_locked_without_paid_order():
    client = _client(FakePool(FakeConnection(_report_row(), paid=False)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 200
    body = response.json()
    assert body["locked"] is True
    assert body["unlocked"] is False
    assert body["query_key"] == QUERY_KEY
    assert body["summary"]["title"] == "总而言之"
    assert body["data_sources"] == []
    assert body["created_at"] == "2026-09-11T12:00:00+00:00"
    # content fields must not leave the server while locked
    for forbidden in LOCKED_REPORT_FIELDS:
        assert forbidden not in body
    assert "unlock_hint" in body


def test_report_unlocked_with_paid_risk_report_single():
    client = _client(FakePool(FakeConnection(_report_row(), paid=True, paid_key=QUERY_KEY)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 200
    body = response.json()
    assert body.get("locked") is None
    assert body["markdown"] == "# 深度报告全文"
    assert body["sale"][0]["amount_yen"] == 102570000


def test_report_purchase_only_unlocks_the_matching_report():
    client = _client(FakePool(FakeConnection(_report_row(), paid=True, paid_key="other-report")), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 200
    assert response.json()["locked"] is True


def test_anonymous_report_gets_free_summary_without_locked_fields():
    client = _client(FakePool(FakeConnection(_report_row(), paid=False)), None)
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 200
    body = response.json()
    assert body["unlocked"] is False
    assert body["title"] == "东京都渋谷区塔楼成交参考"
    assert body["summary"] == {"title": "总而言之"}
    assert "sale" not in body
    assert "rental" not in body
    assert "markdown" not in body


def test_active_c_plus_quota_unlocks_report_without_single_purchase():
    client = _client(FakePool(FakeConnection(_report_row(), paid=False, subscription_quota=True)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 200
    assert response.json()["markdown"] == "# 深度报告全文"


def test_exhausted_c_plus_quota_falls_back_to_single_purchase():
    client = _client(FakePool(FakeConnection(_report_row(), paid=False, subscription_quota=False)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 200
    assert response.json()["locked"] is True


def test_report_404_for_non_owner():
    client = _client(FakePool(FakeConnection(None, paid=False)), AuthUser(OTHER_ID, "other@example.com", "用户 B"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}")
    finally:
        _cleanup()
    assert response.status_code == 404
