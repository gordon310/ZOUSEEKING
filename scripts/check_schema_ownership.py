#!/usr/bin/env python3
"""Validate the repository's single forward-migration ownership contract.

This command is intentionally offline and read-only. It compares the tracked
SQL layout with ``docs/architecture/schema-ownership.json``; it never connects
to PostgreSQL, a provider, or applies SQL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


MIGRATION_NAME = re.compile(r"^(?P<timestamp>\d{14})_[a-z0-9][a-z0-9_]*\.sql$")
EXPECTED_CANONICAL_HISTORY = "supabase/migrations"
EXPECTED_BASELINE_STATUS = "canonical_staging_reconciled_production_pending"
REQUIRED_PROHIBITIONS = {
    "edit_applied_migration",
    "delete_restore_package",
    "apply_live_database_change_without_explicit_approval",
    "linked_migration_repair_or_push_without_approval",
    "staging_or_production_reset_without_approval",
}


def _relative_sql_files(root: Path, directory: str) -> list[str]:
    base = root / directory
    if not base.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix() for path in base.rglob("*.sql"))


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "docs/architecture/schema-ownership.json"
    return json.loads(path.read_text(encoding="utf-8"))


def audit(root: Path) -> tuple[dict[str, Any], list[str]]:
    """Return a machine-readable report and any local contract violations."""

    errors: list[str] = []
    try:
        manifest = _load_manifest(root)
    except (OSError, json.JSONDecodeError) as exc:
        error = f"cannot load schema ownership manifest: {exc}"
        return {"status": "fail", "errors": [error]}, [error]

    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    canonical = manifest.get("canonical_forward_history")
    if canonical != EXPECTED_CANONICAL_HISTORY:
        errors.append(f"canonical_forward_history must be {EXPECTED_CANONICAL_HISTORY!r}")

    baseline_status = manifest.get("migration_baseline_status")
    if baseline_status != EXPECTED_BASELINE_STATUS:
        errors.append(f"migration_baseline_status must be {EXPECTED_BASELINE_STATUS!r}")

    migration_files = _relative_sql_files(root, EXPECTED_CANONICAL_HISTORY)
    expected_migrations = [
        f"{EXPECTED_CANONICAL_HISTORY}/{name}"
        for name in manifest.get("forward_migration_files", [])
    ]
    if migration_files != expected_migrations:
        errors.append(
            "forward migration files do not match manifest: "
            f"actual={migration_files!r}, expected={expected_migrations!r}"
        )

    timestamps: list[str] = []
    invalid_names: list[str] = []
    for path in migration_files:
        match = MIGRATION_NAME.match(Path(path).name)
        if match is None:
            invalid_names.append(path)
        else:
            timestamps.append(match.group("timestamp"))
    if invalid_names:
        errors.append(f"invalid forward migration filename(s): {invalid_names!r}")
    if len(timestamps) != len(set(timestamps)):
        errors.append("forward migration timestamps must be unique")

    legacy_files = _relative_sql_files(root, "backend/sql")
    expected_legacy = sorted(manifest.get("legacy_sql_files", []))
    if legacy_files != expected_legacy:
        errors.append(
            "legacy SQL files do not match manifest: "
            f"actual={legacy_files!r}, expected={expected_legacy!r}"
        )

    inventory = manifest.get("legacy_sql_inventory", {})
    if sorted(inventory) != expected_legacy:
        errors.append("legacy_sql_inventory keys must cover every backend/sql/*.sql file exactly once")
    for path, details in inventory.items():
        if not isinstance(details, dict):
            errors.append(f"legacy_sql_inventory entry {path!r} must be an object")
            continue
        disposition = details.get("disposition", "")
        if not disposition or disposition.startswith("forward_history"):
            errors.append(f"legacy SQL entry {path!r} cannot claim forward-history ownership")

    prohibitions = set(manifest.get("prohibited_operations", []))
    missing_prohibitions = sorted(REQUIRED_PROHIBITIONS - prohibitions)
    if missing_prohibitions:
        errors.append(f"missing required prohibitions: {missing_prohibitions!r}")

    audit_document = manifest.get("audit_document")
    if not isinstance(audit_document, str) or not (root / audit_document).is_file():
        errors.append(f"audit document is missing: {audit_document!r}")

    required_docs = manifest.get("required_documentation", [])
    missing_docs = [path for path in required_docs if not (root / path).is_file()]
    if missing_docs:
        errors.append(f"required documentation is missing: {missing_docs!r}")

    report = {
        "status": "pass" if not errors else "fail",
        "canonical_forward_history": canonical,
        "migration_baseline_status": baseline_status,
        "forward_migration_files": [Path(path).name for path in migration_files],
        "legacy_sql_files": legacy_files,
        "required_documentation": required_docs,
        "errors": errors,
    }
    return report, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args(argv)

    report, errors = audit(args.root.resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif errors:
        print("schema_ownership_status=fail")
        for error in errors:
            print(f"- {error}")
    else:
        print(
            "schema_ownership_status=pass "
            f"canonical_forward_history={report['canonical_forward_history']} "
            f"migration_baseline_status={report['migration_baseline_status']}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
