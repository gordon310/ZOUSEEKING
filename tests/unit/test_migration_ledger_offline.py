from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.check_migration_ledger_offline import (
    DEFAULT_CONTRACT,
    check_repo,
    load_contract,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / DEFAULT_CONTRACT
MIGRATIONS = "supabase/migrations"
DOCS = (
    "docs/architecture/schema-ownership.json",
    "docs/release/m1-database-production-line-evidence.json",
    "docs/release/2026-10-07-go-live-readiness-summary.md",
    "docs/release/go-no-go-checklist-2026-10-07.md",
)


def _fixture_repo(tmp_path: Path) -> tuple[Path, dict]:
    shutil.copytree(REPO_ROOT / MIGRATIONS, tmp_path / MIGRATIONS)
    for relative in DOCS:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    contract_destination = tmp_path / DEFAULT_CONTRACT
    contract_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONTRACT_PATH, contract_destination)
    return tmp_path, copy.deepcopy(load_contract(CONTRACT_PATH))


def _errors_for(errors: list[str], coordinate: str) -> list[str]:
    return [error for error in errors if coordinate in error]


def test_real_repository_satisfies_migration_ledger_contract() -> None:
    assert check_repo(REPO_ROOT, load_contract(CONTRACT_PATH)) == []


def test_contract_pins_and_records_the_full_applied_set() -> None:
    contract = load_contract(CONTRACT_PATH)
    on_disk = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / MIGRATIONS).glob("*.sql")
    )

    assert [pin["file"] for pin in contract["pinned_hashes"]] == on_disk
    assert contract["documented_ledger"]["repo_count"] == len(on_disk)
    assert contract["documented_ledger"]["max_version"] == on_disk[-1][len(MIGRATIONS) + 1 :][:14]
    assert {artifact["id"] for artifact in contract["recorded_artifacts"]} == {
        "m1_baseline_reconciliation_apply",
        "m1_service_role_portability_forward_fix",
    }


def test_editing_an_applied_migration_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / MIGRATIONS / "20260923000300_shared_rate_limits.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- tweak\n", encoding="utf-8")

    errors = check_repo(root, contract)

    assert _errors_for(errors, "20260923000300_shared_rate_limits.sql")


def test_removing_a_pinned_migration_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    (root / MIGRATIONS / "20260824000100_legacy_schema_baseline.sql").unlink()

    errors = check_repo(root, contract)

    assert any(error.startswith("C2 ") for error in errors)
    assert any(error.startswith("C3 ") for error in errors)


def test_new_unpinned_forward_migration_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    (root / MIGRATIONS / "20260930000100_late_addition.sql").write_text(
        "select 1;\n", encoding="utf-8"
    )

    errors = check_repo(root, contract)

    assert _errors_for(errors, "20260930000100_late_addition.sql has no pinned sha256")


def test_malformed_and_duplicated_versions_are_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    (root / MIGRATIONS / "2026092300030_short_version.sql").write_text(
        "select 1;\n", encoding="utf-8"
    )
    (root / MIGRATIONS / "20260923000300_duplicate_version.sql").write_text(
        "select 1;\n", encoding="utf-8"
    )

    errors = check_repo(root, contract)

    assert _errors_for(errors, "2026092300030_short_version.sql: filename")
    assert any(error.startswith("C1 migration version 20260923000300 is duplicated") for error in errors)


