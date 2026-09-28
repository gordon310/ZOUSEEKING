#!/usr/bin/env python3
"""Offline launch-surface consistency gate (10-07 countdown, D-5 offline half).

Cross-checks the four-language launch announcement against the site pages it
points users to and against the website dictionary that actually renders them.

Scope of the claim (do not over-read this tool):

* It is **offline**: no network, no socket, no credentials, no environment
  variables, no database. It never proves live behaviour, only that the
  checked-in surfaces agree with each other.
* It reads the readable source (``web-source/js/i18n.js``) and the hand-written
  pages (``web/*.html``). The generated runtime bundle (``web/js/i18n.js``) is
  covered by the existing ``web-assets-fresh`` release-gate check, not here.
* ``zh-Hant`` is derived at runtime from ``zh-CN`` (``DICTIONARY_ZH_HANT`` +
  ``toTraditional``), so the gate asserts that the derivation marker exists and
  evaluates ``zh-Hant`` as ``zh-CN``. It does not re-implement the converter.
* Failures that are already reviewed and owned are declared in the contract as
  ``declared_open_items``; the gate reports them as open (exit 2) instead of
  silently passing, and a declaration that no longer reproduces is reported so
  the contract cannot go stale.

Exit codes: 0 = consistent, 1 = undeclared drift, 2 = declared open items
present or a declaration no longer reproduces.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_CONTRACT = "docs/architecture/launch-surface-consistency-contract.json"

CHECK_IDS = (
    "C0_i18n_dictionary_parse",
    "C1_announcement_referenced_pages",
    "C2_trial_marking_present_and_used",
    "C3_official_source_attribution",
    "C4_free_preview_disclaimer",
    "C5_legal_entity_facts",
    "C6_unfilled_placeholders",
    "C7_jurisdiction_scope",
    "C8_consumer_wording_discipline",
)

CONTRACT_KEYS = (
    "contract_version",
    "announcement",
    "web_dir",
    "i18n_source",
    "source_locales",
    "derived_locales",
    "derivation_marker",
    "referenced_pages",
    "trial_marking",
    "official_sources",
    "disclaimers",
    "entity_facts",
    "jurisdiction",
    "placeholder_tokens",
    "wording_discipline",
    "declared_open_items",
)

UNASSIGNED_OWNER_VALUES = {"", "tbd", "todo", "unassigned", "unknown", "none", "null"}

LOCALE_BLOCK = re.compile(r'(?:"(?P<quoted>[a-zA-Z][a-zA-Z-]*)"|(?P<bare>[a-z]{2}))\s*:\s*\{')
KEY_VALUE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"')
OVERLAY_ENTRY = re.compile(
    r'"(?P<key>(?:[^"\\]|\\.)*)"\s*:\s*\{\s*"zh-CN"\s*:\s*"(?P<zhcn>(?:[^"\\]|\\.)*)"\s*,\s*'
    r'(?:"zh-Hant"\s*:\s*"(?P<zhhant>(?:[^"\\]|\\.)*)"\s*,\s*)?'
    r'en\s*:\s*"(?P<en>(?:[^"\\]|\\.)*)"\s*,\s*ja\s*:\s*"(?P<ja>(?:[^"\\]|\\.)*)"\s*\}'
)
ANNOUNCEMENT_PAGE = re.compile(r"`([a-z0-9][a-z0-9._-]*\.html)`")
DATA_I18N = re.compile(r'data-i18n(?:-[a-z-]+)?="([^"]+)"')


class ContractError(RuntimeError):
    """Raised when the contract itself is malformed."""


class Finding:
    """One failed coordinate; declared open items are matched against it."""

    __slots__ = ("check_id", "surface", "key", "detail")

    def __init__(self, check_id: str, surface: str, key: str, detail: str) -> None:
        self.check_id = check_id
        self.surface = surface
        self.key = key
        self.detail = detail

    @property
    def coordinate(self) -> str:
        return f"{self.check_id}|{self.surface}|{self.key}|{self.detail}"


def load_contract(path: Path) -> dict[str, Any]:
    """Load and shape-check the contract without touching any other surface."""

    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ContractError(f"contract is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise ContractError(f"contract is not valid JSON: {error}") from error
    if not isinstance(contract, dict):
        raise ContractError("contract must be a JSON object")
    for key in CONTRACT_KEYS:
        if key not in contract:
            raise ContractError(f"contract is missing required section: {key}")
    if contract["contract_version"] != 1:
        raise ContractError("contract_version must be 1")
    if not isinstance(contract["declared_open_items"], list):
        raise ContractError("declared_open_items must be a list")
    seen: set[str] = set()
    for item in contract["declared_open_items"]:
        if not isinstance(item, dict):
            raise ContractError("declared_open_items entries must be objects")
        for field in ("id", "check", "coordinate_contains", "summary", "owner", "target"):
            if not item.get(field):
                raise ContractError(
                    f"declared open item {item.get('id', '?')} is missing {field}"
                )
        if item["id"] in seen:
            raise ContractError(f"declared open item id is duplicated: {item['id']}")
        seen.add(item["id"])
        if item["check"] not in CHECK_IDS:
            raise ContractError(
                f"declared open item {item['id']} names unknown check {item['check']}"
            )
        if item["owner"].strip().lower() in UNASSIGNED_OWNER_VALUES:
            raise ContractError(
                f"declared open item {item['id']} must name an assigned owner"
            )
    return contract


def _unescape(value: str) -> str:
    return value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def _block_end(text: str, open_index: int) -> int:
    depth = 0
    index = open_index
    while index < len(text):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ContractError("unbalanced object literal in the i18n source")


def parse_dictionary(
    text: str,
    source_locales: Sequence[str],
    derived_locales: Mapping[str, str],
    derivation_marker: str,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Extract locale -> key -> value from the readable i18n source."""

    errors: list[str] = []
    if text and derivation_marker not in text:
        errors.append(f"i18n source is missing the derived-locale marker {derivation_marker!r}")

    dictionaries: dict[str, dict[str, str]] = {}
    for locale in source_locales:
        located = False
        for match in LOCALE_BLOCK.finditer(text):
            name = match.group("quoted") or match.group("bare")
            if name != locale:
                continue
            open_index = text.index("{", match.end() - 1)
            block = text[open_index : _block_end(text, open_index) + 1]
            dictionaries[locale] = {
                _unescape(key): _unescape(value) for key, value in KEY_VALUE.findall(block)
            }
            located = True
            break
        if not located:
            errors.append(f"i18n source has no {locale} dictionary block")

    for match in OVERLAY_ENTRY.finditer(text):
        key = _unescape(match.group("key"))
        zh_hant = match.group("zhhant")
        values = {
            "zh-CN": _unescape(match.group("zhcn")),
            "zh-Hant": _unescape(zh_hant) if zh_hant is not None else _unescape(match.group("zhcn")),
            "en": _unescape(match.group("en")),
            "ja": _unescape(match.group("ja")),
        }
        for locale, value in values.items():
            if locale in dictionaries and value:
                # The runtime bundle applies the per-key overlay after the base
                # dictionary, so the overlay wins; mirror that here.
                dictionaries[locale][key] = value

    for derived, fallback in derived_locales.items():
        if fallback not in dictionaries:
            errors.append(
                f"derived locale {derived} needs its fallback locale {fallback} to be parsed"
            )
            continue
        dictionaries[derived] = dict(dictionaries[fallback])

    return dictionaries, errors


