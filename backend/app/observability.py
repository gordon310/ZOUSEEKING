"""Structured, redacted request logging for the FastAPI process."""

from __future__ import annotations

import contextvars
from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
import time
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request


_HANDLER_ATTRIBUTE = "_api_json_handler"
_REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_TOKEN_PATTERN = re.compile(r"\b(?:sb_[A-Za-z0-9._-]+|sk_(?:live|test)_[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._-]+)\b")
_QUERY_SECRET_PATTERN = re.compile(r"([?&](?:access_token|apikey)=)[^&#\s]*", re.IGNORECASE)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_service = "api"


def redact(value: str) -> str:
    """Remove common credentials and email addresses while retaining safe context."""
    result = _EMAIL_PATTERN.sub("<redacted>", value)
    result = _TOKEN_PATTERN.sub("<redacted>", result)
    return _QUERY_SECRET_PATTERN.sub(r"\1<redacted>", result)


def redact_mapping(mapping: Any, *, _depth: int = 0) -> Any:
    """Recursively redact values; refuse overly deep untrusted structures."""
    if _depth > 6:
        return "<redacted>"
    if isinstance(mapping, str):
        return redact(mapping)
    if isinstance(mapping, Mapping):
        return {str(key): redact_mapping(value, _depth=_depth + 1) for key, value in mapping.items()}
    if isinstance(mapping, (list, tuple)):
        return [redact_mapping(value, _depth=_depth + 1) for value in mapping]
    return mapping


class _JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service", self.service),
            "event": record.event if hasattr(record, "event") else "log",
        }
        if not hasattr(record, "event"):
            payload["logger"] = redact(record.name)
            payload["message"] = redact(record.getMessage())
        for key, value in getattr(record, "structured_fields", {}).items():
            if key not in payload:
                payload[key] = redact(value) if isinstance(value, str) else value if isinstance(value, (int, float, bool, type(None))) else "<redacted>"
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _level_from_environment() -> int:
    return getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)


def _third_party_level() -> int:
    value = os.environ.get("LOG_THIRD_PARTY_LEVEL", "WARNING").upper()
    return getattr(logging, value, logging.WARNING) if isinstance(getattr(logging, value, None), int) else logging.WARNING


class _ThirdPartyQuietFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith("app.") or getattr(record, "service", None) == _service:
            return True
        return record.levelno >= _third_party_level()


def configure_logging(service: str) -> None:
    """Configure exactly one marked stdout JSON handler."""
    global _service
    _service = service
    root = logging.getLogger()
    level = _level_from_environment()
    root.setLevel(level)
    for handler in root.handlers:
        if getattr(handler, _HANDLER_ATTRIBUTE, False):
            handler.setLevel(level)
            handler.setFormatter(_JsonFormatter(service))
            if not any(isinstance(filter_, _ThirdPartyQuietFilter) for filter_ in handler.filters):
                handler.addFilter(_ThirdPartyQuietFilter())
            return
    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_ATTRIBUTE, True)
    handler.setLevel(level)
    handler.setFormatter(_JsonFormatter(service))
    handler.addFilter(_ThirdPartyQuietFilter())
    root.addHandler(handler)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit scalar, redacted fields only; exception text is never serialized."""
    safe_fields = {
        key: redact(value) if isinstance(value, str) else value if isinstance(value, (int, float, bool, type(None))) else "<redacted>"
        for key, value in fields.items()
    }
    logger.info(event, extra={"service": _service, "event": event, "structured_fields": safe_fields})


def request_id_from_headers(headers: Mapping[str, str]) -> str:
    value = next((value for key, value in headers.items() if key.lower() == _REQUEST_ID_HEADER.lower()), "")
    return value if isinstance(value, str) and _REQUEST_ID_PATTERN.fullmatch(value) else uuid4().hex


def current_request_id() -> str | None:
    return _request_id.get()


def bind_request_id(value: str) -> contextvars.Token[str | None]:
    return _request_id.set(value)


def install(app: FastAPI) -> None:
    """Install correlation/audit middleware without configuring process logging."""
    logger = logging.getLogger("app.request")

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request_id_from_headers(request.headers)
        token = bind_request_id(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except BaseException as exc:
            log_event(
                logger,
                "request_failed",
                method=request.method,
                path=request.url.path,
                status=500,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                request_id=request_id,
                error_type=type(exc).__name__,
            )
            raise
        finally:
            _request_id.reset(token)
        response.headers[_REQUEST_ID_HEADER] = request_id
        fields = {
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "request_id": request_id,
        }
        log_event(logger, "request_completed", **fields)
        if response.status_code >= 400:
            log_event(logger, "request_failed", **fields)
        return response
