"""Real collection runners for the three ``configs/jphouse_*`` families.

Registered (by :mod:`backend.app.collection.worker`) into ``RUNNER_REGISTRY``
under the prefixes:

* ``jphouse_23ku``        -> ``configs/jphouse_23ku/<stem>.json``
* ``jphouse_osaka_wards`` -> ``configs/jphouse_osaka_wards/<stem>.json``
* ``jphouse_yokohama_wards`` -> ``configs/jphouse_yokohama_wards/<stem>.json``

Runner protocol
---------------
Each prefix resolves to an async runner ``run(source_key, source_type) ->
worker.CollectionOutcome``.  The runner:

1. parses ``source_key = "<prefix>/<config-stem>"`` and resolves the matching
   config json under the family's ``configs/`` directory (repo-relative);
2. executes one collection *data read-in* via a collector callable that is
   separated from the deterministic output so tests can inject fixtures;
3. persists a per-source run snapshot under
   ``data/collected/jphouse_runs/<prefix>/<stem>.json`` (atomic replace) and
   returns ``rows_collected`` + a lowercase-hex sha256 ``snapshot_hash`` that
   are both consistent with the persisted snapshot.

Collector seam / live collection scope
--------------------------------------
The *default* collector (``collect_local_readin``) reads the source's already
collected numeric snapshot from ``data/collected/<family>_sources.json`` and
rebuilds the value rows from the numeric fields (never from presentation
strings), following the migration comment: raw payloads never live on the run
row.  Source URLs and the recorded source periods are carried from the config
and the aggregate record.

Live web fetching/parsing for these SUUMO/Tochidai pages is intentionally NOT
wired as the default collector yet: direct third-party collection still needs
the documented authorization/terms review and stored parser fixtures.  When
that is ready, a later unit supplies a collector that performs the fetch+parse
and returns the same ``CollectResult`` shape; the runner/registry/snapshot
mechanics tested here are unchanged.

Failure mapping
---------------
Failures raise ``worker.CollectionRunError`` with a stable ``code``
(``bad_source_key``, ``config_missing``, ``config_invalid``,
``aggregate_missing``, ``aggregate_invalid``, ``aggregate_entry_missing``) so
``run_once`` records a failed run with a filterable code instead of leaving the
run hanging or crashing the worker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Mapping, MutableMapping, Optional, Tuple

# backend/app/collection/jphouse_runners.py -> parents[3] == repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Per-source run snapshots written by these runners (repo-relative).
RUN_SNAPSHOT_ROOT_REL = "data/collected/jphouse_runs"

# Version of the read-in/parser pipeline producing the snapshot rows.  Bump
# only when the numeric interpretation changes (the run ledger records it).
PARSER_VERSION = "jphouse-local-readin-v1"
SNAPSHOT_FORMAT = "jphouse-run-v1"

# Stable ordering for the layout matrix used by the collection scripts.
LAYOUTS = ("1LDK", "2LDK", "3LDK")

# Config identity used as the source_key stem (safe path segment).
_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class JphouseFamily:
    """Static mapping from a registered prefix to its config + snapshot roots."""

    prefix: str
    config_dir_rel: str
    aggregate_rel: str
    label_ja: str


FAMILIES = (
    JphouseFamily(
        prefix="jphouse_23ku",
        config_dir_rel="configs/jphouse_23ku",
        aggregate_rel="data/collected/jphouse_23ku_sources.json",
        label_ja="东京23区",
    ),
    JphouseFamily(
        prefix="jphouse_osaka_wards",
        config_dir_rel="configs/jphouse_osaka_wards",
        aggregate_rel="data/collected/jphouse_osaka_wards_sources.json",
        label_ja="大阪市各区",
    ),
    JphouseFamily(
        prefix="jphouse_yokohama_wards",
        config_dir_rel="configs/jphouse_yokohama_wards",
        aggregate_rel="data/collected/jphouse_yokohama_wards_sources.json",
        label_ja="横浜市各区",
    ),
)
FAMILY_BY_PREFIX = {family.prefix: family for family in FAMILIES}


@dataclass(frozen=True)
class CollectResult:
    """What one collection read-in produced (decoupled from persistence)."""

    rows: Tuple[dict, ...]
    meta: Mapping[str, object] = field(default_factory=dict)


# Collector: (family, config-stem, config dict, repo_root) -> CollectResult.
Collector = Callable[[JphouseFamily, str, dict, Path], CollectResult]
Clock = Callable[[], str]


def _numeric(value: object) -> Optional[float]:
    """Return a numeric value (never a bool/string), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _rows_from_ward_record(record: dict) -> Tuple[dict, ...]:
    """Rebuild deterministic value rows from the numeric collected record.

    Numeric values only - never parsed from presentation strings (AGENTS data
    rules).  Rents are 万日元/月, sale ``layout_price_man_yen`` are total 万日元.
    Layouts missing a numeric sample are skipped (kept consistent with the
    collection scripts' "暂无样本" policy of not inventing values).
    """
    rows: list[dict] = []
    rents = record.get("rents")
    if isinstance(rents, dict):
        for layout in LAYOUTS:
            value = _numeric(rents.get(layout))
            if value is not None:
                rows.append(
                    {
                        "metric": "rent",
                        "layout": layout,
                        "value_man_yen": value,
                        "unit": "man_yen_per_month",
                    }
                )
    sale = record.get("sale")
    if isinstance(sale, dict):
        prices = sale.get("layout_price_man_yen")
        if isinstance(prices, dict):
            for layout in LAYOUTS:
                value = _numeric(prices.get(layout))
                if value is not None:
                    rows.append(
                        {
                            "metric": "sale_price",
                            "layout": layout,
                            "value_man_yen": value,
                            "unit": "man_yen",
                        }
                    )
    return tuple(rows)


