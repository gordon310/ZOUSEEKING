"""Run the single authoritative PostgreSQL-backed report worker."""

from backend.app.report_worker import run_worker
import asyncio
import os


if __name__ == "__main__":
    asyncio.run(run_worker(once=os.environ.get("REPORT_WORKER_ONCE") == "1"))
