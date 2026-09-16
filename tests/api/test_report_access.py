"""Tests for the deep-report paywall gate (D7/D8b: account-level unlock).

The gate lives server-side in /api/reports/{query_key}: without a paid
risk_report_single order the response is locked (metadata only, content fields
never leave the server); with one, the full report is returned.
"""

from __future__ import annotations

import uuid
import re
from urllib.parse import quote

import pytest

from backend.app.auth import AuthUser, optional_user, require_user
from backend.app.main import LOCKED_REPORT_FIELDS, app
from fastapi import HTTPException
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
        "address": "东京都渋谷区",
        "source_period": "2026-01至2026-03",
        "limitations": "授权聚合口径；不包含挂牌价。",
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
        if "owner_user_id=$2" in query and self.report_row is not None:
            if str(self.report_row.get("owner_user_id")) != str(args[1]):
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


def _download_client(pool: FakePool, user: AuthUser | None) -> TestClient:
    import backend.app.main as main

    async def auth_override():
        if user is None:
            raise HTTPException(status_code=401, detail={"code": "auth_required", "message": "请先登录。"})
        return user

    app.dependency_overrides[require_user] = auth_override
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


def test_report_download_anonymous_is_401():
    client = _download_client(FakePool(FakeConnection(_report_row(), paid=True)), None)
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}/download")
    finally:
        _cleanup()
    assert response.status_code == 401


def test_report_download_locked_is_403_without_report_body():
    client = _download_client(FakePool(FakeConnection(_report_row(), paid=False)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}/download")
    finally:
        _cleanup()
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["code"] == "report_locked"
    response_text = response.text
    for forbidden in ("深度报告全文", "成交数据", "102570000", "markdown", "sale"):
        assert forbidden not in response_text


def test_report_download_unlocked_is_self_contained_html_attachment():
    client = _download_client(FakePool(FakeConnection(_report_row(), paid=True, paid_key=QUERY_KEY)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}/download")
    finally:
        _cleanup()
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.text.startswith("<!doctype html>")
    assert "东京都渋谷区塔楼成交参考" in response.text
    assert "成交数据" in response.text
    assert "102,570,000 日元" in response.text
    assert not __import__("re").search(r"https?://", response.text)
    for internal in ("land_right", "full_report", "insufficient_data", "generating", "risk_report_single", "report_version"):
        assert internal not in response.text


def test_report_download_never_exposes_internal_key_or_uuid_in_html_or_filename():
    row = _report_row()
    row.pop("address")
    row.pop("location", None)
    row["slug"] = f"{OWNER_ID}_jphouse_23ku_shibuya_tower"
    row["query_key"] = f"{OWNER_ID}::东京都::港区::__not_subdivided__::塔楼::2026::8"
    row.update({"prefecture": "东京都", "city": "港区", "ward": "__not_subdivided__", "asset_type": "塔楼", "year": 2026, "month": 8})
    client = _download_client(FakePool(FakeConnection(row, paid=True, paid_key=row["query_key"])), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{row['query_key']}/download")
    finally:
        _cleanup()
    assert response.status_code == 200
    assert "::" not in response.text
    assert "__not_subdivided__" not in response.text
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", response.text, re.I)
    disposition = response.headers["content-disposition"]
    assert "::" not in disposition
    assert "__not_subdivided__" not in disposition
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", disposition, re.I)
    assert quote("物件报告-东京都-港区-塔楼-2026-8.html", safe="") in disposition


def test_report_download_non_owner_is_404():
    client = _download_client(FakePool(FakeConnection(_report_row(owner_user_id=OTHER_ID), paid=True)), AuthUser(OWNER_ID, "owner@example.com", "用户 A"))
    try:
        response = client.get(f"/api/reports/{QUERY_KEY}/download")
    finally:
        _cleanup()
    assert response.status_code == 404
