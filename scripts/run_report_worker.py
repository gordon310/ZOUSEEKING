"""Run the single authoritative PostgreSQL-backed report worker."""

import asyncio
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.report_worker import run_worker
from backend.app.worker_logging import configure_logging, log_event


if __name__ == "__main__":
    configure_logging("report-worker")
    logger = logging.getLogger(__name__)
    log_event(logger, "worker_started")
    try:
        asyncio.run(run_worker(once=os.environ.get("REPORT_WORKER_ONCE") == "1"))
    finally:
        log_event(logger, "worker_stopped")
