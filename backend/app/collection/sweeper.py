"""Collection sweeper / QA watchdog: stale-running recovery + snapshot-hash QA.

P1.3 质检/告警单元.  The collection worker guarantees a claimed run reaches a
terminal state (``succeeded``/``failed``/``cancelled``) on the happy path, but
an operator kill, host crash or worker bug can still leave a row stuck in
``running`` forever.  A permanently ``running`` row also blocks the scheduler
feeder (``in_flight`` guard) for that source, so without a sweeper one dead
worker wedges a whole config family out of the weekly cadence.

Two watchdogs, both deliberately small and independently testable:

1. ``recover_stale_runs`` - stale-running recovery.  Any run still
   ``running`` with ``started_at <= now - stale_after`` is judged abandoned:
   the row is flipped to ``failed`` (``error_message`` explains it was swept,
   never a runner stack), ``completed_at`` is set, and an append-only
   ``audit_events`` row ``admin.collection.run_swept`` is written - all in
   one transaction, mirroring the worker's terminal-write discipline.  The
   update is guarded by ``where status = 'running'`` so an operator cancel or
   a concurrent worker terminal write that lands first always wins.
   ``stale_after`` is a deliberate safety margin: the default (6h) is far
   beyond any expected run duration so a genuinely slow live fetch is never
   swept out from under an executing worker (its later terminal write then
   becomes a no-op and it reports ``cancelled``).

   A swept run counts as a ``failed`` terminal attempt for the scheduler
   window (a crashed worker is not a source defect; the conservative window
   advance prevents queue storms and an operator can always re-enqueue from
   the back-office collection page).

2. ``verify_snapshot_hashes`` - read-only quality check over succeeded runs.
   For every succeeded ``jphouse_*`` run with a recorded ``snapshot_hash``,
   the persisted snapshot file under ``data/collected/jphouse_runs/`` is
   re-read and its canonical fingerprint recomputed with the runner's own
   canonicalisation rule (``canonical_snapshot_payload``, which excludes the
   per-run ``collected_at``).  Any mismatch / missing / unreadable file /
   row-count drift is reported as a ``VerifyEvent`` with ``ok=False``.
   Nothing is written: QA findings are for operators (the CLI exits non-zero
   so a cron wrapper can alert).

Access contract is the same as the worker: the sweeper talks to
``collection_runs`` / ``audit_events`` over the trusted (service-role/
superuser) pool; both tables are internal-domain with RLS enabled and no
anon policy.  Audit rows are written with a NULL actor (system watchdog).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Tuple

import asyncpg

from backend.app.collection.jphouse_runners import (
    FAMILY_BY_PREFIX,
    RUN_SNAPSHOT_ROOT_REL,
    canonical_snapshot_payload,
)
from backend.app.collection.worker import ERROR_MESSAGE_LIMIT

#: backend/app/collection/sweeper.py -> parents[3] == repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Audit action for a stale run recovered by the sweeper (system actor).
ACTION_SWEPT = "admin.collection.run_swept"
#: Stable failure code carried in the run's error_message and audit summary.
CODE_STALE_TIMEOUT = "stale_timeout"

#: A run is considered abandoned once it has been 'running' this long.
#: Safety margin far above any expected collection duration (see module
#: docstring); operators may lower it via the CLI for recovery drills.
DEFAULT_STALE_AFTER = timedelta(hours=6)

#: Default cap for one sweep batch (bound the transaction / lock window).
DEFAULT_SWEEP_LIMIT = 50

#: Default cap for the read-only hash verification pass.
DEFAULT_VERIFY_LIMIT = 200

#: Safe stem characters must mirror the runner's source_key contract
#: (jphouse_runners._STEM_RE) so path resolution can never escape the
#: snapshot root via traversal.
_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Recovery event actions.
ACTION_RECOVERED = "recovered"
ACTION_DRY_RUN = "dry_run"

# Snapshot verification verdict codes.
VERIFY_OK = "hash_ok"
VERIFY_HASH_MISMATCH = "hash_mismatch"
VERIFY_ROWS_MISMATCH = "rows_mismatch"
VERIFY_FILE_MISSING = "file_missing"
VERIFY_FILE_UNREADABLE = "file_unreadable"


def _coerce_now(now: Optional[datetime]) -> datetime:
    """UTC-aware clock for the sweep decision (injected or wall clock)."""
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (UTC)")
    return now.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryEvent:
    """One stale-running recovery decision."""

    run_id: str
    source_key: str
    action: str  # ACTION_RECOVERED | ACTION_DRY_RUN
    started_at: Optional[str]
    stale_after_seconds: int
    #: A recovery is the expected watchdog action (ok); an abandoned run was
    #: still found, which the CLI treats as an anomaly worth alerting on.
    ok: bool = True

    def to_json(self) -> dict:
        payload: dict = {
            "kind": "recover",
            "run_id": self.run_id,
            "source_key": self.source_key,
            "action": self.action,
            "stale_after_seconds": self.stale_after_seconds,
        }
        if self.started_at is not None:
            payload["started_at"] = self.started_at
        return payload


@dataclass(frozen=True)
class VerifyEvent:
    """One snapshot-hash QA verdict for a succeeded run."""

    run_id: str
    source_key: str
    code: str
    snapshot_rel: Optional[str]
    recorded_hash: Optional[str]
    computed_hash: Optional[str]
    recorded_rows: Optional[int]
    file_rows: Optional[int]
    ok: bool

    def to_json(self) -> dict:
        payload: dict = {
            "kind": "verify",
            "run_id": self.run_id,
            "source_key": self.source_key,
            "code": self.code,
            "ok": self.ok,
        }
        for key, value in (
            ("snapshot_rel", self.snapshot_rel),
            ("recorded_hash", self.recorded_hash),
            ("computed_hash", self.computed_hash),
            ("recorded_rows", self.recorded_rows),
            ("file_rows", self.file_rows),
        ):
            if value is not None:
                payload[key] = value
        return payload


# ---------------------------------------------------------------------------
# snapshot path resolution + pure file verification (no DB)
# ---------------------------------------------------------------------------


def snapshot_rel_for_source(source_key: str) -> Optional[str]:
    """Map a run's ``source_key`` to its snapshot file path (repo-relative).

    Only registered jphouse config-family keys map to a file-backed snapshot
    (``data/collected/jphouse_runs/<prefix>/<stem>.json``); the ``fixture``
    runner and any unknown prefix produce no on-disk snapshot and therefore
    return None (not verifiable / out of scope for the file QA).
    """
    prefix, sep, stem = source_key.partition("/")
    if (
        sep != "/"
        or not stem
        or "/" in stem
        or not _STEM_RE.match(stem)
        or prefix not in FAMILY_BY_PREFIX
    ):
        return None
    return f"{RUN_SNAPSHOT_ROOT_REL}/{prefix}/{stem}.json"


def verify_snapshot_file(
    path: Path,
    recorded_hash: Optional[str],
    recorded_rows: Optional[int] = None,
) -> dict:
    """Recompute the canonical fingerprint of one on-disk snapshot file.

    Pure filesystem check (no DB): reads ``path``, strips the per-run
    ``collected_at`` exactly like the runner did when it recorded the hash,
    and returns a verdict dict::

        {"code": <VERIFY_*>, "computed_hash": str | None, "file_rows": int | None}

    ``code`` is ``hash_ok`` only when the recomputed fingerprint equals the
    recorded one *and* the recorded ``rows_collected`` matches the snapshot's
    row count (when both are present).  Missing/unreadable files never raise
    - they are reported as ``file_missing`` / ``file_unreadable`` findings.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"code": VERIFY_FILE_MISSING, "computed_hash": None, "file_rows": None}
    except OSError:
        return {"code": VERIFY_FILE_UNREADABLE, "computed_hash": None, "file_rows": None}

    try:
        snapshot = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return {"code": VERIFY_FILE_UNREADABLE, "computed_hash": None, "file_rows": None}
    if not isinstance(snapshot, Mapping):
        return {"code": VERIFY_FILE_UNREADABLE, "computed_hash": None, "file_rows": None}

    rows = snapshot.get("rows")
    file_rows = len(rows) if isinstance(rows, list) else None
    digest = hashlib.sha256(canonical_snapshot_payload(snapshot)).hexdigest()

    expected = (recorded_hash or "").strip().lower()
    if expected and digest != expected:
        return {
            "code": VERIFY_HASH_MISMATCH,
            "computed_hash": digest,
            "file_rows": file_rows,
        }
    if recorded_rows is not None and file_rows is not None and file_rows != recorded_rows:
        return {
            "code": VERIFY_ROWS_MISMATCH,
            "computed_hash": digest,
            "file_rows": file_rows,
        }
    return {
        "code": VERIFY_OK,
        "computed_hash": digest,
        "file_rows": file_rows,
    }


