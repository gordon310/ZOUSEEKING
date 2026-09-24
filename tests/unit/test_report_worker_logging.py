from __future__ import annotations

import asyncio
import json
import logging
import sys
from types import ModuleType
from uuid import uuid4

import pytest

from backend.app import report_worker
from backend.app import observability
from backend.app import worker_logging
from backend.app.worker_logging import configure_logging, log_event


def _json_lines(captured: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in captured.splitlines() if line]


@pytest.fixture(autouse=True)
def _remove_worker_log_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_report_worker_json_handler", False):
            root.removeHandler(handler)
            handler.close()
    yield
    for handler in list(root.handlers):
        if getattr(handler, "_report_worker_json_handler", False):
            root.removeHandler(handler)
            handler.close()


def test_configure_logging_is_idempotent_and_emits_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    configure_logging("report-worker-test")
    handler_count = len(root.handlers)
    configure_logging("report-worker-test")

    assert len(root.handlers) == handler_count
    log_event(logging.getLogger("tests.report_worker_logging"), "worker_started")

    lines = _json_lines(capsys.readouterr().out)
    assert len(lines) == 1
    assert {"ts", "level", "service", "event"} <= lines[0].keys()
    assert lines[0]["service"] == "report-worker-test"
    assert lines[0]["event"] == "worker_started"


def test_log_event_places_service_and_event_at_top_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("report-worker-test")

    log_event(logging.getLogger("tests.report_worker_logging"), "report_claimed", job_id="job-1", attempts=1)

    line = _json_lines(capsys.readouterr().out)[0]
    assert line["service"] == "report-worker-test"
    assert line["event"] == "report_claimed"
    assert line["job_id"] == "job-1"
    assert line["attempts"] == 1


def test_failure_event_does_not_serialize_exception_message(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("report-worker-test")
    failure = report_worker.classify_failure(RuntimeError("secret database payload"))

    log_event(
        logging.getLogger("tests.report_worker_logging"),
        "report_failed",
        job_id="job-1",
        error_code=failure.code,
        retryable=failure.retryable,
    )

    output = capsys.readouterr().out
    assert "secret" not in output
    line = _json_lines(output)[0]
    assert line["event"] == "report_failed"
    assert line["error_code"] == "report_generation_failed"
    assert line["retryable"] is False


def test_worker_unstructured_records_match_api_redacted_shape():
    record = logging.LogRecord(
        "httpx",
        logging.WARNING,
        "",
        0,
        "HTTP Request: GET https://x/y?access_token=SECRET123 mail jane.doe@example.co.jp",
        (),
        None,
    )

    api_payload = json.loads(observability._JsonFormatter("api-test").format(record))
    worker_payload = json.loads(worker_logging._JsonFormatter("report-worker-test").format(record))

    assert worker_payload.keys() == api_payload.keys()
    assert worker_payload["event"] == "log"
    assert worker_payload["logger"] == "httpx"
    assert "HTTP Request" in worker_payload["message"]
    assert "SECRET123" not in worker_payload["message"]
    assert "jane.doe@example.co.jp" not in worker_payload["message"]


@pytest.mark.asyncio
async def test_process_once_failure_emits_report_failed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("report-worker-test")
    claim = report_worker.ClaimedReport(
        outbox_id=uuid4(),
        generation_job_id=uuid4(),
        query_id=uuid4(),
        claim_token=uuid4(),
        payload={
            "owner_user_id": str(uuid4()),
            "prefecture": "Tokyo",
            "city": "Chiyoda",
            "year": 2026,
            "month": 9,
        },
        attempts=1,
        max_attempts=3,
        lease_expired=False,
    )

    async def claim_next(_pool: object) -> report_worker.ClaimedReport:
        return claim

    async def record_failure(_pool: object, _claim: report_worker.ClaimedReport, _failure: report_worker.Failure) -> str:
        return "failed"

    async def run_generation_job(*_args: object) -> None:
        raise RuntimeError("secret report payload")

    fake_main = ModuleType("backend.app.main")
    fake_main.run_generation_job = run_generation_job
    monkeypatch.setattr(report_worker, "claim_next", claim_next)
    monkeypatch.setattr(report_worker, "record_failure", record_failure)
    monkeypatch.setitem(sys.modules, "backend.app.main", fake_main)

    result = await report_worker.process_once(pool=object())

    assert result == {"job_id": str(claim.generation_job_id), "status": "failed", "code": "report_generation_failed"}
    output = capsys.readouterr().out
    assert "secret" not in output
    events = _json_lines(output)
    assert any(
        event["event"] == "report_failed"
        and event["job_id"] == str(claim.generation_job_id)
        and event["error_code"] == "report_generation_failed"
        and event["retryable"] is False
        and event["error_type"] == "RuntimeError"
        for event in events
    )
