import pytest

from backend.app import main
from backend.app.main import (
    ReportSourceResolutionError,
    cached_report_action,
    namespaced_report_slug,
    report_status_for_report,
    resolve_market_source_id,
)


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

    async def fetchrow(self, *_args):
        if self.error:
            raise self.error
        return self.row


@pytest.mark.asyncio
async def test_market_source_is_resolved_from_authorized_url(monkeypatch):
    main._market_source_cache = None
    conn = _FakeConn({"id": "source-from-db"})

    assert await resolve_market_source_id(conn) == "source-from-db"


@pytest.mark.asyncio
async def test_market_source_resolution_failure_is_structured(monkeypatch):
    main._market_source_cache = None
    conn = _FakeConn(error=RuntimeError("secret database details"))

    with pytest.raises(ReportSourceResolutionError, match="market_source_unavailable") as exc_info:
        await resolve_market_source_id(conn)
    assert "secret database details" not in str(exc_info.value)


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
