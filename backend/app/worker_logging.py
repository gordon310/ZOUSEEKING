"""Structured, non-sensitive logging for long-running workers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import sys
from typing import Any


_HANDLER_ATTRIBUTE = "_report_worker_json_handler"
_service = "worker"


class _JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service", self.service),
            "event": getattr(record, "event", "unstructured_log"),
        }
        for key, value in getattr(record, "structured_fields", {}).items():
            if key not in payload:
                payload[key] = value if isinstance(value, (str, int, float, bool, type(None))) else "<redacted>"
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _level_from_environment() -> int:
    return getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)


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
            return
    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_ATTRIBUTE, True)
    handler.setLevel(_level_from_environment())
    handler.setFormatter(_JsonFormatter(service))
    root.addHandler(handler)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit an allow-listed structured event without exception text or traces."""
    logger.info(event, extra={"service": _service, "event": event, "structured_fields": fields})
