"""CLI lifecycle coverage for ``scripts/collection_worker.py``.

These tests execute the worker as a real subprocess against the local
PostgreSQL stack.  They exercise the command's signal handling rather than
calling its asyncio helpers in-process.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "scripts" / "collection_worker.py"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _worker_env() -> dict[str, str]:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL is required for collection worker subprocess tests")
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    env["PYTHONPATH"] = str(ROOT)
    return env


def _read_json_line(process: subprocess.Popen[str], timeout: float) -> dict:
    assert process.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            return json.loads(line)
        if process.poll() is not None:
            break
    stderr = process.stderr.read() if process.stderr is not None else ""
    raise AssertionError(
        f"worker did not emit a JSONL round before exit={process.poll()}: {stderr}"
    )


def test_forever_mode_exits_zero_at_round_boundary_after_sigterm() -> None:
    process = subprocess.Popen(
        [sys.executable, str(WORKER), "--loop", "0", "--interval", "30"],
        cwd=ROOT,
        env=_worker_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        first = _read_json_line(process, timeout=10)
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
    except BaseException:
        process.kill()
        process.communicate()
        raise

    elapsed = time.monotonic() - started
    assert process.returncode == 0, stderr
    assert elapsed < 5
    assert first == {"attempt": 1, "status": "noop", "run_id": None}
    assert stdout == ""
    print(
        "forever subprocess: "
        f"returncode={process.returncode} elapsed_seconds={elapsed:.3f} "
        f"completed_attempt={first['attempt']}"
    )


def test_finite_loop_runs_requested_number_of_rounds_then_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(WORKER), "--loop", "2", "--interval", "0"],
        cwd=ROOT,
        env=_worker_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    assert lines == [
        {"attempt": 1, "status": "noop", "run_id": None},
        {"attempt": 2, "status": "noop", "run_id": None},
    ]
    print(
        "finite subprocess: "
        f"returncode={result.returncode} completed_attempts={len(lines)}"
    )


def test_loop_zero_is_documented_and_negative_loop_is_rejected() -> None:
    help_result = subprocess.run(
        [sys.executable, str(WORKER), "--help"],
        cwd=ROOT,
        env=_worker_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    invalid_result = subprocess.run(
        [sys.executable, str(WORKER), "--loop", "-1"],
        cwd=ROOT,
        env=_worker_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert help_result.returncode == 0
    assert "0 = run until" in help_result.stdout
    assert "SIGTERM or SIGINT" in help_result.stdout
    assert invalid_result.returncode != 0
    assert "--loop must be >= 0" in invalid_result.stderr
