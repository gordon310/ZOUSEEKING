from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.check_quota_enforcement_offline import check_repo, load_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "docs/architecture/quota-enforcement-contract.json"
SOURCE_FILES = (
    "backend/app/main.py",
    "backend/app/analysis/routes.py",
    "backend/app/exports/routes.py",
    "backend/app/org/routes.py",
    "backend/app/region_stats_routes.py",
    "backend/app/routes/intake.py",
    "backend/app/usage/quota.py",
)


def _fixture_repo(tmp_path: Path) -> tuple[Path, dict]:
    for relative_path in SOURCE_FILES:
        source = REPO_ROOT / relative_path
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path, copy.deepcopy(load_contract(CONTRACT_PATH))


def _errors_for(errors: list[str], coordinate: str) -> list[str]:
    return [error for error in errors if coordinate in error]


def test_real_repository_satisfies_quota_contract() -> None:
    contract = load_contract(CONTRACT_PATH)

    assert check_repo(REPO_ROOT, contract) == []


def test_rejects_changed_call_site_metric(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / "backend/app/main.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace('metric="query",', 'metric="stats_query",', 1),
        encoding="utf-8",
    )

    assert _errors_for(check_repo(root, contract), "query-create")


def test_rejects_missing_entitlement_call(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / "backend/app/main.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace("await consume_current_entitlement(", "await removed_entitlement_call(", 1),
        encoding="utf-8",
    )

    assert _errors_for(check_repo(root, contract), "c-plus-report")


def test_rejects_missing_call_site_function(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    contract["call_sites"][0]["function"] = "missing_quota_function"

    assert _errors_for(check_repo(root, contract), "query-create")


def test_rejects_unregistered_entitlement_importer(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / "backend/app/unregistered_quota_import.py"
    target.write_text("from .usage.quota import consume_current_entitlement\n", encoding="utf-8")

    assert _errors_for(check_repo(root, contract), "backend/app/unregistered_quota_import.py")


def test_rejects_removed_direct_call_edge(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    target = root / "backend/app/main.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace("await _consume_c_plus_report_quota(", "await removed_report_quota_call(", 1),
        encoding="utf-8",
    )

    assert _errors_for(check_repo(root, contract), "edge-report-job")


def test_rejects_metric_outside_meter_map(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    contract["call_sites"][0]["metric"] = "not_a_meter_metric"

    assert _errors_for(check_repo(root, contract), "not_a_meter_metric")


def test_rejects_duplicate_contract_id(tmp_path: Path) -> None:
    root, contract = _fixture_repo(tmp_path)
    contract["edges"][0]["id"] = contract["call_sites"][0]["id"]

    assert _errors_for(check_repo(root, contract), "duplicate id")
