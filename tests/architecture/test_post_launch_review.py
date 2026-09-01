from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/operations/post-launch-slo-review-2026-09-01.json"


def test_post_launch_review_stays_blocked_without_production_evidence() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert report["status"] == "blocked_pre_production"
    assert report["production_contacted"] is False
    assert report["customer_content_read"] is False
    assert report["evidence_window_days"] == [30, 60]
    assert set(report["metrics"]) == {
        "api_slo",
        "error_budget",
        "database_pool",
        "worker_backlog",
        "storage_growth",
        "cost",
    }
    assert set(report["metrics"].values()) == {"not_available"}
    assert report["optimization"]["status"] == "not_started"
    assert report["render_postgres"]["decision"] == "defer"
    assert report["render_postgres"]["migration_approved"] is False


def test_post_launch_review_machine_check_is_reproducible() -> None:
    result = subprocess.run(
        ["python3", "scripts/check_post_launch_review.py", "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "pass"
    assert output["review_status"] == "blocked_pre_production"
    assert output["render_postgres_decision"] == "defer"
