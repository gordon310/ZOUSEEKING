from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.check_launch_surface_consistency import (
    CHECK_IDS,
    ContractError,
    audit,
    load_contract,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_RELATIVE = "docs/architecture/launch-surface-consistency-contract.json"
I18N_RELATIVE = "web-source/js/i18n.js"
ANNOUNCEMENT_RELATIVE = "docs/release/launch-announcement-2026-10-07.md"
TOKUSHOHO_RELATIVE = "web/tokushoho.html"
STAGED_FILES = (
    CONTRACT_RELATIVE,
    ANNOUNCEMENT_RELATIVE,
    I18N_RELATIVE,
    "docs/legal/01-プライバシーポリシー(隐私政策).md",
    "docs/legal/03-特定商取引法に基づく表記.md",
)


def stage_repo(tmp_path: Path) -> Path:
    """Copy the checked surfaces so mutations never touch the real checkout."""

    for relative in STAGED_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    for page in sorted((REPO_ROOT / "web").glob("*.html")):
        target = tmp_path / "web" / page.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(page, target)
    return tmp_path


def mutate(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert old in text, f"mutation anchor is missing from {relative}: {old!r}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def mutate_contract(root: Path, mutate_loaded) -> dict:
    path = root / CONTRACT_RELATIVE
    contract = json.loads(path.read_text(encoding="utf-8"))
    mutate_loaded(contract)
    path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return contract


def run_audit(root: Path) -> tuple[dict, list[str]]:
    return audit(root, load_contract(root / CONTRACT_RELATIVE))


def matching(errors: list[str], coordinate: str) -> list[str]:
    return [error for error in errors if coordinate in error]


def test_repository_has_no_undeclared_drift() -> None:
    result, errors = run_audit(REPO_ROOT)

    assert errors == []
    assert result["errors"] == []
    assert result["status"] in {"pass", "open"}
    assert result["production_contacted"] is False
    assert result["network_used"] is False


def test_checks_cover_the_declared_check_ids() -> None:
    result, _ = run_audit(REPO_ROOT)

    assert {check["id"] for check in result["checks"]} == set(CHECK_IDS)


def test_every_declared_open_item_still_reproduces() -> None:
    """A declaration that no longer reproduces must be removed from the contract."""

    result, _ = run_audit(REPO_ROOT)

    stale = [
        item["id"]
        for item in result["declared_open_items"]
        if item["status"] != "open"
    ]
    assert stale == [], f"stale declared open items: {stale}"
    for item in result["declared_open_items"]:
        assert item["owner"].strip()
        assert item["target"].strip()
        assert item["coordinates"]


def test_staged_copy_reproduces_the_repository_result(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    live_result, live_errors = run_audit(REPO_ROOT)
    staged_result, staged_errors = run_audit(staged)

    assert staged_errors == live_errors == []
    assert staged_result["status"] == live_result["status"]


def test_missing_referenced_page_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    (staged / "web/terms.html").unlink()

    _, errors = run_audit(staged)

    assert matching(errors, "C1_announcement_referenced_pages|web/terms.html")


def test_announcement_dropping_a_referenced_page_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, ANNOUNCEMENT_RELATIVE, "`privacy.html`", "privacy")

    _, errors = run_audit(staged)

    assert matching(errors, "C1_announcement_referenced_pages")
    assert any("does not reference" in error for error in errors)


def test_missing_trial_marking_key_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, I18N_RELATIVE, '"trial.badge"', '"trial.badgeRenamed"')

    _, errors = run_audit(staged)

    assert matching(errors, "C2_trial_marking_present_and_used|web-source/js/i18n.js|trial.badge")


def test_dropping_the_official_source_token_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, I18N_RELATIVE, "e-Stat", "eStat")

    _, errors = run_audit(staged)

    assert matching(errors, "C3_official_source_attribution")


def test_dropping_the_free_preview_disclaimer_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(
        staged,
        I18N_RELATIVE,
        "does not replace professional transaction checks",
        "is a substitute for any check",
    )

    _, errors = run_audit(staged)

    assert matching(errors, "C4_free_preview_disclaimer")


def test_entity_fact_drift_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, I18N_RELATIVE, "6120001261672", "6120001261673")

    _, errors = run_audit(staged)

    assert matching(errors, "C5_legal_entity_facts|web-source/js/i18n.js|required")


def test_forbidden_representative_name_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, TOKUSHOHO_RELATIVE, "姜爽", "姜興")

    _, errors = run_audit(staged)

    assert matching(errors, "C5_legal_entity_facts|web/tokushoho.html|representative")


