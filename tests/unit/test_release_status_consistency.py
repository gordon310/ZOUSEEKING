from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.check_release_status_consistency import (
    CHECK_IDS,
    DEFAULT_CONTRACT,
    ContractError,
    audit,
    load_contract,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLIST_RELATIVE = "docs/release/go-no-go-checklist-2026-10-07.md"
PLAN_RELATIVE = "docs/superpowers/plans/2026-09-24-launch-countdown-10-07.md"
STATE_FILES = (
    "docs/release/production-go-live-approval.json",
    "docs/release/production-release-evidence.json",
    "docs/release/phase-one-staging-evidence.json",
)
STAGED_FILES = (DEFAULT_CONTRACT, CHECKLIST_RELATIVE, PLAN_RELATIVE, *STATE_FILES)

C14_LEGACY_STATUS = "🟡 待用户逐项授权（口径已更新）"


def stage_repo(tmp_path: Path) -> Path:
    """Copy the checked documents so mutations never touch the real checkout."""

    for relative in STAGED_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    return tmp_path


def replace_in(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"fixture text not found in {relative}: {old[:60]!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def rewrite_json(root: Path, relative: str, mutate) -> None:
    path = root / relative
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(root: Path) -> tuple[dict, list[str]]:
    return audit(root, load_contract(root / DEFAULT_CONTRACT))


def failing_checks(result: dict, coordinates: list[str]) -> set[str]:
    return {
        check["id"]
        for check in result["checks"]
        if any(coordinate in coordinates for coordinate in check["detail"].split("; "))
    }


# --------------------------------------------------------------------------
# the real repository
# --------------------------------------------------------------------------


def test_real_repo_has_no_undeclared_drift():
    result, undeclared = run(REPO_ROOT)
    assert undeclared == []
    assert result["status"] == "open"
    assert result["production_contacted"] is False
    assert result["network_used"] is False


def test_real_repo_only_open_item_is_the_registered_d8_c04_scope_conflict():
    result, _ = run(REPO_ROOT)
    open_items = [item for item in result["declared_open_items"] if item["status"] == "open"]
    assert [item["id"] for item in open_items] == ["RS1_d8_c04_scope"]
    assert open_items[0]["coordinates"] == ["plan:D-8:C04:plan-open-checklist-closed"]
    assert open_items[0]["owner"].strip().lower() not in {"", "tbd", "todo"}
    assert open_items[0]["blocking"] is True


def test_real_repo_checks_are_the_registered_set():
    result, _ = run(REPO_ROOT)
    assert [check["id"] for check in result["checks"]] == list(CHECK_IDS)
    failing = [check["id"] for check in result["checks"] if not check["ok"]]
    assert failing == ["C7_plan_vs_checklist_scope"]


def test_real_repo_cli_exit_code_is_open(capsys):
    assert main(["--root", str(REPO_ROOT)]) == 2
    out = capsys.readouterr().out
    assert "release-status consistency: open" in out
    assert "plan:D-8:C04:plan-open-checklist-closed" in out


def test_real_repo_cli_json_reports_offline_and_declared_items(capsys):
    assert main(["--root", str(REPO_ROOT), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["production_contacted"] is False
    assert payload["network_used"] is False
    assert payload["errors"] == []
    assert payload["declared_open_items"][0]["id"] == "RS1_d8_c04_scope"


def test_staged_copy_reproduces_the_real_result(tmp_path):
    root = stage_repo(tmp_path)
    result, undeclared = run(root)
    assert undeclared == []
    assert result["status"] == "open"


# --------------------------------------------------------------------------
# mutations: the document and the machine state must not drift apart
# --------------------------------------------------------------------------


def test_stale_c14_row_is_caught_when_reverted(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        CHECKLIST_RELATIVE,
        "| C14 | ✅ 已完成（09-27，本行 09-29 夜班按机器状态更正） |",
        f"| C14 | {C14_LEGACY_STATUS} |",
    )
    result, undeclared = run(root)
    assert any(
        coordinate.startswith("binding:B1_c14_go_live_approval:C14:partial")
        for coordinate in undeclared
    )
    assert "C4_machine_state_bindings" in failing_checks(result, undeclared)


def test_authorization_rollback_makes_the_closed_claim_drift(tmp_path):
    root = stage_repo(tmp_path)
    rewrite_json(
        root,
        "docs/release/production-go-live-approval.json",
        lambda document: document.__setitem__("status", "BLOCK / NOT AUTHORIZED"),
    )
    result, undeclared = run(root)
    assert any(coordinate.startswith("binding:B1_c14_go_live_approval") for coordinate in undeclared)
    assert any(coordinate.startswith("verdict:Go:vs:BLOCK / NOT AUTHORIZED") for coordinate in undeclared)
    assert "C6_verdict_agreement" in failing_checks(result, undeclared)


def test_release_evidence_rollback_makes_the_closed_claim_drift(tmp_path):
    root = stage_repo(tmp_path)
    rewrite_json(
        root,
        "docs/release/production-release-evidence.json",
        lambda document: document.__setitem__("status", "NOT_EXECUTED"),
    )
    _, undeclared = run(root)
    assert any(
        coordinate.startswith("binding:B2_c14_release_evidence:C14:closed")
        for coordinate in undeclared
    )


def test_uncovered_state_value_is_reported_instead_of_guessed(tmp_path):
    root = stage_repo(tmp_path)
    rewrite_json(
        root,
        "docs/release/production-go-live-approval.json",
        lambda document: document.__setitem__("status", "PENDING_REVIEW"),
    )
    _, undeclared = run(root)
    assert any("PENDING_REVIEW" in coordinate and "not covered" not in coordinate for coordinate in undeclared)
    assert any("binding:B1_c14_go_live_approval:PENDING_REVIEW" in coordinate for coordinate in undeclared)
    assert any("C6_verdict_agreement" and "PENDING_REVIEW" in coordinate for coordinate in undeclared)


def test_staging_evidence_flip_no_longer_blocks_c13(tmp_path):
    root = stage_repo(tmp_path)
    rewrite_json(
        root,
        "docs/release/phase-one-staging-evidence.json",
        lambda document: document.__setitem__("status", "EXECUTED"),
    )
    _, undeclared = run(root)
    assert any("B3_c13_staging_evidence" and "EXECUTED" in coordinate for coordinate in undeclared)


def test_missing_historical_caveat_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        CHECKLIST_RELATIVE,
        "**旧判定不再作为当前结论,勿引用。**",
        "**历史记录。**",
    )
    result, undeclared = run(root)
    assert any("caveat" in coordinate for coordinate in undeclared)
    assert "C2_historical_marking" in failing_checks(result, undeclared)


def test_renamed_current_section_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        CHECKLIST_RELATIVE,
        "## B. C01–C14 对 10-07 的判定",
        "## B. C01–C14 判定",
    )
    result, undeclared = run(root)
    assert any(coordinate == "section:current_item_judgement" for coordinate in undeclared)
    assert any(coordinate.startswith("unregistered-section:") for coordinate in undeclared)
    assert "C1_section_registry" in failing_checks(result, undeclared)


def test_new_unregistered_status_table_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    path = root / CHECKLIST_RELATIVE
    text = path.read_text(encoding="utf-8")
    text += (
        "\n## H. 临时判定\n\n"
        "| 项 | 判定 | 依据 |\n|---|---|---|\n"
        "| C04 | ✅ 已闭合 | 手工补的一段表 |\n"
    )
    path.write_text(text, encoding="utf-8")
    result, undeclared = run(root)
    assert any(coordinate == "unregistered-section:## H. 临时判定" for coordinate in undeclared)
    assert "C1_section_registry" in failing_checks(result, undeclared)


def test_deleted_item_row_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    path = root / CHECKLIST_RELATIVE
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("| C06 | ✅ 闭合")
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result, undeclared = run(root)
    assert "current-table:C06" in undeclared
    assert "C3_current_item_coverage" in failing_checks(result, undeclared)


def test_duplicated_item_row_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        CHECKLIST_RELATIVE,
        "| C05 | 🟡 需一次生产复验 |",
        "| C05 | 🟡 需一次生产复验 |\n| C05 | ✅ 已闭合 |",
    )
    result, undeclared = run(root)
    assert any(coordinate.endswith("C05:duplicate") for coordinate in undeclared)
    assert "C3_current_item_coverage" in failing_checks(result, undeclared)


def test_status_glyph_removal_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(root, CHECKLIST_RELATIVE, "| C07 | ✅ 已闭合(09-24 补) |", "| C07 | 已闭合 |")
    result, undeclared = run(root)
    assert any(coordinate.endswith(":C07") and "section:" in coordinate for coordinate in undeclared)
    assert "C3_current_item_coverage" in failing_checks(result, undeclared)


def test_hidden_verdict_drift_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(root, CHECKLIST_RELATIVE, "**工程侧:Go。**", "**工程侧:No-Go。**")
    result, undeclared = run(root)
    assert any(coordinate.startswith("verdict:") for coordinate in undeclared)
    assert "C6_verdict_agreement" in failing_checks(result, undeclared)


def test_plan_row_claiming_a_partial_item_closed_is_caught(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        PLAN_RELATIVE,
        "| **D-9** | 09-28 一 | **C13 真实 staging smoke**",
        "| **D-9** | 09-28 一 | ✅ **C13 真实 staging smoke**",
    )
    result, undeclared = run(root)
    assert "plan:D-9:C13:plan-closed-checklist-partial" in undeclared
    assert "C7_plan_vs_checklist_scope" in failing_checks(result, undeclared)


def test_resolved_declaration_is_reported_not_hidden(tmp_path):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        PLAN_RELATIVE,
        "| **D-8** | 09-29 二 | **C04**(成本已批)",
        "| **D-8** | 09-29 二 | ✅ **C04**(成本已批)",
    )
    result, undeclared = run(root)
    assert undeclared == []
    assert result["declared_open_items"][0]["status"] == "resolved"
    assert result["status"] == "open"


