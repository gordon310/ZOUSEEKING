from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_content_library_gate_reports_zero_non_synthetic_violations_and_matching_hashes(tmp_path: Path) -> None:
    output = tmp_path / "content-library-provenance.json"
    result = subprocess.run(
        [sys.executable, "scripts/audit_content_library_provenance.py", "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["canonical_record_count"] == report["web_record_count"]
    assert report["non_synthetic_violations"] == []
    assert report["copies"]["sha256_match"] is True
