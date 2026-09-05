"""Collection scheduler (feeder) entrypoint: enqueue due aggregate sources.

P1.3 scheduler unit 1.  Discovers the schedulable sources (every
``configs/jphouse_{23ku,osaka_wards,yokohama_wards}/<stem>.json`` config),
asks each whether it is due for a fresh weekly ``aggregate_authorized`` run on
``public.collection_runs`` (migration 20260905000601), and enqueues every due
source as a ``queued`` row with ``operator_user_id = NULL`` (a service feed) in
one transaction.  It never claims, never executes a runner, and never touches a
live website - it only feeds "local read-in" jobs that the collection worker
consumes.

Output is one JSON object per line (JSONL) - one line per source with
``source_key`` / ``action`` (``queued`` | ``skipped`` | ``due_later``) / a
stable non-PII ``reason``, mirroring ``scripts/collection_worker.py``.

Usage (from the repo root):

    DATABASE_URL=postgresql://... python3 scripts/collection_scheduler.py
    DATABASE_URL=postgresql://... python3 scripts/collection_scheduler.py --dry-run
    DATABASE_URL=postgresql://... python3 scripts/collection_scheduler.py --family jphouse_23ku
    DATABASE_URL=postgresql://... python3 scripts/collection_scheduler.py --now 2026-09-05T00:00:00Z
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.collection.scheduler import (  # noqa: E402
    FAMILY_BY_PREFIX,
    decision_to_json,
    discover_sources,
    feed_due,
    plan_due,
)
from backend.app.db import close, connect, get_pool  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enqueue due aggregate-authorised collection runs (one feed per run)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be enqueued; write nothing",
    )
    parser.add_argument(
        "--family",
        metavar="PREFIX",
        default=None,
        help="only process sources under this family prefix "
        "(one of: %s)" % ", ".join(sorted(FAMILY_BY_PREFIX)),
    )
    parser.add_argument(
        "--now",
        metavar="ISO",
        default=None,
        help="inject the scheduler clock as an ISO-8601 timestamp (UTC); "
        "default is the real wall clock. For tests / ops replay.",
    )
    return parser


def _parse_now(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit(f"--now must include a timezone offset (got {raw!r})")
    return parsed.astimezone(timezone.utc)


def _log_decision(decision, *, dry_run: bool) -> None:
    print(json.dumps(decision_to_json(decision, dry_run=dry_run), ensure_ascii=False), flush=True)


async def _run_feed(
    *,
    dry_run: bool,
    family: str | None,
    now: datetime | None,
) -> int:
    sources = discover_sources(prefix=family)
    await connect()
    try:
        async with get_pool().acquire() as conn:
            # plan_due (read-only) when dry-run, feed_due (single write
            # transaction) otherwise.  Both return every decision so the JSONL
            # contract is identical.
            decisions = await (
                plan_due(conn, sources, now=now)
                if dry_run
                else feed_due(conn, sources, now=now)
            )
            for decision in decisions:
                _log_decision(decision, dry_run=dry_run)
    finally:
        await close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _parse_now(args.now) if args.now else None
    if args.family is not None and args.family not in FAMILY_BY_PREFIX:
        raise SystemExit(
            f"--family {args.family!r} is not a schedulable family "
            f"(known: {', '.join(sorted(FAMILY_BY_PREFIX))})"
        )
    try:
        return asyncio.run(_run_feed(dry_run=args.dry_run, family=args.family, now=now))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