def test_cli_exit_code_is_one_for_undeclared_drift(tmp_path, capsys):
    root = stage_repo(tmp_path)
    replace_in(
        root,
        CHECKLIST_RELATIVE,
        "## B. C01–C14 对 10-07 的判定",
        "## B. C01–C14 判定",
    )
    assert main(["--root", str(root), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert payload["errors"]


def test_missing_document_is_a_contract_error(tmp_path):
    root = stage_repo(tmp_path)
    (root / PLAN_RELATIVE).unlink()
    with pytest.raises(ContractError):
        run(root)


# --------------------------------------------------------------------------
# mutations: the contract itself
# --------------------------------------------------------------------------


def _contract_of(root: Path) -> dict:
    return json.loads((root / DEFAULT_CONTRACT).read_text(encoding="utf-8"))


def _write_contract(root: Path, contract: dict) -> None:
    (root / DEFAULT_CONTRACT).write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_contract_without_owner_is_rejected(tmp_path):
    root = stage_repo(tmp_path)
    contract = _contract_of(root)
    contract["declared_open_items"][0]["owner"] = "TBD"
    _write_contract(root, contract)
    with pytest.raises(ContractError):
        load_contract(root / DEFAULT_CONTRACT)


def test_contract_with_a_glyph_in_two_classes_is_rejected(tmp_path):
    root = stage_repo(tmp_path)
    contract = _contract_of(root)
    contract["status_classes"]["partial"].append("✅")
    _write_contract(root, contract)
    with pytest.raises(ContractError):
        load_contract(root / DEFAULT_CONTRACT)


def test_contract_binding_outside_the_item_universe_is_rejected(tmp_path):
    root = stage_repo(tmp_path)
    contract = _contract_of(root)
    contract["bindings"][0]["item"] = "C99"
    _write_contract(root, contract)
    with pytest.raises(ContractError):
        load_contract(root / DEFAULT_CONTRACT)


def test_contract_state_claim_naming_an_unknown_section_is_rejected(tmp_path):
    root = stage_repo(tmp_path)
    contract = _contract_of(root)
    contract["state_claims"][0]["current_value_sections"].append("section_that_does_not_exist")
    _write_contract(root, contract)
    with pytest.raises(ContractError):
        load_contract(root / DEFAULT_CONTRACT)


def test_contract_missing_keys_is_rejected(tmp_path):
    root = stage_repo(tmp_path)
    contract = _contract_of(root)
    del contract["state_claims"]
    _write_contract(root, contract)
    with pytest.raises(ContractError):
        load_contract(root / DEFAULT_CONTRACT)


def test_contract_with_invalid_regex_is_rejected(tmp_path):
    root = stage_repo(tmp_path)
    contract = _contract_of(root)
    contract["plan_scope"]["item_reference_pattern"] = "(?<!C("
    _write_contract(root, contract)
    with pytest.raises(ContractError):
        load_contract(root / DEFAULT_CONTRACT)
