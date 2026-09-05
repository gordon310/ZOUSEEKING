"""Collection sweeper entrypoint: stale-run recovery + snapshot-hash QA.

P1.3 质检/告警单元.  Two watchdogs over ``public.collection_runs``:

* recovery (default on): every run stuck in ``running`` past ``--stale-after``
  is flipped to ``failed`` with an explanatory ``error_message`` and an
  ``admin.collection.run_swept`` audit row, in one transaction (worker-style
  guard, ``for update skip locked`` - safe under concurrent sweepers/workers).
* hash QA (default on): the most recent succeeded jphouse runs are verified
  against their persisted snapshot files under ``data/collected/jphouse_runs/``
  (canonical fingerprint recomputed with the runner's own rule).  Read-only.

Output is one JSON object per line (JSONL) - recovery events (``kind``
``recover``) and verification verdicts (``kind`` ``verify``) - with run
identity and stable non-PII codes only.  Exit code is 0 when the sweep found
nothing abnormal and every verified snapshot matched; it is 1 when any stale
run was found (recovered or dry-run) or any snapshot failed QA, so a cron
wrapper can alert on abnormal pipeline state.

Usage (from the repo root):

    DATABASE_URL=postgresql://... python3 scripts/collection_sweep.py
    DATABASE_URL=postgresql://... python3 scripts/collection_sweep.py --dry-run
    DATABASE_URL=postgresql://... python3 scripts/collection_sweep.py --recover-only --stale-after 3600
    DATABASE_URL=postgresql://... python3 scripts/collection_sweep.py --verify-only --repo-root /path/to/repo
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.collection.sweeper import (  # noqa: E402
    DEFAULT_STALE_AFTER,
    DEFAULT_SWEEP_LIMIT,
    DEFAULT_VERIFY_LIMIT,
    REPO_ROOT,
    recover_stale_runs,
    verify_snapshot_hashes,
)
from backend.app.db import close, connect, get_pool  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover stale running collection runs and verify snapshot hashes."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--recover-only",
        action="store_true",
        help="only sweep stale 'running' runs; skip snapshot hash QA",
    )
    mode.add_argument(
        "--verify-only",
        action="store_true",
        help="only verify snapshot hashes (read-only); skip stale recovery",
    )
    parser.add_argument(
        "--stale-after",
        type=float,
        default=DEFAULT_STALE_AFTER.total_seconds(),
        metavar="SECONDS",
        help=f"a 'running' run older than this is abandoned (default:"
        f" {DEFAULT_STALE_AFTER.total_seconds():.0f}s = {DEFAULT_STALE_AFTER})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=f"max runs to recover (default: {DEFAULT_SWEEP_LIMIT}) and max"
        f" succeeded runs to verify (default: {DEFAULT_VERIFY_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report stale runs without writing anything; QA stays read-only",
    )
    parser.add_argument(
        "--now",
        metavar="ISO",
        default=None,
        help="inject the sweep clock as an ISO-8601 timestamp (UTC); default is"
        " the real wall clock. For tests / ops replay.",
    )
    parser.add_argument(
        "--repo-root",
        metavar="PATH",
        default=None,
        help="repo root used to resolve snapshot files for hash QA"
        " (default: the repository containing this script)",
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


def _log_event(event) -> None:
    print(json.dumps(event.to_json(), ensure_ascii=False), flush=True)


async def _run_sweep(
    *,
    do_recover: bool,
    do_verify: bool,
    stale_after: timedelta,
    limit: int | None,
    dry_run: bool,
    now: datetime | None,
    repo_root: Path | None,
) -> int:
    found_abnormal = False
    await connect()
    try:
        if do_recover:
            events = await recover_stale_runs(
                get_pool(),
                stale_after=stale_after,
                now=now,
                limit=limit or DEFAULT_SWEEP_LIMIT,
                dry_run=dry_run,
            )
            for event in events:
                _log_event(event)
            # A found abandoned run is abnormal regardless of dry-run.
            found_abnormal = found_abnormal or bool(events)
        if do_verify:
            events = await verify_snapshot_hashes(
                get_pool(),
                repo_root=repo_root,
                limit=limit or DEFAULT_VERIFY_LIMIT,
            )
            for event in events:
                _log_event(event)
            found_abnormal = found_abnormal or any(not event.ok for event in events)
    finally:
        await close()
    return 1 if found_abnormal else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stale_after <= 0:
        raise SystemExit("--stale-after must be a positive number of seconds")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    now = _parse_now(args.now) if args.now else None
    do_recover = not args.verify_only
    do_verify = not args.recover_only
    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT
    try:
        return asyncio.run(
            _run_sweep(
                do_recover=do_recover,
                do_verify=do_verify,
                stale_after=timedelta(seconds=args.stale_after),
                limit=args.limit,
                dry_run=args.dry_run,
                now=now,
                repo_root=repo_root,
            )
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
