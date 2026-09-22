from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_restore_drill_help_describes_source_read_only_and_disposable_target() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/restore_drill.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "read-only" in result.stdout
    assert "disposable" in result.stdout


def test_observability_check_has_required_read_only_contract() -> None:
    script = (ROOT / "deploy/observability-check.sh").read_text(encoding="utf-8")

    assert "default_transaction_read_only = on" in script
    assert "report_generation_outbox" in script
    assert "failed" in script
    assert "zombie_running" in script
    assert "pending_due" in script
    assert "api report-worker nginx" in script
    assert "https://api.zoubeacon.com/health/ready" in script
    assert "127.0.0.1:8000" not in script
    assert "docker exec" in script
    assert "deploy-api-1" in script
    assert "asyncpg" in script
    assert not re.search(r"(?<![A-Za-z0-9_])psql(?:\s|\")", script)


def _compose_service_block(compose: str, name: str) -> str:
    start = compose.index(f"\n  {name}:\n")
    rest = compose[start + 1 :]
    match = re.search(r"\n  [A-Za-z_]", rest)
    assert match, f"could not delimit the {name} service block"
    return rest[: match.start()]


def test_compose_scheduler_runs_collection_qa_sweep_with_snapshot_mount() -> None:
    compose = (ROOT / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8")
    block = _compose_service_block(compose, "scheduler")

    assert "collection_scheduler.py" in block
    assert "collection_sweep.py" in block
    assert "account_retention_sweeper.py --limit 50" in block
    # The QA sweep reads snapshot files under data/collected; the scheduler must
    # mount the same host directory the worker writes them into.
    assert "../data/collected:/app/data/collected" in block
    # A non-zero sweep exit must surface as an operator-visible alert line
    # instead of silently ending the loop.
    assert "collection_sweep_abnormal" in block

    readme = (ROOT / "deploy/README.md").read_text(encoding="utf-8")
    assert "collection_sweep.py" in readme
