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
