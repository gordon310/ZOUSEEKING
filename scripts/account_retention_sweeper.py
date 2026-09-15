"""Bounded execution of account deletion retention obligations.

The controlled deletion executor owns destructive/anonymizing work.  This
sweeper only verifies that completed requests meet that contract and records
the fact that the provider backup retention deadline has passed.  It never
touches ``auth.users`` or ``public.usage_events``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_LIMIT = 50
UTC = timezone.utc


@dataclass(frozen=True)
class SweepSummary:
    scanned: int = 0
    primary_due: int = 0
    backup_recorded: int = 0
    failures: int = 0


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def is_due(due_at: datetime | None, now: datetime) -> bool:
    if due_at is None:
        return False
    return _utc(due_at, "due_at") <= _utc(now, "now")


def validate_limit(limit: int) -> int:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return limit


def plan_retention_actions(row: Mapping[str, Any], now: datetime) -> tuple[str, ...]:
    actions: list[str] = []
    if is_due(row.get("primary_data_deletion_due"), now):
        actions.append("verify_primary_data")
    if is_due(row.get("backup_expiry_due"), now) and row.get("backup_expired_at") is None:
        actions.append("record_backup_expiry")
    return tuple(actions)


def run_planned_actions(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    limit: int,
    dry_run: bool,
    record_backup_expiry: Callable[[Mapping[str, Any]], bool],
) -> SweepSummary:
    validate_limit(limit)
    scanned = primary_due = backup_recorded = failures = 0
    for row in rows:
        if scanned >= limit:
            break
        scanned += 1
        actions = plan_retention_actions(row, now)
        primary_due += "verify_primary_data" in actions
        if dry_run or "record_backup_expiry" not in actions:
            continue
        try:
            backup_recorded += bool(record_backup_expiry(row))
        except Exception:
            failures += 1
    return SweepSummary(scanned, primary_due, backup_recorded, failures)


async def _candidate_rows(pool: Any, *, now: datetime, limit: int) -> list[Mapping[str, Any]]:
    async with pool.acquire() as conn:
        return list(
            await conn.fetch(
                """
                select id, primary_data_deletion_due, backup_expiry_due, backup_expired_at
                from public.account_deletion_requests
                where status = 'completed'
                  and (
                    primary_data_deletion_due <= $1
                    or (backup_expiry_due <= $1 and backup_expired_at is null)
                  )
                order by least(primary_data_deletion_due, backup_expiry_due), id
                limit $2
                """,
                _utc(now, "now"),
                validate_limit(limit),
            )
        )


async def _primary_data_is_anonymized(conn: Any, request_id: Any) -> bool:
    # The ledger's user_id is read only inside the trusted worker connection.
    user_id = await conn.fetchval(
        "select user_id from public.account_deletion_requests where id=$1 and status='completed'",
        request_id,
    )
    if user_id is None:
        return False
    profile_has_identity = await conn.fetchval(
        """
        select exists(
          select 1 from public.user_profiles
          where user_id=$1 and (email <> '' or username <> '' or display_name <> ''
            or city <> '' or favorite_area <> '' or favorite_asset_type <> '' or bio <> '')
        )
        """,
        user_id,
    )
    remaining_private_rows = await conn.fetchval(
        """
        select exists(select 1 from public.queries where owner_user_id=$1)
          or exists(select 1 from public.exports where owner_user_id=$1)
          or exists(select 1 from public.analysis_sessions where owner_user_id=$1)
          or exists(select 1 from public.organization_members where user_id=$1)
          or exists(select 1 from public.usage_quotas where scope_key=$2)
        """,
        user_id,
        f"user:{user_id}",
    )
    retained_report_has_identity = await conn.fetchval(
        "select exists(select 1 from public.property_reports where owner_user_id=$1)",
        user_id,
    )
    return not (profile_has_identity or remaining_private_rows or retained_report_has_identity)


async def _process_candidate(pool: Any, row: Mapping[str, Any], *, now: datetime, dry_run: bool) -> str:
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchrow(
                "select * from public.account_deletion_requests where id=$1 for update",
                row["id"],
            )
            if not locked or locked["status"] != "completed":
                return "stale_candidate"
            actions = plan_retention_actions(locked, now)
            if "verify_primary_data" in actions and not await _primary_data_is_anonymized(conn, locked["id"]):
                return "primary_data_verification_failed"
            if dry_run:
                return "dry_run"
            if "record_backup_expiry" in actions:
                updated = await conn.fetchval(
                    """
                    update public.account_deletion_requests
                    set backup_expired_at=$2, updated_at=now()
                    where id=$1 and status='completed' and backup_expired_at is null
                    returning id
                    """,
                    locked["id"],
                    _utc(now, "now"),
                )
                return "backup_expiry_recorded" if updated else "already_recorded"
            return "verified"


async def sweep_account_retention(
    pool: Any, *, now: datetime, limit: int = DEFAULT_LIMIT, dry_run: bool = False
) -> SweepSummary:
    validate_limit(limit)
    now = _utc(now, "now")
    rows = await _candidate_rows(pool, now=now, limit=limit)
    primary_due = backup_recorded = failures = 0
    for row in rows:
        actions = plan_retention_actions(row, now)
        primary_due += "verify_primary_data" in actions
        try:
            if await _process_candidate(pool, row, now=now, dry_run=dry_run) == "backup_expiry_recorded":
                backup_recorded += 1
        except Exception:
            failures += 1
    return SweepSummary(len(rows), primary_due, backup_recorded, failures)


def _parse_now(raw: str | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return _utc(datetime.fromisoformat(value), "--now")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sweep completed account deletion retention deadlines.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N")
    parser.add_argument("--dry-run", action="store_true", help="report due work without writing")
    parser.add_argument("--now", metavar="ISO", help="timezone-aware clock for replay/testing")
    return parser


async def _run(args: argparse.Namespace) -> int:
    from backend.app.db import close, connect, get_pool

    await connect()
    try:
        summary = await sweep_account_retention(
            get_pool(), now=_parse_now(args.now), limit=args.limit, dry_run=args.dry_run
        )
        print(json.dumps({"kind": "account_retention_sweep", **summary.__dict__}, sort_keys=True), flush=True)
        return 1 if summary.failures else 0
    finally:
        await close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_limit(args.limit)
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"account retention sweeper unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2
    except Exception:
        print("account retention sweeper unavailable: unexpected_error", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