def test_manifest_reordering_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    manifest_path = root / contract["manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[contract["manifest"]["key"]] = list(
        reversed(manifest[contract["manifest"]["key"]])
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    errors = check_repo(root, contract)

    assert any(error.startswith("C2 ") and "append-only" in error for error in errors)


def test_manifest_version_drift_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    manifest_path = root / contract["manifest"]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_forward_history"] = "db/migrations"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    errors = check_repo(root, contract)

    assert any(error.startswith("C2 ") and "canonical_forward_history" in error for error in errors)


def test_recorded_production_line_hash_tampering_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    evidence = root / "docs/release/m1-database-production-line-evidence.json"
    document = json.loads(evidence.read_text(encoding="utf-8"))
    document["migration"]["service_role_portability_forward_fix"]["sha256"] = "0" * 64
    evidence.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    errors = check_repo(root, contract)

    assert any(
        error.startswith("C4 ") and "no longer matches the recorded sha256" in error
        for error in errors
    )


def test_live_claim_ledger_count_drift_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    summary = root / "docs/release/2026-10-07-go-live-readiness-summary.md"
    summary.write_text(
        summary.read_text(encoding="utf-8").replace("生产 **54 / 仓库 54**", "生产 **53 / 仓库 54**"),
        encoding="utf-8",
    )

    errors = check_repo(root, contract)

    assert any(error.startswith("C5 L1_go_live_readiness_summary: production=") for error in errors)


def test_live_claim_max_version_drift_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    checklist = root / "docs/release/go-no-go-checklist-2026-10-07.md"
    checklist.write_text(
        checklist.read_text(encoding="utf-8").replace(
            "最高登记 `20260923000300`", "最高登记 `20260922000100`"
        ),
        encoding="utf-8",
    )

    errors = check_repo(root, contract)

    assert any(
        error.startswith("C5 L2_go_no_go_checklist_a1: max_version=") for error in errors
    )


def test_duplicated_live_claim_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    checklist = root / "docs/release/go-no-go-checklist-2026-10-07.md"
    text = checklist.read_text(encoding="utf-8")
    claim_line = next(line for line in text.splitlines() if "生产已登记 54 条 / 仓库 54 条" in line)
    checklist.write_text(text + "\n" + claim_line + "\n", encoding="utf-8")

    errors = check_repo(root, contract)

    assert any(
        error.startswith("C5 L2_go_no_go_checklist_a1") and "2 claim(s), expected 1" in error
        for error in errors
    )


def test_unregistered_destructive_statement_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / MIGRATIONS / "20260824000100_legacy_schema_baseline.sql"
    target.write_text(
        target.read_text(encoding="utf-8") + "\ndrop table public.some_member_table;\n",
        encoding="utf-8",
    )

    errors = check_repo(root, contract)

    assert any(
        error.startswith("C6 ") and "drop_table appears 1 time(s), registered 0" in error
        for error in errors
    )


def test_registered_destructive_count_drift_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / MIGRATIONS / "20260905000500_v1_finance_admin_audit.sql"
    target.write_text(
        target.read_text(encoding="utf-8") + "\ntruncate public.audit_events;\n",
        encoding="utf-8",
    )

    errors = check_repo(root, contract)

    assert any(
        error.startswith("C6 ") and "truncate appears 2 time(s), registered 1" in error
        for error in errors
    )


def test_stale_destructive_registration_is_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / MIGRATIONS / "20260923000100_invite_only_consumer_gate.sql"
    text = target.read_text(encoding="utf-8").replace(
        "delete from public.invite_redemptions", "update public.invite_redemptions"
    )
    target.write_text(text, encoding="utf-8")

    errors = check_repo(root, contract)

    assert any(
        error.startswith("C6 ") and "delete_from is registered (1) but no longer present" in error
        for error in errors
    )


def test_comment_only_destructive_keywords_are_not_registered(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / MIGRATIONS / "20260824000100_legacy_schema_baseline.sql"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n-- drop table public.example;\n",
        encoding="utf-8",
    )

    errors = check_repo(root, contract)

    assert not [error for error in errors if error.startswith("C6 ")]


def test_contract_structure_violations_are_rejected(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    broken = copy.deepcopy(contract)
    broken["contract"] = "something-else/v1"
    broken["live_ledger_claims"][0]["pattern"] = "no groups here"

    errors = check_repo(root, broken)

    assert any(error.startswith("C7 contract must be") for error in errors)
    assert any(error.startswith("C7 live_ledger_claims[0].pattern") for error in errors)


def test_cli_exit_codes_and_print_pins(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    assert main(["--root", str(root)]) == 0
    assert main(["--root", str(root), "--json"]) == 0

    (root / MIGRATIONS / "20260824000100_legacy_schema_baseline.sql").write_text(
        "-- changed\n", encoding="utf-8"
    )
    assert main(["--root", str(root)]) == 1
    assert main(["--root", str(tmp_path / "missing")]) == 1

    result = subprocess.run(
        [sys.executable, "scripts/check_migration_ledger_offline.py", "--print-pins"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    printed = json.loads(result.stdout)
    assert [pin["file"] for pin in printed] == [pin["file"] for pin in contract["pinned_hashes"]]
