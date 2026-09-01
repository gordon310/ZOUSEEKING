from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app import db
from backend.app.intake.geocoding import GsiReverseGeocoder
from backend.app.intake.storage import MAX_UPLOAD_BYTES, UnsupportedUpload, validate_upload
from backend.app.main import app
from scripts.staging_capacity_probe import (
    CapacityConfig,
    SyntheticJobQueue,
    inspect_static_assets,
    percentile,
    run_asgi_probe,
    run_pool_probe,
    run_queue_probe,
    run_async_probe,
    validate_probe_target,
    within_error_budget,
)


def test_percentile_interpolates_the_tail_from_hand_checked_values():
    assert percentile([10, 20, 30, 40, 50], 50) == 30
    assert percentile([10, 20, 30, 40, 50], 95) == 48


@pytest.mark.asyncio
async def test_async_probe_bounds_concurrency_and_records_failures():
    active = 0
    max_active = 0
    failed_once = False

    async def operation():
        nonlocal active, max_active, failed_once
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.001)
            if not failed_once:
                failed_once = True
                raise RuntimeError("synthetic failure")
        finally:
            active -= 1

    result = await run_async_probe(operation, requests=10, concurrency=3)

    assert result.total == 10
    assert result.failed == 1
    assert result.succeeded == 9
    assert result.max_in_flight == 3
    assert max_active == 3


def test_error_budget_rejects_more_than_one_percent():
    assert within_error_budget(total=100, failed=1, fraction=0.01)
    assert not within_error_budget(total=100, failed=2, fraction=0.01)


@pytest.mark.asyncio
async def test_pool_probe_reports_bounded_in_flight_and_acquire_tail():
    async def database_operation():
        await asyncio.sleep(0.003)

    result = await run_pool_probe(database_operation, operations=8, pool_size=2)

    assert result.request_stats.succeeded == 8
    assert result.max_in_flight == 2
    assert result.acquire_wait_p95_ms >= 0


def test_synthetic_job_queue_rejects_a_burst_after_capacity():
    queue = SyntheticJobQueue(capacity=2)

    assert queue.enqueue("job-1")
    assert queue.enqueue("job-2")
    assert not queue.enqueue("job-3")
    assert queue.depth == 2
    assert queue.rejected == 1


@pytest.mark.asyncio
async def test_queue_probe_records_rejected_burst_and_completed_jobs():
    result = await run_queue_probe(capacity=2, jobs=5, workers=1, service_ms=0)

    assert result.accepted == 2
    assert result.rejected == 3
    assert result.completed == 2
    assert result.max_depth == 2


def test_probe_target_rejects_non_staging_remote_hosts():
    assert validate_probe_target("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert validate_probe_target("https://zouseeking-api-staging.onrender.com", allow_staging=True)
    with pytest.raises(ValueError):
        validate_probe_target("https://zouseeking-api.onrender.com", allow_staging=True)


def test_static_inventory_returns_relative_paths_and_sizes(tmp_path):
    (tmp_path / "index.html").write_text("<html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "logo.png").write_bytes(b"x" * 12)
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "generated.png").write_bytes(b"x" * 100)

    inventory = inspect_static_assets(tmp_path)

    assert inventory.file_count == 2
    assert inventory.total_bytes == 18
    assert inventory.largest_path == "assets/logo.png"


def test_capacity_defaults_are_bounded_and_staging_safe():
    config = CapacityConfig()

    assert config.concurrency > 0
    assert config.pool_size == 5
    assert config.queue_capacity > 0
    assert config.error_budget_fraction == 0.01
    assert config.target_url is None


def test_cli_local_fastapi_entrypoint_bootstraps_repository_import(tmp_path):
    output = tmp_path / "baseline.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "staging_capacity_probe.py"),
            "--local-fastapi",
            "--requests",
            "1",
            "--concurrency",
            "1",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["fastapi"]["probe"].startswith(
        "local_in_process_asgi:"
    )


def test_upload_boundary_and_storage_contract_are_explicit():
    exact = b"%PDF-" + b"x" * (MAX_UPLOAD_BYTES - len(b"%PDF-"))
    validate_upload("synthetic.pdf", "application/pdf", exact)
    with pytest.raises(UnsupportedUpload):
        validate_upload("synthetic-too-large.pdf", "application/pdf", exact + b"x")


def test_geocoder_timeout_is_clamped_to_provider_safe_range():
    assert GsiReverseGeocoder(timeout_seconds=0).timeout_seconds == 1
    assert GsiReverseGeocoder(timeout_seconds=99).timeout_seconds == 15


@pytest.mark.asyncio
async def test_fastapi_live_route_handles_local_concurrent_requests_only():
    result = await run_asgi_probe(app, "/health/live", requests=16, concurrency=4)

    assert result.failed == 0
    assert result.succeeded == 16
    assert 1 <= result.max_in_flight <= 4


@pytest.mark.asyncio
async def test_db_connect_declares_bounded_pool(monkeypatch):
    captured = {}

    class FakePool:
        async def close(self):
            return None

    async def fake_create_pool(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakePool()

    monkeypatch.setattr(db, "DATABASE_URL", "postgresql://synthetic.invalid/db")
    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    await db.connect()
    try:
        assert captured["min_size"] == 1
        assert captured["max_size"] == 5
    finally:
        await db.close()