def _aggregate_entries(data: object) -> list:
    """Normalise a family aggregate file (list or ``{"collected": [...]}``)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("collected"), list):
        return data["collected"]
    return []


def collect_local_readin(
    family: JphouseFamily, stem: str, config: dict, repo_root: Path
) -> CollectResult:
    """Default collector: deterministic local data read-in.

    Reads the family's already collected numeric aggregate
    (``data/collected/<family>_sources.json``) and returns the value rows for
    the config identity plus the recorded source periods.  See the module
    docstring for why this - not live fetching - is the default collector in
    this unit.
    """
    # Imported lazily: the worker module imports this module at load time, so
    # these symbols must never be required at module import time (no cycle).
    from backend.app.collection.worker import CollectionRunError

    aggregate_path = repo_root / family.aggregate_rel
    if not aggregate_path.exists():
        raise CollectionRunError(
            f"[jphouse] aggregate snapshot missing for {family.prefix}/{stem}:"
            f" {family.aggregate_rel}",
            code="aggregate_missing",
        )
    try:
        data = json.loads(aggregate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectionRunError(
            f"[jphouse] aggregate snapshot unreadable for {family.prefix}/{stem}:"
            f" {family.aggregate_rel} ({exc.__class__.__name__})",
            code="aggregate_invalid",
        ) from exc

    entries = _aggregate_entries(data)
    wanted = f"{family.prefix}/{stem}"
    matched = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("source_key") == wanted:
            matched = entry
            break
        cfg = entry.get("config")
        if isinstance(cfg, str) and Path(cfg).name == f"{stem}.json":
            matched = entry
            break
    if matched is None:
        raise CollectionRunError(
            f"[jphouse] no collected record for {wanted} in {family.aggregate_rel}",
            code="aggregate_entry_missing",
        )

    meta: dict = {}
    if isinstance(matched.get("suumo_updated"), str):
        meta["rents_updated"] = matched["suumo_updated"]
    sale = matched.get("sale")
    if isinstance(sale, dict) and isinstance(sale.get("updated"), str):
        meta["sale_updated"] = sale["updated"]
    return CollectResult(rows=_rows_from_ward_record(matched), meta=meta)


def _canonical_payload(snapshot: dict) -> bytes:
    """Canonical JSON bytes used for the snapshot_hash.

    ``collected_at`` (the per-run persistence timestamp) is excluded so that
    identical collected content produces an identical hash - deterministic
    replay / idempotent runs share a fingerprint.
    """
    payload = {key: value for key, value in snapshot.items() if key != "collected_at"}
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _snapshot_dict(
    family: JphouseFamily,
    stem: str,
    config: dict,
    rows: Tuple[dict, ...],
    meta: Mapping[str, object],
    collected_at: str,
) -> dict:
    source_urls: list[str] = []
    for source in config.get("data_sources") or []:
        if isinstance(source, dict) and isinstance(source.get("url"), str):
            source_urls.append(source["url"])
    snapshot = {
        "source_key": f"{family.prefix}/{stem}",
        "config": f"{family.config_dir_rel}/{stem}.json",
        "slug": config.get("slug"),
        "publish_month": config.get("publish_month"),
        "source_urls": source_urls,
        "rows": list(rows),
        "rows_collected": len(rows),
        "parser_version": PARSER_VERSION,
        "snapshot_format": SNAPSHOT_FORMAT,
        "collected_at": collected_at,
    }
    snapshot.update(dict(meta))
    return snapshot


def _write_snapshot(repo_root: Path, family: JphouseFamily, stem: str, snapshot: dict) -> Path:
    """Atomically persist the per-source run snapshot; returns its path."""
    target = repo_root / RUN_SNAPSHOT_ROOT_REL / family.prefix / f"{stem}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{stem}.tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


def _split_source_key(
    family: JphouseFamily, source_key: str, error_type: type
) -> str:
    """Validate ``source_key`` and return the config stem for the family."""
    prefix, sep, stem = source_key.partition("/")
    if (
        sep != "/"
        or prefix != family.prefix
        or not stem
        or "/" in stem
        or not _STEM_RE.match(stem)
    ):
        raise error_type(
            f"[jphouse] invalid source_key {source_key!r} for family"
            f" {family.prefix} (expected '<prefix>/<config-stem>')",
            code="bad_source_key",
        )
    return stem


def make_runner(
    family: JphouseFamily,
    *,
    collector: Optional[Collector] = None,
    repo_root: Optional[Path] = None,
    now: Optional[Clock] = None,
) -> Awaitable:
    """Build a collection runner for one jphouse family.

    ``collector`` / ``repo_root`` / ``now`` are injectable so tests exercise the
    full runner mechanics (config resolution -> collector -> snapshot write ->
    hash) against local sample configs and fixture aggregates without touching
    the real ``data/collected`` tree or the wall clock.
    """
    base_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    effective_collector = collector if collector is not None else collect_local_readin
    effective_now: Clock = now or (
        lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    async def run(source_key: str, source_type: str):
        # Imported lazily so this module never creates an import cycle with
        # worker.py (which imports jphouse_runners at load to register).
        from backend.app.collection.worker import CollectionOutcome, CollectionRunError

        stem = _split_source_key(family, source_key, CollectionRunError)

        config_path = base_root / family.config_dir_rel / f"{stem}.json"
        if not config_path.exists():
            raise CollectionRunError(
                f"[jphouse] config missing for {source_key}: {config_path.relative_to(base_root)}",
                code="config_missing",
            )
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectionRunError(
                f"[jphouse] config unreadable for {source_key}"
                f" ({exc.__class__.__name__})",
                code="config_invalid",
            ) from exc
        if not isinstance(config, dict) or not isinstance(config.get("slug"), str):
            raise CollectionRunError(
                f"[jphouse] config invalid for {source_key}: expected an object"
                " with a string 'slug'",
                code="config_invalid",
            )

        result = effective_collector(family, stem, config, base_root)
        if not isinstance(result, CollectResult) or not isinstance(result.rows, tuple):
            raise CollectionRunError(
                f"[jphouse] collector for {source_key} returned an invalid result",
                code="runner_error",
            )
        snapshot = _snapshot_dict(
            family, stem, config, result.rows, result.meta, effective_now()
        )
        _write_snapshot(base_root, family, stem, snapshot)
        snapshot_hash = hashlib.sha256(_canonical_payload(snapshot)).hexdigest()
        return CollectionOutcome(rows=len(result.rows), snapshot_hash=snapshot_hash)

    return run


def register_defaults(registry: MutableMapping[str, object]) -> None:
    """Add the real jphouse family runners to a runner registry.

    Uses ``setdefault`` semantics so an explicit override registered by tests
    or operators is never clobbered by a later re-registration.
    """
    for family in FAMILIES:
        if family.prefix not in registry:
            registry[family.prefix] = make_runner(family)
