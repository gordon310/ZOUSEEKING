"""Collection scheduler: decide which aggregate sources are due and enqueue them.

P1.3 scheduler unit 1.  A *feeder* (投料器): for every schedulable source it
decides whether a new ``queued`` row should be created in
``public.collection_runs`` (migration 20260905000601), and when yes, inserts
the batch in one transaction.  It never runs a runner and never reads a live
website - it only decides and enqueues "local read-in" collection jobs that
the existing :mod:`backend.app.collection.worker` will later claim and run.

Schedulable sources
-------------------
A source is every ``<stem>.json`` config under one of the three jphouse ward
family config directories (``configs/jphouse_23ku``, ``configs/jphouse_osaka_wards``,
``configs/jphouse_yokohama_wards``).  The prefix -> config-dir mapping is
*derived* from :mod:`backend.app.collection.jphouse_runners` ``FAMILIES`` so a
feed can never target a ``source_key`` the runner registry cannot execute; the
list of stems is enumerated from the directory (never hard-coded).  The
``fixture`` prefix is not a jphouse family and is therefore never schedulable.

Cadence / clock
---------------
All three families are ``aggregate_authorized`` region snapshots refreshed on a
weekly cadence (``FAMILY_CADENCE``).  ``now`` is always an injected parameter
(clock seam) so every decision is a pure function of ``(state, now)`` and tests
can drive it deterministically.

Due decision
------------
Per ``source_key`` we look at the latest terminal attempt
(status ``succeeded`` or ``failed`` - a failed run still advances the window so
a permanently failing source does not get re-fed every run and storm the
queue) plus the presence of any in-flight run (``queued``/``running``):

* no terminal attempt  -> due immediately (``no_history``);
* an in-flight run exists -> skipped (``in_flight``) - never double-feed;
* ``now - last_terminal_at >= cadence`` -> due (``due``);
* otherwise -> ``due_later`` (``within_cadence``).

``in_flight`` makes the feeder idempotent *between scheduler invocations*:
running the same scheduler twice back-to-back inserts zero duplicate rows,
because the first run leaves ``queued`` rows that the second run observes.

Persistence
-----------
Due sources are inserted with ``source_type = 'aggregate_authorized'`` and
``operator_user_id = NULL`` (a service feed, not an operator action), all in a
single transaction.  Decision logic lives in pure functions (``decide`` /
``decide_all``); all SQL lives in ``fetch_state`` / the feed transaction, so
each half is independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

import asyncpg

from backend.app.collection.jphouse_runners import FAMILIES as _JPHOUSE_FAMILIES

#: Repo root (backend/app/collection/scheduler.py -> parents[3]).
REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# cadence / source-type constants
# ---------------------------------------------------------------------------

#: Weekly refresh cadence shared by all three jphouse ward families.  Kept as
#: a constant so a future unit can evolve it to a per-family cadence without
#: touching the decision logic.
FAMILY_CADENCE = timedelta(days=7)

#: source_type stamped on every scheduler-created run row (migration allows
#: 'authorized_csv' | 'official_open' | 'partner' | 'user_submitted' |
#: 'aggregate_authorized').
FEED_SOURCE_TYPE = "aggregate_authorized"

#: Statuses that count as "an attempt" and therefore advance the due window.
#: Note: 'cancelled' is intentionally NOT included - an operator cancel does
#: not represent a collection attempt, so a cancelled-only source stays due.
WINDOW_ADVANCING = frozenset({"succeeded", "failed"})

#: Statuses that mean "a run for this source is already in flight".
INFLIGHT = frozenset({"queued", "running"})

# Decision actions emitted to callers / the CLI.
ACTION_QUEUED = "queued"
ACTION_SKIPPED = "skipped"
ACTION_DUE_LATER = "due_later"

# Human-stable reason codes (no PII) attached to each decision.
REASON_NO_HISTORY = "no_history"
REASON_DUE = "due"
REASON_IN_FLIGHT = "in_flight"
REASON_WITHIN_CADENCE = "within_cadence"


# ---------------------------------------------------------------------------
# family / source model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledFamily:
    """A schedulable family: runner prefix + its config directory."""

    prefix: str
    config_dir_rel: str
    cadence: timedelta = FAMILY_CADENCE


#: Families the scheduler feeds.  Derived from the authoritative jphouse runner
#: families (prefix -> config dir) so feeder and runner can never disagree on a
#: source_key.  ``fixture`` is excluded by construction: it has no config dir
#: and exists only for tests/self-checks.
SCHEDULED_FAMILIES: tuple[ScheduledFamily, ...] = tuple(
    ScheduledFamily(prefix=f.prefix, config_dir_rel=f.config_dir_rel)
    for f in _JPHOUSE_FAMILIES
)

FAMILY_BY_PREFIX: dict[str, ScheduledFamily] = {
    fam.prefix: fam for fam in SCHEDULED_FAMILIES
}


@dataclass(frozen=True)
class SchedulableSource:
    """One config stem under a schedulable family."""

    source_key: str  # "<prefix>/<stem>"
    prefix: str
    stem: str
    cadence: timedelta = FAMILY_CADENCE


class CollectionSchedulerError(RuntimeError):
    """Configuration error raised before any DB write (safe to surface)."""

    def __init__(self, message: str, *, code: str = "scheduler_config") -> None:
        super().__init__(message)
        self.code = code


def default_now() -> datetime:
    """UTC-aware wall clock; the default when the caller injects no ``now``."""
    return datetime.now(timezone.utc)


def _coerce_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return default_now()
    if now.tzinfo is None:
        raise CollectionSchedulerError(
            "now must be timezone-aware (UTC)", code="naive_now"
        )
    return now.astimezone(timezone.utc)


def discover_sources(
    families: Sequence[ScheduledFamily] = SCHEDULED_FAMILIES,
    *,
    prefix: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> tuple[SchedulableSource, ...]:
    """Enumerate every schedulable source from the family config directories.

    ``repo_root`` defaults to this repo; tests pass a temporary root with a
    fabricated ``configs/<family>`` tree so discovery stays a pure filesystem
    function.  ``prefix`` filters to a single family.  A family whose config
    directory is missing raises - feeding nothing silently is a footgun.
    """
    root = (repo_root or REPO_ROOT).resolve()
    sources: list[SchedulableSource] = []
    for fam in families:
        if prefix is not None and fam.prefix != prefix:
            continue
        config_dir = root / fam.config_dir_rel
        if not config_dir.is_dir():
            raise CollectionSchedulerError(
                f"[{fam.prefix}] config directory missing: {config_dir}",
                code="missing_config_dir",
            )
        for config_path in sorted(config_dir.glob("*.json")):
            stem = config_path.stem
            sources.append(
                SchedulableSource(
                    source_key=f"{fam.prefix}/{stem}",
                    prefix=fam.prefix,
                    stem=stem,
                    cadence=fam.cadence,
                )
            )
    return tuple(sources)


# ---------------------------------------------------------------------------
# decision logic (pure - no SQL, no I/O)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceState:
    """What the scheduler needs to know about a source before deciding."""

    source_key: str
    #: created_at of the most recent succeeded/failed run, else None.
    last_terminal_at: Optional[datetime]
    #: True when a queued/running run exists for this source_key.
    has_inflight: bool = False


@dataclass(frozen=True)
class FeedDecision:
    """One per-source scheduler verdict."""

    source_key: str
    action: str  # ACTION_QUEUED | ACTION_SKIPPED | ACTION_DUE_LATER
    reason: Optional[str] = None
    last_terminal_at: Optional[datetime] = None


def decide(
    source: SchedulableSource,
    state: SourceState,
    *,
    now: Optional[datetime] = None,
) -> FeedDecision:
    """Decide whether ``source`` is due for a fresh queued run at ``now``.

    Pure function: deterministic given ``(state, now)``.  Order of checks
    matches the module docstring - in-flight guard wins, then no-history,
    then cadence.
    """
    clock = _coerce_now(now)
    if state.has_inflight:
        return FeedDecision(
            source.source_key, ACTION_SKIPPED,
            reason=REASON_IN_FLIGHT, last_terminal_at=state.last_terminal_at,
        )
    last = state.last_terminal_at
    if last is None:
        return FeedDecision(
            source.source_key, ACTION_QUEUED,
            reason=REASON_NO_HISTORY, last_terminal_at=None,
        )
    if clock - last.astimezone(timezone.utc) >= source.cadence:
        return FeedDecision(
            source.source_key, ACTION_QUEUED,
            reason=REASON_DUE, last_terminal_at=last,
        )
    return FeedDecision(
        source.source_key, ACTION_DUE_LATER,
        reason=REASON_WITHIN_CADENCE, last_terminal_at=last,
    )


def decide_all(
    sources: Sequence[SchedulableSource],
    states: dict[str, SourceState],
    *,
    now: Optional[datetime] = None,
) -> tuple[FeedDecision, ...]:
    """Map each source through :func:`decide`; absent state == no history."""
    return tuple(
        decide(
            source,
            states.get(
                source.source_key,
                SourceState(source_key=source.source_key, last_terminal_at=None),
            ),
            now=now,
        )
        for source in sources
    )


# ---------------------------------------------------------------------------
# SQL layer (injected connection; decision stays in the pure functions above)
# ---------------------------------------------------------------------------


async def fetch_state(
    conn: asyncpg.Connection,
    source_keys: Sequence[str],
) -> dict[str, SourceState]:
    """Load per-source scheduler state for all ``source_keys`` in one query.

    A single grouped SELECT returns, per key that has any run row: the latest
    succeeded/failed ``created_at`` and whether any queued/running row exists.
    Keys with no rows at all are simply absent from the result (callers treat
    absence as no-history / not-in-flight).
    """
    if not source_keys:
        return {}
    rows = await conn.fetch(
        """
        select
            source_key,
            max(created_at) filter (where status = any($2::text[]))
                as last_terminal_at,
            coalesce(
                bool_or(status = any($3::text[])), false
            ) as has_inflight
        from public.collection_runs
        where source_key = any($1::text[])
        group by source_key
        """,
        list(source_keys),
        list(WINDOW_ADVANCING),
        list(INFLIGHT),
    )
    return {
        row["source_key"]: SourceState(
            source_key=row["source_key"],
            last_terminal_at=row["last_terminal_at"],
            has_inflight=bool(row["has_inflight"]),
        )
        for row in rows
    }


async def plan_due(
    conn: asyncpg.Connection,
    sources: Sequence[SchedulableSource],
    *,
    now: Optional[datetime] = None,
    source_keys: Optional[Sequence[str]] = None,
) -> tuple[FeedDecision, ...]:
    """Read state and compute decisions without writing anything (dry-run).

    Read-only; never opens a write transaction.  Returns the decisions that
    ``feed_due`` would insert (``ACTION_QUEUED``) plus the skip/due-later set.
    """
    keys = list(source_keys) if source_keys is not None else [s.source_key for s in sources]
    states = await fetch_state(conn, keys)
    return decide_all(sources, states, now=now)


async def feed_due(
    conn: asyncpg.Connection,
    sources: Sequence[SchedulableSource],
    *,
    now: Optional[datetime] = None,
    source_type: str = FEED_SOURCE_TYPE,
) -> tuple[FeedDecision, ...]:
    """Enqueue a queued row for every due source, in a single transaction.

    Returns every decision (due ones were inserted).  The read+insert run
    inside one transaction so a scheduler that re-runs *after this commit*
    sees the just-inserted ``queued`` rows as in-flight and inserts nothing
    (sequential idempotency).
    """
    async with conn.transaction():
        states = await fetch_state(conn, [s.source_key for s in sources])
        decisions = decide_all(sources, states, now=now)
        for decision in decisions:
            if decision.action == ACTION_QUEUED:
                await conn.execute(
                    "insert into public.collection_runs"
                    " (source_key, source_type, status, operator_user_id)"
                    " values ($1, $2, 'queued', null)",
                    decision.source_key,
                    source_type,
                )
    return decisions


async def run_feed(
    pool: asyncpg.Pool,
    *,
    now: Optional[datetime] = None,
    prefix: Optional[str] = None,
    dry_run: bool = False,
    source_type: str = FEED_SOURCE_TYPE,
    sources: Optional[Sequence[SchedulableSource]] = None,
) -> tuple[FeedDecision, ...]:
    """High-level entrypoint used by the CLI: discover + plan + (optionally) feed.

    ``sources`` defaults to :func:`discover_sources` filtered by ``prefix``.
    With ``dry_run=True`` nothing is written; the returned decisions still
    report ``action='queued'`` for what *would* be queued.  Never feeds the
    ``fixture`` prefix (not a scheduled family).
    """
    clock = _coerce_now(now)
    srcs = sources
    if srcs is None:
        srcs = discover_sources(prefix=prefix)
    async with pool.acquire() as conn:
        if dry_run:
            return await plan_due(conn, srcs, now=clock)
        return await feed_due(conn, srcs, now=clock, source_type=source_type)


# ---------------------------------------------------------------------------
# helper for script/test output (JSONL-safe, no PII)
# ---------------------------------------------------------------------------


def decision_to_json(decision: FeedDecision, *, dry_run: bool = False) -> dict:
    """Render one decision as a flat JSON object for JSONL output."""
    payload: dict = {
        "source_key": decision.source_key,
        "action": decision.action,
        "reason": decision.reason,
    }
    if decision.last_terminal_at is not None:
        payload["last_terminal_at"] = decision.last_terminal_at.isoformat()
    if dry_run:
        payload["dry_run"] = True
    return payload


__all__ = [
    "ACTION_DUE_LATER",
    "ACTION_QUEUED",
    "ACTION_SKIPPED",
    "CollectionSchedulerError",
    "FAMILY_BY_PREFIX",
    "FAMILY_CADENCE",
    "FEED_SOURCE_TYPE",
    "FeedDecision",
    "INFLIGHT",
    "REASON_DUE",
    "REASON_IN_FLIGHT",
    "REASON_NO_HISTORY",
    "REASON_WITHIN_CADENCE",
    "REPO_ROOT",
    "SCHEDULED_FAMILIES",
    "SchedulableSource",
    "ScheduledFamily",
    "SourceState",
    "WINDOW_ADVANCING",
    "decide",
    "decide_all",
    "decision_to_json",
    "default_now",
    "discover_sources",
    "fetch_state",
    "feed_due",
    "plan_due",
    "run_feed",
]