def _read(root: Path, relative: str, errors: list[str]) -> str:
    path = root / relative
    if not path.is_file():
        errors.append(f"surface is missing: {relative}")
        return ""
    return path.read_text(encoding="utf-8")


def _lookup(dictionaries: Mapping[str, Mapping[str, str]], locale: str, key: str) -> str:
    return dictionaries.get(locale, {}).get(key, "") or ""


def audit(root: Path, contract: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return the machine result and the undeclared violation list."""

    findings: list[Finding] = []

    def fail(check_id: str, surface: str, key: str, detail: str) -> None:
        findings.append(Finding(check_id, surface, key, detail))

    read_errors: list[str] = []
    dictionaries, dictionary_errors = parse_dictionary(
        _read(root, contract["i18n_source"], read_errors),
        contract["source_locales"],
        contract["derived_locales"],
        contract["derivation_marker"],
    )
    for error in dictionary_errors + [error for error in read_errors if "i18n" in error]:
        fail("C0_i18n_dictionary_parse", contract["i18n_source"], "-", error)

    locales = list(contract["source_locales"]) + list(contract["derived_locales"])
    announcement = _read(root, contract["announcement"], read_errors)
    for error in read_errors:
        if "announcement" in error:
            fail("C1_announcement_referenced_pages", contract["announcement"], "-", error)
    web_dir = root / contract["web_dir"]
    page_names = sorted(path.name for path in web_dir.glob("*.html")) if web_dir.is_dir() else []
    page_texts = {name: (web_dir / name).read_text(encoding="utf-8") for name in page_names}

    # C1 - the announcement's referenced pages exist and are reachable.
    declared_pages = list(contract["referenced_pages"])
    referenced = set(ANNOUNCEMENT_PAGE.findall(announcement))
    for name in sorted(referenced - set(declared_pages)):
        fail(
            "C1_announcement_referenced_pages",
            contract["announcement"],
            name,
            "announcement references a page that is not declared in the contract",
        )
    for name in sorted(set(declared_pages) - referenced):
        fail(
            "C1_announcement_referenced_pages",
            contract["announcement"],
            name,
            "contract declares a page the announcement does not reference",
        )
    for name in declared_pages:
        if name not in page_texts:
            fail(
                "C1_announcement_referenced_pages",
                f"{contract['web_dir']}/{name}",
                "-",
                "page is missing",
            )
            continue
        inbound = [
            other
            for other, text in page_texts.items()
            if other != name and f'href="{name}"' in text
        ]
        if not inbound:
            fail(
                "C1_announcement_referenced_pages",
                f"{contract['web_dir']}/{name}",
                "-",
                "page is not linked from any site page",
            )

    # C2 - the trial marking the announcement promises exists and is used.
    trial = contract["trial_marking"]
    for key in trial["keys"]:
        for locale in locales:
            if not _lookup(dictionaries, locale, key):
                fail(
                    "C2_trial_marking_present_and_used",
                    contract["i18n_source"],
                    key,
                    f"{locale} value is empty or missing",
                )
    for name in trial["pages"]:
        text = page_texts.get(name, "")
        if not text:
            fail(
                "C2_trial_marking_present_and_used",
                f"{contract['web_dir']}/{name}",
                "-",
                "page is missing",
            )
            continue
        if not any(f'{trial["attribute"]}="{key}"' in text for key in trial["keys"]):
            fail(
                "C2_trial_marking_present_and_used",
                f"{contract['web_dir']}/{name}",
                "-",
                "page does not render the trial marking",
            )

    # C3 / C4 - per-locale wording the announcement promises on the site.
    for check_id, section in (
        ("C3_official_source_attribution", contract["official_sources"]),
        ("C4_free_preview_disclaimer", contract["disclaimers"]),
    ):
        for locale, tokens in section["tokens"].items():
            for token in tokens:
                if not any(token in _lookup(dictionaries, locale, key) for key in section["keys"]):
                    fail(
                        check_id,
                        contract["i18n_source"],
                        ",".join(section["keys"]),
                        f"{locale} has no surface carrying {token!r}",
                    )

    # C5 - legal entity facts agree across the declared surfaces.
    for surface in contract["entity_facts"]["surfaces"]:
        text = _read(root, surface["path"], [])
        for token in surface["required_tokens"]:
            if token not in text:
                fail("C5_legal_entity_facts", surface["path"], "required", f"missing {token!r}")
        for token in surface["forbidden_tokens"]:
            if token in text:
                fail(
                    "C5_legal_entity_facts",
                    surface["path"],
                    "representative",
                    f"carries {token!r}",
                )

    # C6 - no unfilled placeholder reaches the pages the announcement points at.
    placeholders = contract["placeholder_tokens"]
    for name in declared_pages:
        text = page_texts.get(name, "")
        for token in placeholders["page_text"]:
            if token in text:
                fail(
                    "C6_unfilled_placeholders",
                    f"{contract['web_dir']}/{name}",
                    "page-text",
                    f"page text carries placeholder token {token!r}",
                )
        for key in sorted(set(DATA_I18N.findall(text))):
            for locale in locales:
                value = _lookup(dictionaries, locale, key)
                if not value:
                    fail(
                        "C6_unfilled_placeholders",
                        contract["i18n_source"],
                        key,
                        f"{locale} value is empty for a key used by {name}",
                    )
                    continue
                for token in placeholders["values"]:
                    if token in value:
                        fail(
                            "C6_unfilled_placeholders",
                            contract["i18n_source"],
                            key,
                            f"{locale} carries placeholder token {token!r}",
                        )

    # C7 - the site legal wording matches the recorded jurisdiction decision.
    jurisdiction = contract["jurisdiction"]
    for locale in locales:
        for key in sorted(dictionaries.get(locale, {})):
            if not key.startswith(jurisdiction["scan_key_prefix"]):
                continue
            value = _lookup(dictionaries, locale, key)
            for token in jurisdiction["forbidden_tokens"]:
                if token in value:
                    fail(
                        "C7_jurisdiction_scope",
                        contract["i18n_source"],
                        key,
                        f"{locale} contradicts the {jurisdiction['primary']} scope: {token!r}",
                    )

    # C8 - consumer wording discipline, with reviewed exceptions.
    discipline = contract["wording_discipline"]
    exceptions = {exception["key"]: exception for exception in discipline["declared_exceptions"]}
    reproduced_exceptions: set[str] = set()
    for locale in locales:
        for key in sorted(dictionaries.get(locale, {})):
            value = _lookup(dictionaries, locale, key)
            for token in discipline["banned_tokens"]:
                if token not in value:
                    continue
                if key in exceptions:
                    reproduced_exceptions.add(key)
                    continue
                fail(
                    "C8_consumer_wording_discipline",
                    contract["i18n_source"],
                    key,
                    f"{locale} uses banned consumer wording {token!r}",
                )
    for key in sorted(set(exceptions) - reproduced_exceptions):
        fail(
            "C8_consumer_wording_discipline",
            contract["i18n_source"],
            key,
            "declared wording exception no longer reproduces; update the contract",
        )

    # Split reviewed-and-owned failures from undeclared drift.
    matches: dict[str, list[str]] = {
        item["id"]: [] for item in contract["declared_open_items"]
    }
    undeclared: list[Finding] = []
    for finding in findings:
        owner = None
        for item in contract["declared_open_items"]:
            if item["check"] != finding.check_id:
                continue
            needles = item["coordinate_contains"]
            if isinstance(needles, str):
                needles = [needles]
            if any(needle in finding.coordinate for needle in needles):
                owner = item
                break
        if owner is None:
            undeclared.append(finding)
        else:
            matches[owner["id"]].append(finding.coordinate)

    declared_status: list[dict[str, Any]] = []
    for item in contract["declared_open_items"]:
        coordinates = sorted(matches[item["id"]])
        declared_status.append(
            {
                "id": item["id"],
                "status": "open" if coordinates else "resolved",
                "summary": item["summary"],
                "owner": item["owner"],
                "target": item["target"],
                "blocking": bool(item.get("blocking")),
                "coordinates": coordinates,
            }
        )

    undeclared_coordinates = sorted(finding.coordinate for finding in undeclared)
    declared_coordinates = {
        coordinate
        for entry in declared_status
        for coordinate in entry["coordinates"]
    }
    if undeclared_coordinates:
        status = "fail"
    elif declared_coordinates or any(entry["status"] == "resolved" for entry in declared_status):
        status = "open"
    else:
        status = "pass"

    check_entries: list[dict[str, Any]] = []
    for check_id in CHECK_IDS:
        failed = sorted(
            finding.coordinate for finding in findings if finding.check_id == check_id
        )
        check_entries.append(
            {
                "id": check_id,
                "ok": not failed,
                "declared_open": bool(failed)
                and all(coordinate in declared_coordinates for coordinate in failed),
                "detail": "; ".join(failed),
            }
        )

    result: dict[str, Any] = {
        "contract_version": contract["contract_version"],
        "status": status,
        "production_contacted": False,
        "network_used": False,
        "checks": check_entries,
        "declared_open_items": declared_status,
        "errors": undeclared_coordinates,
    }
    return result, undeclared_coordinates


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    contract_path = args.contract or (args.root / DEFAULT_CONTRACT)
    try:
        contract = load_contract(contract_path)
    except ContractError as error:
        print(f"contract error: {error}")
        return 1

    result, errors = audit(args.root, contract)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for check in result["checks"]:
            label = "PASS" if check["ok"] else "FAIL (declared open)" if check["declared_open"] else "FAIL"
            print(f"[{label}] {check['id']}")
            for detail in (check["detail"].split("; ") if check["detail"] else []):
                print(f"        {detail}")
        for item in result["declared_open_items"]:
            print(
                f"[{item['status'].upper()}] {item['id']}"
                f"{' (blocking)' if item['blocking'] else ''} | owner: {item['owner']} | target: {item['target']}"
            )
            print(f"        {item['summary']}")
            for coordinate in item["coordinates"]:
                print(f"        at: {coordinate}")
        print(f"status: {result['status']} | undeclared violations: {len(errors)}")
        for error in errors:
            print(f"  violation: {error}")

    if result["status"] == "fail":
        return 1
    if result["status"] == "open":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
