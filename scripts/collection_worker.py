"""Collection worker entrypoint: claim queued collection runs and execute them.

Runs one ``run_once`` round by default (claim -> execute -> record), or polls
continuously with ``--loop N`` every ``--interval`` seconds.  Output is one
JSON object per line (JSONL) with run identity and outcome only - no PII, no
exception stacks (worker error text lives on the collection_runs row, never
in logs).

Usage (from the repo root):

    DATABASE_URL=postgresql://... python3 scripts/collection_worker.py
    DATABASE_URL=postgresql://... python3 scripts/collection_worker.py --loop 60 --interval 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.collection.worker import run_once  # noqa: E402
from backend.app.db import close, connect, get_pool  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute queued collection runs (one claim per round)."
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=1,
        metavar="N",
        help="claim at most N runs across rounds (default: 1 = single round)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="pause between rounds when --loop > 1 (default: 5.0)",
    )
    return parser


def _log_line(attempt: int, report: dict | None) -> None:
    if report is None:
        payload = {"attempt": attempt, "status": "noop", "run_id": None}
    else:
        payload = {
            "attempt": attempt,
            "run_id": report["run_id"],
            "source_key": report["source_key"],
            "status": report["status"],
            "rows": report["rows"],
        }
        if report.get("snapshot_hash"):
            payload["snapshot_hash"] = report["snapshot_hash"]
        if report.get("code"):
            payload["code"] = report["code"]
    print(json.dumps(payload, ensure_ascii=False), flush=True)


async def _run_rounds(rounds: int, interval: float) -> int:
    await connect()
    try:
        for attempt in range(1, rounds + 1):
            report = await run_once(get_pool())
            _log_line(attempt, report)
            if attempt < rounds and interval > 0:
                await asyncio.sleep(interval)
    finally:
        await close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.loop < 1:
        raise SystemExit("--loop must be >= 1")
    if args.interval < 0:
        raise SystemExit("--interval must be >= 0")
    try:
        return asyncio.run(_run_rounds(args.loop, args.interval))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
