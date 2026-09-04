from __future__ import annotations

from pathlib import Path

from scripts.ci.check_release_policy import check_policy


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/release-gate.yml"


def test_repository_policy_requires_release_boundary_files() -> None:
    assert check_policy(ROOT) == []


def test_repository_policy_rejects_staging_schema_initialization(tmp_path: Path) -> None:
    (tmp_path / "render.yaml").write_text(
        "      - key: INIT_SCHEMA\n        value: \"true\"\n",
        encoding="utf-8",
    )

    violations = check_policy(tmp_path)

    assert "staging render service enables INIT_SCHEMA" in violations


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
        "npm run test:web -- --workers=1",
        "npx supabase db reset --local",
        "tests/sql/test_foundation_schema.sql",
        "tests/sql/test_property_intake_schema.sql",
        "tests/sql/test_provenance_policy_metric_contract.sql",
        "tests/sql/test_m1_reconciliation_contract.sql",
        "tests/security/test_rls_private_projects.sql",
        "tests/security/test_rls_v1_identity_matrix.sql",
        "npm audit --audit-level=high",
        "pip-audit",
        "scripts/ci/secret_scan.py",
        "git diff --check",
        "if: always()",
    ):
        assert marker in text


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
        "migration_baseline_status = canonical_staging_reconciled_production_pending",
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
