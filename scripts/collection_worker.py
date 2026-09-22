"""Collection worker entrypoint: claim queued collection runs and execute them.

Runs one ``run_once`` round by default (claim -> execute -> record), a finite
number of rounds with ``--loop N`` (``N > 0``), or continuously with
``--loop 0``.  The continuous mode exits successfully at a round boundary
after SIGTERM or SIGINT. Output is one JSON object per line (JSONL) with run
identity and outcome only - no PII, no exception stacks (worker error text
lives on the collection_runs row, never in logs).

Usage (from the repo root):

    DATABASE_URL=postgresql://... python3 scripts/collection_worker.py
    DATABASE_URL=postgresql://... python3 scripts/collection_worker.py --loop 60 --interval 10
    DATABASE_URL=postgresql://... python3 scripts/collection_worker.py --loop 0 --interval 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
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
        help=(
            "claim at most N runs across rounds; 0 = run until SIGTERM or SIGINT "
            "(default: 1 = single round)"
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="pause between rounds (default: 5.0)",
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


async def _wait_for_interval_or_stop(stop_requested: asyncio.Event, interval: float) -> None:
    if interval <= 0:
        await asyncio.sleep(0)
        return
    try:
        await asyncio.wait_for(stop_requested.wait(), timeout=interval)
    except asyncio.TimeoutError:
        pass


async def _run_rounds(rounds: int, interval: float) -> int:
    """Run finite rounds, or forever when ``rounds`` is zero.

    Signal handlers only set ``stop_requested``. They do not cancel
    ``run_once``, so an in-flight claim/execute/record cycle can finish before
    the worker closes its database pool and exits zero.
    """
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    handled_signals = (signal.SIGTERM, signal.SIGINT)
    for handled_signal in handled_signals:
        loop.add_signal_handler(handled_signal, stop_requested.set)

    await connect()
    try:
        attempt = 0
        while rounds == 0 or attempt < rounds:
            if stop_requested.is_set():
                break
            attempt += 1
            report = await run_once(get_pool())
            _log_line(attempt, report)
            if stop_requested.is_set() or (rounds > 0 and attempt == rounds):
                break
            await _wait_for_interval_or_stop(stop_requested, interval)
    finally:
        await close()
        for handled_signal in handled_signals:
            loop.remove_signal_handler(handled_signal)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.loop < 0:
        raise SystemExit("--loop must be >= 0")
    if args.interval < 0:
        raise SystemExit("--interval must be >= 0")
    try:
        return asyncio.run(_run_rounds(args.loop, args.interval))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
