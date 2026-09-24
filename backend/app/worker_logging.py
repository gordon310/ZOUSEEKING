"""Structured, non-sensitive logging for long-running workers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
from typing import Any


_HANDLER_ATTRIBUTE = "_report_worker_json_handler"
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")
_TOKEN_PATTERN = re.compile(r"\b(?:sb_[A-Za-z0-9._-]+|sk_(?:live|test)_[A-Za-z0-9._-]+|eyJ[A-Za-z0-9._-]+)\b")
_QUERY_SECRET_PATTERN = re.compile(r"([?&](?:access_token|apikey)=)[^&#\s]*", re.IGNORECASE)
_service = "worker"


def redact(value: str) -> str:
    """Remove common credentials and email addresses while retaining safe context."""
    result = _EMAIL_PATTERN.sub("<redacted>", value)
    result = _TOKEN_PATTERN.sub("<redacted>", result)
    return _QUERY_SECRET_PATTERN.sub(r"\1<redacted>", result)


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
    """Configure one stdout JSON handler, safely across repeated calls."""
    global _service
    _service = service
    root = logging.getLogger()
    root.setLevel(_level_from_environment())
    for handler in root.handlers:
        if getattr(handler, _HANDLER_ATTRIBUTE, False):
            handler.setLevel(_level_from_environment())
            handler.setFormatter(_JsonFormatter(service))
            if not any(isinstance(filter_, _ThirdPartyQuietFilter) for filter_ in handler.filters):
                handler.addFilter(_ThirdPartyQuietFilter())
            return
    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_ATTRIBUTE, True)
    handler.setLevel(_level_from_environment())
    handler.setFormatter(_JsonFormatter(service))
    handler.addFilter(_ThirdPartyQuietFilter())
    root.addHandler(handler)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit an allow-listed structured event without exception text or traces."""
    logger.info(event, extra={"service": _service, "event": event, "structured_fields": fields})
