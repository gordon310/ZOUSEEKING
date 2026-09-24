"""Static guards for the durable report-job queue authority boundary."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/architecture/report-job-queue-contract.md"
BOUNDARIES = ROOT / "docs/architecture/authoritative-boundaries.json"
MIGRATION = ROOT / "supabase/migrations/20260918000400_report_generation_outbox.sql"


def _python_sources() -> list[Path]:
    return sorted((ROOT / "backend/app").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))


def _call_sites(name: str) -> list[tuple[Path, int]]:
    pattern = re.compile(rf"(?<!def\s){re.escape(name)}\s*\(")
    sites: list[tuple[Path, int]] = []
    for path in _python_sources():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            code = re.sub(r"(['\"]).*?\1", "", code)
            if pattern.search(code):
                sites.append((path.relative_to(ROOT), line_number))
    return sites


def test_only_the_report_worker_executes_generation_jobs() -> None:
    """A production request path calling the executor would bypass the outbox.

    This text-only guard ignores line comments and simple quoted literals; the
    remaining match is treated as executable source rather than prose.
    """
    assert _call_sites("run_generation_job") == [(Path("backend/app/report_worker.py"), 241)]


def test_no_request_path_executes_generation_jobs() -> None:
    """A BackgroundTasks report call would make crash/replay semantics non-durable."""
    all_source = "\n".join(path.read_text(encoding="utf-8") for path in _python_sources())
    assert not re.search(r"\.add_task\(\s*run_generation_job\s*[,)]", all_source)
    assert _call_sites("add_task") == [(Path("backend/app/routes/intake.py"), 261)]
    intake = (ROOT / "backend/app/routes/intake.py").read_text(encoding="utf-8")
    assert "background_tasks.add_task(cleanup_expired_sessions, repository, storage)" in intake


def test_contract_document_names_the_evidence() -> None:
    """Removing core queue evidence from the human contract would hide its guarantees."""
    text = CONTRACT.read_text(encoding="utf-8")
    for anchor in (
        "Single authoritative consumer",
        "for update skip locked",
        "idempotency_key",
        "15 minutes",
        "test_two_real_postgres_workers_only_one_claims_same_job",
        "test_no_request_path_executes_generation_jobs",
    ):
        assert anchor in text


def test_contract_matches_authoritative_boundaries() -> None:
    """A changed authority value must be reflected in the queue contract."""
    boundary = json.loads(BOUNDARIES.read_text(encoding="utf-8"))
    expected = "postgres_job_outbox_single_worker"
    assert boundary["background_execution"] == expected
    assert expected in CONTRACT.read_text(encoding="utf-8")


def test_outbox_status_vocabulary_matches_migration() -> None:
    """A status added to either schema or contract must be reviewed together."""
    migration = MIGRATION.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    for status in ("pending", "running", "retryable", "completed", "failed"):
        assert f"'{status}'" in migration
        assert status in contract
