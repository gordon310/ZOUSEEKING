from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.ci.release_evidence import (
    build_evidence,
    derive_release_tag,
    required_checks_pass,
    record_not_executed,
    record_command,
)


def write_result(results_dir: Path, name: str, status: str = "PASS") -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "status": status,
                "command": ["synthetic", name],
                "exit_code": 0 if status == "PASS" else 1,
                "duration_seconds": 0.01,
                "reason": "",
                "recorded_at": "2026-08-31T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


REQUIRED = ["python", "node", "browser", "sql-rls", "supply-chain", "policy"]


def test_derive_release_tag_accepts_matching_version_tag() -> None:
    assert derive_release_tag("0.1.0", "v0.1.0", "abcdef1234567890") == "v0.1.0"


def test_derive_release_tag_uses_candidate_for_branch() -> None:
    assert derive_release_tag("0.1.0", "main", "abcdef1234567890") == "v0.1.0-ci.abcdef123456"


def test_derive_release_tag_rejects_mismatched_version_tag() -> None:
    with pytest.raises(ValueError, match="does not match project version"):
        derive_release_tag("0.1.0", "v0.2.0", "abcdef1234567890")


def test_record_command_does_not_persist_child_output(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    marker = "synthetic-output-must-not-be-recorded"

    exit_code = record_command(
        "safe-command",
        [sys.executable, "-c", f"print({marker!r})"],
        result_path,
    )

    assert exit_code == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert marker not in result_path.read_text(encoding="utf-8")


def test_record_command_redacts_url_credentials(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"

    exit_code = record_command(
        "url-command",
        [sys.executable, "-c", "print(0)", "postgresql://postgres:disposable-password@127.0.0.1:54322/postgres"],
        result_path,
    )

    assert exit_code == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert "disposable-password" not in str(result)
    assert "[redacted]" in str(result["command"])


def test_record_command_marks_missing_executable_blocked(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"

    exit_code = record_command("missing", ["definitely-not-installed-jppropdis"], result_path)

    assert exit_code != 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "BLOCKED"
    assert "not found" in result["reason"].lower()


def test_build_evidence_creates_candidate_source_but_not_release_ready(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    output_dir = tmp_path / "evidence"
    for name in REQUIRED:
        write_result(results_dir, name)

    manifest = build_evidence(
        results_dir=results_dir,
        output_dir=output_dir,
        version="0.1.0",
        ref_name="main",
        commit="abcdef1234567890",
        required=REQUIRED,
    )

    assert manifest["offline_gate_passed"] is True
    assert manifest["release_ready"] is False
    assert manifest["external_checks"]["production_database"] == "NOT_EXECUTED"
    assert (output_dir / manifest["artifacts"]["evidence_bundle"]).is_file()
    assert (output_dir / manifest["artifacts"]["candidate_source"]).is_file()


def test_build_evidence_omits_source_when_required_check_fails(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    output_dir = tmp_path / "evidence"
    for name in REQUIRED:
        write_result(results_dir, name, "FAIL" if name == "sql-rls" else "PASS")

    manifest = build_evidence(
        results_dir=results_dir,
        output_dir=output_dir,
        version="0.1.0",
        ref_name="v0.1.0",
        commit="abcdef1234567890",
        required=REQUIRED,
    )

    assert manifest["offline_gate_passed"] is False
    assert manifest["release_ready"] is False
    assert "candidate_source" not in manifest["artifacts"]
    assert manifest["checks"]["sql-rls"]["status"] == "FAIL"


def test_required_checks_pass_requires_every_named_result_to_pass(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    for name in REQUIRED:
        write_result(results_dir, name)
    assert required_checks_pass(results_dir, REQUIRED) is True

    write_result(results_dir, "sql-rls", "BLOCKED")
    assert required_checks_pass(results_dir, REQUIRED) is False


def test_record_not_executed_is_explicitly_not_a_pass(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"

    exit_code = record_not_executed("production", "requires explicit production approval", result_path)

    assert exit_code == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "NOT_EXECUTED"
    assert result["exit_code"] is None
    assert required_checks_pass(tmp_path, ["production"]) is False
