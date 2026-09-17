import pytest
import json
from fastapi.testclient import TestClient
from uuid import UUID

from backend.app import main
from backend.app.main import (
    ReportSourceResolutionError,
    cached_report_action,
    namespaced_report_slug,
    report_status_for_report,
    resolve_market_source_id,
)
from backend.app.auth import AuthUser, require_user
from backend.app.main import app


def test_report_status_is_terminal_for_collected_and_empty_reports():
    assert report_status_for_report(has_snapshot=True) == "full_report"
    assert report_status_for_report(has_snapshot=False) == "insufficient_data"


def test_report_slug_is_namespaced_by_owner():
    assert namespaced_report_slug("11111111-1111-1111-1111-111111111111", "jphouse_tokyo_minato_tower") == (
        "11111111-1111-1111-1111-111111111111_jphouse_tokyo_minato_tower"
    )


class _FakeConn:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.calls = []

    async def fetchrow(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.row


@pytest.mark.asyncio
async def test_market_source_is_resolved_from_authorized_url(monkeypatch):
    main._market_source_cache = None
    conn = _FakeConn({"id": "source-from-db"})

    assert await resolve_market_source_id(conn) == "source-from-db"
    query, *args = conn.calls[0]
    assert "source_type='government_open_data'" in query
    assert "permission_status='rights_confirmed'" in query
    assert args == []


@pytest.mark.asyncio
async def test_market_source_resolution_failure_is_structured(monkeypatch):
    main._market_source_cache = None
    conn = _FakeConn(error=RuntimeError("secret database details"))

    with pytest.raises(ReportSourceResolutionError, match="market_source_unavailable") as exc_info:
        await resolve_market_source_id(conn)
    assert "secret database details" not in str(exc_info.value)
    assert exc_info.value.code == "market_source_unavailable"
    assert exc_info.value.user_message


@pytest.mark.asyncio
async def test_market_source_resolution_without_registered_row_has_safe_structured_error():
    main._market_source_cache = None
    with pytest.raises(ReportSourceResolutionError) as exc_info:
        await resolve_market_source_id(_FakeConn())
    assert exc_info.value.code == "market_source_unavailable"
    assert exc_info.value.user_message == "市场数据源暂时不可用，请稍后重试。"


def test_job_error_payload_is_structured_and_safe():
    payload = main.job_error_payload(ReportSourceResolutionError("internal lookup detail"))
    assert payload == {"code": "market_source_unavailable", "message": "市场数据源暂时不可用，请稍后重试。"}


def test_failed_job_api_returns_structured_safe_error():
    class JobConn:
        async def fetchrow(self, *_args):
            return {
                "id": "job-1", "query_key": "query-1", "status": "failed", "progress": 100,
                "current_step": "失败", "error_message": json.dumps({
                    "code": "market_source_unavailable",
                    "message": "市场数据源暂时不可用，请稍后重试。",
                }, ensure_ascii=False),
            }

    class Acquire:
        async def __aenter__(self): return JobConn()
        async def __aexit__(self, *_args): return False

    class Pool:
        def acquire(self): return Acquire()

    app.dependency_overrides[require_user] = lambda: AuthUser(UUID("00000000-0000-0000-0000-000000000041"), "user@example.test", "Member")
    old_pool = main.get_pool
    main.get_pool = lambda: Pool()
    try:
        response = TestClient(app).get("/api/jobs/job-1")
    finally:
        main.get_pool = old_pool
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["error"] == {
        "code": "market_source_unavailable",
        "message": "市场数据源暂时不可用，请稍后重试。",
    }
    assert "no rights_confirmed" not in response.text


@pytest.mark.parametrize(
    ("job_status", "report_status", "expected_action"),
    [
        ("completed", "full_report", "cache"),
        ("completed", "insufficient_data", "cache"),
        ("pending", "generating", "wait"),
        ("running", "generating", "wait"),
        ("failed", "generating", "requeue"),
        ("completed", "generating", "requeue"),
    ],
)
def test_cached_report_action_covers_published_inflight_and_stale_states(
    job_status, report_status, expected_action
):
    assert cached_report_action(job_status, report_status) == expected_action