def test_new_placeholder_on_a_referenced_page_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(
        staged,
        I18N_RELATIVE,
        '"legal.navHome": "返回小象数据",',
        '"legal.navHome": "返回小象数据 TBD",',
    )

    _, errors = run_audit(staged)

    assert matching(errors, "C6_unfilled_placeholders|web-source/js/i18n.js|legal.navHome")


def test_jurisdiction_drift_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)

    def add_forbidden_token(contract: dict) -> None:
        contract["jurisdiction"]["forbidden_tokens"].append("跨境传输")

    mutate_contract(staged, add_forbidden_token)
    _, errors = run_audit(staged)

    assert matching(errors, "C7_jurisdiction_scope")


def test_banned_consumer_wording_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, I18N_RELATIVE, "公开数据查询", "公开房源查询")

    _, errors = run_audit(staged)

    assert matching(errors, "C8_consumer_wording_discipline")
    assert any("房源" in error for error in errors)


def test_stale_wording_exception_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)

    def point_exception_at_an_unrelated_key(contract: dict) -> None:
        contract["wording_discipline"]["declared_exceptions"][0]["key"] = "brand.business"

    mutate_contract(staged, point_exception_at_an_unrelated_key)
    _, errors = run_audit(staged)

    assert matching(errors, "C8_consumer_wording_discipline")
    assert any("no longer reproduces" in error for error in errors)


def test_missing_derived_locale_marker_is_reported(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(staged, I18N_RELATIVE, "DICTIONARY_ZH_HANT", "DICTIONARY_DERIVED_MARKER")

    _, errors = run_audit(staged)

    assert matching(errors, "C0_i18n_dictionary_parse")
    assert any("derived-locale marker" in error for error in errors)


def test_fixing_the_draft_notice_clears_its_coordinates(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)
    mutate(
        staged,
        I18N_RELATIVE,
        "本文件为上线前草稿，待法务／负责人确认。生效日：〔生效日:待确认〕",
        "生效日：2026年10月7日。",
    )
    mutate(
        staged,
        I18N_RELATIVE,
        "This document is a pre-launch draft pending legal and owner review. Effective date: [Effective date: to be confirmed]",
        "Effective date: 7 October 2026.",
    )
    mutate(
        staged,
        I18N_RELATIVE,
        "本書は公開前の草案であり、法務・責任者の確認待ちです。発効日：〔発効日：要確認〕",
        "発効日：2026年10月7日。",
    )
    mutate(
        staged,
        "web/privacy.html",
        "本文件为上线前草稿，待法务／负责人确认。生效日：〔生效日:待确认〕",
        "生效日：2026年10月7日。",
    )

    result, errors = run_audit(staged)

    assert errors == []
    assert not any("legal.draftNotice" in coordinate for coordinate in _all_coordinates(result))
    assert not any("web/privacy.html" in coordinate for coordinate in _all_coordinates(result))
    assert result["status"] == "open"


def test_resolved_declaration_is_reported_as_resolved(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)

    def drop_the_forbidden_name(contract: dict) -> None:
        for surface in contract["entity_facts"]["surfaces"]:
            surface["forbidden_tokens"] = []

    mutate_contract(staged, drop_the_forbidden_name)
    result, errors = run_audit(staged)

    assert errors == []
    statuses = {item["id"]: item["status"] for item in result["declared_open_items"]}
    assert statuses["O3"] == "resolved"


def test_contract_rejects_an_unowned_declaration(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)

    def blank_the_owner(contract: dict) -> None:
        contract["declared_open_items"][0]["owner"] = "TBD"

    mutate_contract(staged, blank_the_owner)

    with pytest.raises(ContractError):
        load_contract(staged / CONTRACT_RELATIVE)


def test_contract_rejects_an_unknown_check_id(tmp_path: Path) -> None:
    staged = stage_repo(tmp_path)

    def point_at_an_unknown_check(contract: dict) -> None:
        contract["declared_open_items"][0]["check"] = "C99_made_up"

    mutate_contract(staged, point_at_an_unknown_check)

    with pytest.raises(ContractError):
        load_contract(staged / CONTRACT_RELATIVE)


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(REPO_ROOT)]) == 2

    staged = stage_repo(tmp_path)
    mutate(staged, I18N_RELATIVE, "公开数据查询", "公开房源查询")

    assert main(["--root", str(staged)]) == 1
    captured = capsys.readouterr()
    assert "undeclared violations" in captured.out


def _all_coordinates(result: dict) -> list[str]:
    coordinates = list(result["errors"])
    for check in result["checks"]:
        coordinates.extend(filter(None, check["detail"].split("; ")))
    return coordinates