# ---------------------------------------------------------------------------
# SQL layer (trusted pool, worker-style discipline)
# ---------------------------------------------------------------------------


async def recover_stale_runs(
    pool: asyncpg.Pool,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    now: Optional[datetime] = None,
    limit: int = DEFAULT_SWEEP_LIMIT,
    dry_run: bool = False,
) -> Tuple[RecoveryEvent, ...]:
    """Sweep abandoned ``running`` runs to ``failed`` (+ audit), or dry-run.

    Candidates are ``running`` rows whose ``started_at`` is older than
    ``stale_after``.  With ``dry_run=True`` nothing is written - every
    candidate is reported with ``action='dry_run'``.  Otherwise all flips and
    their audit rows happen in one transaction; rows are pinned with
    ``for update skip locked`` so concurrent sweepers split the batch and can
    never double-recover (the second sweeper no longer sees a matching
    ``running`` row after the first commits).  A row whose state changed
    between the SELECT and the guarded UPDATE is left untouched.
    """
    clock = _coerce_now(now)
    cutoff = clock - stale_after
    seconds = int(stale_after.total_seconds())
    if seconds <= 0:
        raise ValueError("stale_after must be a positive timedelta")

    events: list[RecoveryEvent] = []
    selector = (
        "select id, source_key, started_at"
        " from public.collection_runs"
        " where status = 'running' and started_at is not null"
        "   and started_at <= $1"
        " order by started_at asc, id asc"
        " limit $2"
    )

    async with pool.acquire() as conn:
        if dry_run:
            rows = await conn.fetch(selector, cutoff, limit)
            for row in rows:
                events.append(
                    RecoveryEvent(
                        run_id=str(row["id"]),
                        source_key=row["source_key"],
                        action=ACTION_DRY_RUN,
                        started_at=row["started_at"].isoformat(),
                        stale_after_seconds=seconds,
                    )
                )
            return tuple(events)

        async with conn.transaction():
            rows = await conn.fetch(selector + " for update skip locked", cutoff, limit)
            for row in rows:
                message = (
                    f"[swept] run stayed 'running' for >={seconds}s"
                    f" (started_at {row['started_at'].isoformat()});"
                    " no terminal state recorded by the worker"
                )
                updated = await conn.fetchval(
                    "update public.collection_runs"
                    " set status = 'failed', error_message = $2, completed_at = now()"
                    " where id = $1 and status = 'running'"
                    " returning id",
                    row["id"],
                    message[:ERROR_MESSAGE_LIMIT],
                )
                if updated is None:
                    # Concurrent worker terminal write / operator cancel won
                    # between SELECT and UPDATE - not ours to recover.
                    continue
                await conn.execute(
                    "insert into public.audit_events"
                    " (action, target_type, target_id, summary)"
                    " values ($1, 'collection_run', $2, $3::jsonb)",
                    ACTION_SWEPT,
                    str(row["id"]),
                    json.dumps(
                        {
                            "source_key": row["source_key"],
                            "code": CODE_STALE_TIMEOUT,
                            "status": "failed",
                            "stale_after_seconds": seconds,
                            "started_at": row["started_at"].isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                )
                events.append(
                    RecoveryEvent(
                        run_id=str(row["id"]),
                        source_key=row["source_key"],
                        action=ACTION_RECOVERED,
                        started_at=row["started_at"].isoformat(),
                        stale_after_seconds=seconds,
                    )
                )
    return tuple(events)


async def verify_snapshot_hashes(
    pool: asyncpg.Pool,
    *,
    repo_root: Optional[Path] = None,
    limit: int = DEFAULT_VERIFY_LIMIT,
) -> Tuple[VerifyEvent, ...]:
    """Verify recorded snapshot hashes against the persisted snapshot files.

    Read-only.  The most recent ``limit`` succeeded runs that carry a
    ``snapshot_hash`` are checked; only file-backed jphouse config-family
    source_keys are verifiable, the rest are skipped by construction
    (``snapshot_rel_for_source`` returns None - fixture runs have no file).
    Files are resolved under ``repo_root`` (default: the repo root) so tests
    can point at a fabricated ``data/collected/`` tree.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select id, source_key, rows_collected, snapshot_hash"
            " from public.collection_runs"
            " where status = 'succeeded' and snapshot_hash is not null"
            " order by created_at desc, id desc"
            " limit $1",
            limit,
        )

    events: list[VerifyEvent] = []
    for row in rows:
        rel = snapshot_rel_for_source(row["source_key"])
        if rel is None:
            continue
        recorded_hash = (row["snapshot_hash"] or "").strip().lower() or None
        verdict = verify_snapshot_file(
            root / rel, recorded_hash, row["rows_collected"]
        )
        ok = verdict["code"] == VERIFY_OK
        events.append(
            VerifyEvent(
                run_id=str(row["id"]),
                source_key=row["source_key"],
                code=verdict["code"],
                snapshot_rel=rel,
                recorded_hash=recorded_hash,
                computed_hash=verdict["computed_hash"],
                recorded_rows=row["rows_collected"],
                file_rows=verdict["file_rows"],
                ok=ok,
            )
        )
    return tuple(events)


__all__ = [
    "ACTION_DRY_RUN",
    "ACTION_RECOVERED",
    "ACTION_SWEPT",
    "CODE_STALE_TIMEOUT",
    "DEFAULT_STALE_AFTER",
    "DEFAULT_SWEEP_LIMIT",
    "DEFAULT_VERIFY_LIMIT",
    "REPO_ROOT",
    "RecoveryEvent",
    "VERIFY_FILE_MISSING",
    "VERIFY_FILE_UNREADABLE",
    "VERIFY_HASH_MISMATCH",
    "VERIFY_OK",
    "VERIFY_ROWS_MISMATCH",
    "VerifyEvent",
    "recover_stale_runs",
    "snapshot_rel_for_source",
    "verify_snapshot_file",
    "verify_snapshot_hashes",
]
