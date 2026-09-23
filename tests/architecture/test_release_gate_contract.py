from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.ci.check_release_policy import check_policy


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/release-gate.yml"


def test_repository_policy_requires_release_boundary_files() -> None:
    assert check_policy(ROOT) == []


def test_repository_policy_requires_migration_ownership_status(tmp_path: Path) -> None:
    migration_readme = tmp_path / "supabase/migrations"
    migration_readme.mkdir(parents=True)
    (migration_readme / "README.md").write_text(
        "migration_baseline_status = canonical_staging_reconciled_production_pending\n",
        encoding="utf-8",
    )

    violations = check_policy(tmp_path)

    assert "migration policy missing marker: migration_baseline_status = canonical_staging_reconciled_production_reconciled" in violations


def test_workflow_has_all_required_triggers_jobs_and_commands() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in (
        "pull_request:",
        "workflow_dispatch:",
        "branches: [main]",
        'tags: ["v*"]',
        "contents: read",
        "python:",
        "node:",
        "browser:",
        "sql-rls:",
        "supply-chain:",
        "policy:",
        "evidence:",
        "python -m pytest -q",
        "node --check web/app.js",
        "node --test tests/edge/jphouse-run-authority.test.mjs",
        "npm run check:web-assets",
        "--name web-assets-fresh",
        "node-syntax,node-edge,web-assets-fresh",
        "npm run test:web -- --workers=1",
        "npx supabase db reset --local",
        "tests/sql/test_foundation_schema.sql",
        "tests/sql/test_property_intake_schema.sql",
        "tests/sql/test_provenance_policy_metric_contract.sql",
        "tests/sql/test_m1_reconciliation_contract.sql",
        "tests/sql/test_account_deletion_retention_sweeper.sql",
        "tests/security/test_rls_private_projects.sql",
        "tests/security/test_rls_v1_identity_matrix.sql",
        "npm audit --audit-level=high",
        "pip-audit",
        "scripts/ci/secret_scan.py",
        "git diff --check",
        "if: always()",
    ):
        assert marker in text
    assert text.count("sql-account-retention") >= 3
    assert text.count("web-assets-fresh") >= 3


def test_workflow_requires_every_recorded_check() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    recorded_checks = set(re.findall(r"--name ([a-z0-9-]+)", text))
    required_checks_line = next(
        line for line in text.splitlines() if line.startswith("  REQUIRED_CHECKS:")
    )
    required_checks = set(required_checks_line.split('"')[1].split(","))
    job_required_checks = {
        check
        for line in text.splitlines()
        if " --required " in line
        for check in line.split("--required ", 1)[1].split(",")
    }

    missing_from_required_checks = recorded_checks - required_checks
    assert missing_from_required_checks == set(), missing_from_required_checks

    missing_from_job_required_checks = recorded_checks - job_required_checks
    assert missing_from_job_required_checks == set(), missing_from_job_required_checks


def test_workflow_gates_generated_web_assets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in (
        "npm run check:web-assets",
        "--name web-assets-fresh",
        "node-syntax,node-edge,web-assets-fresh",
    ):
        assert marker in text

    required_checks = next(
        line for line in text.splitlines() if line.startswith("  REQUIRED_CHECKS:")
    )
    assert "web-assets-fresh" in required_checks

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "check:web-assets" in package["scripts"]
    assert "build:web-assets" in package["scripts"]


def test_workflow_forbids_live_mutations_and_external_pass_claims() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "supabase db push",
        "migration repair",
        "supabase functions deploy",
        "git push --tags",
        "gh release create",
        "render deploy",
    ):
        assert forbidden not in text
    assert "NOT_EXECUTED" in text
    assert "release_ready" in text


def test_release_runbooks_record_required_boundaries_and_commands() -> None:
    gate_doc = (ROOT / "docs/release/release-gate.md").read_text(encoding="utf-8")
    rollback_doc = (ROOT / "docs/release/rollback-checklist.md").read_text(encoding="utf-8")
    combined = gate_doc + rollback_doc
    for marker in (
        "release_tag",
        "rollback",
        "forward-fix",
        "NOT_EXECUTED",
        "migration_baseline_status",
        "python3 -m pytest -q",
        "npm run test:web -- --workers=1",
        "node --check",
        "compileall",
        "pip check",
        "npm audit",
        "pip-audit",
        "secret",
        "db reset --local",
        "test_foundation_schema.sql",
        "test_property_intake_schema.sql",
        "test_provenance_policy_metric_contract.sql",
        "test_m1_reconciliation_contract.sql",
        "test_rls_private_projects.sql",
        "test_rls_v1_identity_matrix.sql",
    ):
        assert marker in combined
