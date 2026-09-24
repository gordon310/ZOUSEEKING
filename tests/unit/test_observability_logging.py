import json
import logging
import re

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app import observability


def _handlers():
    root = logging.getLogger()
    return [handler for handler in root.handlers if getattr(handler, observability._HANDLER_ATTRIBUTE, False)]


def test_configure_logging_is_idempotent_and_emits_worker_shape(caplog):
    for _ in range(3):
        observability.configure_logging("api-test")

    assert len(_handlers()) == 1
    observability.log_event(logging.getLogger("observability-test"), "tested", count=1)
    handler = _handlers()[0]
    payload = json.loads(handler.format(caplog.records[-1]))
    assert {"ts", "level", "service", "event"} <= payload.keys()
    assert payload["service"] == "api-test"
    assert payload["event"] == "tested"


def test_request_id_accepts_valid_header_and_replaces_invalid_values():
    assert observability.request_id_from_headers({"x-request-id": "trace_1.2-A"}) == "trace_1.2-A"
    for value in ("not valid", "x" * 129, ""):
        assert re.fullmatch(r"[0-9a-f]{32}", observability.request_id_from_headers({"X-Request-Id": value}))
    assert re.fullmatch(r"[0-9a-f]{32}", observability.request_id_from_headers({}))


def test_redaction_covers_tokens_emails_urls_and_nested_mapping():
    assert "jane.doe@example.co.jp" not in observability.redact("contact jane.doe@example.co.jp now")
    assert "eyJfakeToken" not in observability.redact("Bearer eyJfakeToken")
    assert "abc" not in observability.redact("https://example.test/?access_token=abc")
    assert "sk_live_example" not in observability.redact_mapping({"child": ["sk_live_example"]})["child"][0]


def test_third_party_record_keeps_redacted_message_and_logger_name():
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="HTTP Request: GET https://x/y?access_token=SECRET123 mail jane.doe@example.co.jp",
        args=(),
        exc_info=None,
    )

    payload = json.loads(observability._JsonFormatter("api-test").format(record))

    assert payload["event"] == "log"
    assert payload["logger"] == "httpx"
    assert "HTTP Request" in payload["message"]
    assert "SECRET123" not in payload["message"]
    assert "jane.doe@example.co.jp" not in payload["message"]


def test_third_party_info_is_suppressed_at_default_level(monkeypatch):
    monkeypatch.delenv("LOG_THIRD_PARTY_LEVEL", raising=False)
    observability.configure_logging("api-test")
    handler = _handlers()[0]
    info = logging.LogRecord("httpx", logging.INFO, "", 0, "diagnostic", (), None)
    warning = logging.LogRecord("httpx", logging.WARNING, "", 0, "diagnostic", (), None)

    filters = [filter_ for filter_ in handler.filters if isinstance(filter_, observability._ThirdPartyQuietFilter)]
    assert len(filters) == 1
    assert filters[0].filter(info) is False
    assert filters[0].filter(warning) is True
    assert json.loads(handler.format(warning))["event"] == "log"


def test_application_records_are_not_suppressed(monkeypatch):
    monkeypatch.delenv("LOG_THIRD_PARTY_LEVEL", raising=False)
    observability.configure_logging("api-test")
    record = logging.LogRecord("app.request", logging.INFO, "", 0, "request_completed", (), None)

    handler = _handlers()[0]
    filters = [filter_ for filter_ in handler.filters if isinstance(filter_, observability._ThirdPartyQuietFilter)]
    assert len(filters) == 1
    assert filters[0].filter(record) is True


def test_log_third_party_level_invalid_value_falls_back_to_warning(monkeypatch):
    monkeypatch.setenv("LOG_THIRD_PARTY_LEVEL", "LOUD")

    assert observability._third_party_level() == logging.WARNING


def test_failed_request_log_never_leaks_sensitive_header_or_path(caplog):
    observability.configure_logging("api-test")
    app = FastAPI()
    observability.install(app)

    @app.get("/failure")
    async def failure():
        raise HTTPException(status_code=400, detail="jane.doe@example.co.jp sk_live_example")

    response = TestClient(app).get(
        "/failure?contact=jane.doe@example.co.jp&access_token=sk_live_example",
        headers={"X-Request-Id": "request-1", "Authorization": "Bearer sk_live_example"},
    )
    assert response.status_code == 400
    output = "\n".join(_handlers()[0].format(record) for record in caplog.records)
    assert "request_failed" in output
    assert "jane.doe@example.co.jp" not in output
    assert "sk_live_example" not in output
    assert response.headers["X-Request-Id"] == "request-1"
