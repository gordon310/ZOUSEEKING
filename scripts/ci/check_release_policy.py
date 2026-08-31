from __future__ import annotations

from pathlib import Path


REQUIRED_FILES = (
    ".github/workflows/release-gate.yml",
    "docs/release/release-gate.md",
    "docs/release/rollback-checklist.md",
    "supabase/migrations/README.md",
    "tests/sql/test_foundation_schema.sql",
    "tests/sql/test_property_intake_schema.sql",
    "tests/security/test_rls_private_projects.sql",
)
REQUIRED_WORKFLOW_MARKERS = (
    "contents: read",
    "python:",
    "node:",
    "browser:",
    "sql-rls:",
    "supply-chain:",
    "policy:",
    "evidence:",
    "release_ready",
    "NOT_EXECUTED",
)
FORBIDDEN_WORKFLOW_MARKERS = (
    "supabase db push",
    "migration repair",
    "supabase functions deploy",
    "git push --tags",
    "gh release create",
    "render deploy",
)


def check_policy(repo: Path) -> list[str]:
    """Return stable release-policy violations without contacting external services."""

    violations: list[str] = []
    for relative in REQUIRED_FILES:
        if not (repo / relative).is_file():
            violations.append(f"missing required file: {relative}")

    workflow_path = repo / ".github/workflows/release-gate.yml"
    if workflow_path.is_file():
        workflow = workflow_path.read_text(encoding="utf-8")
        for marker in REQUIRED_WORKFLOW_MARKERS:
            if marker not in workflow:
                violations.append(f"workflow missing marker: {marker}")
        for marker in FORBIDDEN_WORKFLOW_MARKERS:
            if marker in workflow:
                violations.append(f"workflow contains forbidden mutation: {marker}")
    migration_policy = repo / "supabase/migrations/README.md"
    if migration_policy.is_file():
        migration_text = migration_policy.read_text(encoding="utf-8")
        for marker in (
            "migration_baseline_status = canonical_local_pass_live_reconciliation_required",
            "禁止 linked push、migration repair、staging reset、production reset",
        ):
            if marker not in migration_text:
                violations.append(f"migration policy missing marker: {marker}")
    render_path = repo / "render.yaml"
    if render_path.is_file() and "INIT_SCHEMA\n        value: \"true\"" in render_path.read_text(encoding="utf-8"):
        violations.append("staging render service enables INIT_SCHEMA")
    return sorted(violations)


def main() -> int:
    violations = check_policy(Path.cwd())
    if violations:
        for violation in violations:
            print(violation)
        return 1
    print("release policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
