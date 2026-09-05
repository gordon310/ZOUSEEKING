"""Tests for the real jphouse collection runners (``jphouse_runners.py``).

Pure unit tests only: no database, no network, no writes to the real
``data/collected`` tree.  Each runner is exercised against a disposable temp
tree containing a sample config + fixture aggregate snapshot, asserting the
runner's visible side effect is the *updated per-source snapshot file* under
``data/collected/jphouse_runs/<prefix>/`` and that rows/hash are
deterministic (collection input is separated from deterministic output).
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from backend.app.collection.jphouse_runners import (
    FAMILIES,
    FAMILY_BY_PREFIX,
    CollectResult,
    make_runner,
    register_defaults,
)
from backend.app.collection.worker import (
    RUNNER_REGISTRY,
    CollectionRunError,
    CollectionOutcome,
    NoRunnerError,
    resolve_runner,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")

FIXED_CLOCK = "2026-09-05T08:00:00+00:00"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _sample_config(tmp: Path, stem: str = "minato", url: str | None = None) -> Path:
    family_dir = tmp / "configs" / "jphouse_23ku"
    family_dir.mkdir(parents=True, exist_ok=True)
    path = family_dir / f"{stem}.json"
    path.write_text(
        json.dumps(
            {
                "template_name": "jphouse",
                "slug": f"jphouse_tokyo_23ku_{stem}_2026_08",
                "publish_month": "2026年8月",
                "data_sources": [
                    {
                        "name": "SUUMO 港区租赁相场",
                        "url": url or "https://example.invalid/suumo",
                        "usage": "1LDK/2LDK/3LDK租金相场（2026年7月10日更新）",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _fixture_aggregate(tmp: Path, stem: str = "minato") -> Path:
    agg = tmp / "data" / "collected" / "jphouse_23ku_sources.json"
    agg.parent.mkdir(parents=True, exist_ok=True)
    # Real shape of data/collected/jphouse_23ku_sources.json: a bare list of
    # per-ward records (the osaka/yokohama families wrap a "collected" list).
    agg.write_text(
        json.dumps(
            [
                {
                    "ward": "港区",
                    "config": str(tmp / "configs" / "jphouse_23ku" / f"{stem}.json"),
                    "rents": {"1LDK": 22.5, "2LDK": 33.4, "3LDK": 61.2},
                    "suumo_updated": "2026年7月10日更新",
                    "sale": {
                        "layout_price_man_yen": {
                            "1LDK": 5816, "2LDK": 10204, "3LDK": 7588
                        },
                        "updated": "2026年［令和8年］1～3月",
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return agg


def _real_runner(tmp: Path, **kwargs):
    return make_runner(
        FAMILY_BY_PREFIX["jphouse_23ku"], repo_root=tmp, now=lambda: FIXED_CLOCK, **kwargs
    )


# ---------------------------------------------------------------------------
# registry / resolution
# ---------------------------------------------------------------------------


def test_real_prefixes_are_registered_and_resolve_to_coroutines() -> None:
    for family in FAMILIES:
        assert family.prefix in RUNNER_REGISTRY
        runner = resolve_runner(f"{family.prefix}/ward")
        assert asyncio.iscoroutinefunction(runner)
    # configs/jphouse_worker exists but is not a registered family.
    with pytest.raises(NoRunnerError):
        resolve_runner("jphouse_worker/x")


def test_register_defaults_does_not_clobber_existing_override() -> None:
    async def _override(source_key: str, source_type: str) -> CollectionOutcome:
        return CollectionOutcome(rows=7)

    registry = {"jphouse_23ku": _override}
    register_defaults(registry)
    assert registry["jphouse_23ku"] is _override
    # unregistered prefixes are still added
    assert "jphouse_osaka_wards" in registry


# ---------------------------------------------------------------------------
# deterministic local read-in through the real runner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_runner_visible_side_effect_is_updated_snapshot_file(
    tmp_path: Path,
) -> None:
    _sample_config(tmp_path)
    _fixture_aggregate(tmp_path)
    runner = _real_runner(tmp_path)

    outcome = await runner("jphouse_23ku/minato", "official_open")

    assert isinstance(outcome, CollectionOutcome)
    assert outcome.rows == 6  # 3 rent + 3 sale layout prices
    assert HEX64.match(outcome.snapshot_hash or "")

    snapshot_path = (
        tmp_path / "data" / "collected" / "jphouse_runs" / "jphouse_23ku" / "minato.json"
    )
    assert snapshot_path.exists()
    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))

    # The returned rows_collected and hash match the persisted snapshot, and
    # the snapshot carries provenance/identity fields.
    assert persisted["rows_collected"] == outcome.rows == len(persisted["rows"])
    assert persisted["source_key"] == "jphouse_23ku/minato"
    assert persisted["slug"] == "jphouse_tokyo_23ku_minato_2026_08"
    assert persisted["publish_month"] == "2026年8月"
    assert persisted["parser_version"] == "jphouse-local-readin-v1"
    assert persisted["rents_updated"] == "2026年7月10日更新"
    assert persisted["sale_updated"] == "2026年［令和8年］1～3月"
    assert persisted["source_urls"] == ["https://example.invalid/suumo"]

    # rows are numeric market values with explicit units - never presentation
    # strings - and stay consistent with the fixture aggregate numbers.
    rent_rows = [r for r in persisted["rows"] if r["metric"] == "rent"]
    sale_rows = [r for r in persisted["rows"] if r["metric"] == "sale_price"]
    assert [r["layout"] for r in rent_rows] == ["1LDK", "2LDK", "3LDK"]
    assert rent_rows[0] == {
        "metric": "rent",
        "layout": "1LDK",
        "value_man_yen": 22.5,
        "unit": "man_yen_per_month",
    }
    assert sale_rows[0]["value_man_yen"] == 5816
    assert sale_rows[0]["unit"] == "man_yen"


@pytest.mark.asyncio
async def test_real_runner_rows_and_hash_are_deterministic(tmp_path: Path) -> None:
    _sample_config(tmp_path)
    _fixture_aggregate(tmp_path)
    runner = _real_runner(tmp_path)

    first = await runner("jphouse_23ku/minato", "official_open")
    second = await runner("jphouse_23ku/minato", "official_open")
    assert first == second  # same content -> same rows/hash (idempotent replay)
    assert first.rows == 6
    assert first.snapshot_hash == second.snapshot_hash


@pytest.mark.asyncio
async def test_real_runner_collector_seam_injects_deterministic_output(
    tmp_path: Path,
) -> None:
    # No aggregate file at all: the injected collector fully determines the
    # output, proving collection (input) and deterministic production are
    # decoupled through the collector seam.
    _sample_config(tmp_path)

    def _fixed_collector(family, stem, config, repo_root) -> CollectResult:
        # collector is a synchronous callable (not async); it is invoked by the
        # runner directly and may perform IO via its own means.
        return CollectResult(
            rows=(
                {
                    "metric": "rent",
                    "layout": "2LDK",
                    "value_man_yen": 33.0,
                    "unit": "man_yen_per_month",
                },
            )
        )

    runner = make_runner(
        FAMILY_BY_PREFIX["jphouse_23ku"],
        repo_root=tmp_path,
        now=lambda: FIXED_CLOCK,
        collector=_fixed_collector,
    )
    outcome = await runner("jphouse_23ku/minato", "official_open")
    assert outcome.rows == 1

    snapshot_path = (
        tmp_path / "data" / "collected" / "jphouse_runs" / "jphouse_23ku" / "minato.json"
    )
    persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert persisted["rows"] == [
        {"metric": "rent", "layout": "2LDK", "value_man_yen": 33.0, "unit": "man_yen_per_month"}
    ]
    assert persisted["rows_collected"] == 1


# ---------------------------------------------------------------------------
# failure codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_rejects_malformed_source_key(tmp_path: Path) -> None:
    runner = _real_runner(tmp_path)
    with pytest.raises(CollectionRunError) as excinfo:
        await runner("jphouse_23ku/minato/extra", "official_open")
    assert excinfo.value.code == "bad_source_key"
    with pytest.raises(CollectionRunError) as excinfo:
        await runner("jphouse_osaka_wards/nishi", "official_open")  # wrong family
    assert excinfo.value.code == "bad_source_key"
    with pytest.raises(CollectionRunError) as excinfo:
        await runner("jphouse_23ku/..%2Fetc", "official_open")
    assert excinfo.value.code == "bad_source_key"


@pytest.mark.asyncio
async def test_runner_reports_config_missing(tmp_path: Path) -> None:
    runner = _real_runner(tmp_path)  # no sample config written
    with pytest.raises(CollectionRunError) as excinfo:
        await runner("jphouse_23ku/minato", "official_open")
    assert excinfo.value.code == "config_missing"


@pytest.mark.asyncio
async def test_runner_reports_aggregate_missing(tmp_path: Path) -> None:
    _sample_config(tmp_path)  # config exists, no aggregate file
    runner = _real_runner(tmp_path)
    with pytest.raises(CollectionRunError) as excinfo:
        await runner("jphouse_23ku/minato", "official_open")
    assert excinfo.value.code == "aggregate_missing"


@pytest.mark.asyncio
async def test_runner_reports_missing_aggregate_entry(tmp_path: Path) -> None:
    _sample_config(tmp_path, stem="minato")
    # aggregate exists but holds a different ward
    _fixture_aggregate(tmp_path, stem="shibuya")
    runner = _real_runner(tmp_path)
    with pytest.raises(CollectionRunError) as excinfo:
        await runner("jphouse_23ku/minato", "official_open")
    assert excinfo.value.code == "aggregate_entry_missing"
