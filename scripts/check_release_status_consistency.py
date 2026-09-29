#!/usr/bin/env python3
"""Offline release-status consistency gate (10-07 countdown, D-8 offline half).

Reconciles the documents that carry the 2026-10-07 release verdict against each
other and against the machine-readable state files that evidence them:

* every C-item status table inside the go/no-go checklist,
* the checklist verdict (header block vs the final-verdict section),
* the countdown plan day rows that reference a C-item,
* the checked-in JSON state files (approval / release evidence / staging smoke).

Scope of the claim (do not over-read this tool):

* It is **offline**: no network, no socket, no credentials, no environment
  variables, no database. It proves that the documents agree with each other and
  with the recorded state - never that the state itself is true or current.
* Status classes are read from the status glyph of the first status-bearing cell
  of a table row, so the check does not depend on column position or line
  numbers.
* Sections are registered in the contract. A section that carries C-item rows
  but is not registered is a finding, so a new table cannot escape the gate.
  Historical sections must keep their caveat, otherwise a superseded verdict
  could be cited as current.
* Failures already reviewed and owned are declared in the contract as
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

DEFAULT_CONTRACT = "docs/architecture/release-status-consistency-contract.json"

CHECK_IDS = (
    "C0_contract_structure",
    "C1_section_registry",
    "C2_historical_marking",
    "C3_current_item_coverage",
    "C4_machine_state_bindings",
    "C5_state_claims",
    "C6_verdict_agreement",
    "C7_plan_vs_checklist_scope",
)

CONTRACT_KEYS = (
    "contract_version",
    "purpose",
    "documents",
    "item_row_pattern",
    "item_universe",
    "status_classes",
    "status_cell_rule",
    "sections",
    "verdict",
    "state_files",
    "bindings",
    "state_claims",
    "plan_scope",
    "declared_open_items",
)

UNASSIGNED_OWNER_VALUES = {"", "tbd", "todo", "unassigned", "unknown", "none", "null"}

HEADING_RE = re.compile(r"^#{1,6} ")


class ContractError(RuntimeError):
    """Raised when the contract itself is unusable."""


@dataclass(frozen=True)
class Finding:
    check_id: str
    coordinate: str
    detail: str


@dataclass(frozen=True)
class Row:
    section_id: str
    item: str
    status_class: str | None
    cell: str


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise ContractError(f"contract not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"contract is not valid JSON: {exc}") from exc
    _require(isinstance(contract, dict), "contract must be a JSON object")
    missing = [key for key in CONTRACT_KEYS if key not in contract]
    _require(not missing, f"contract is missing keys: {', '.join(missing)}")
    _require(
        isinstance(contract["contract_version"], int) and contract["contract_version"] >= 1,
        "contract_version must be a positive integer",
    )
    documents = contract["documents"]
    _require(isinstance(documents, dict) and documents, "documents must be a non-empty object")
    for name, relative in documents.items():
        _require(
            isinstance(relative, str) and relative and not Path(relative).is_absolute(),
            f"document {name!r} must be a repository-relative path",
        )

    item_pattern = contract["item_row_pattern"]
    _require(isinstance(item_pattern, str) and item_pattern, "item_row_pattern is required")
    _require(
        isinstance(contract["status_cell_rule"], str) and contract["status_cell_rule"],
        "status_cell_rule is required",
    )
    try:
        re.compile(item_pattern)
    except re.error as exc:
        raise ContractError(f"item_row_pattern is not a valid regex: {exc}") from exc

    universe = contract["item_universe"]
    _require(
        isinstance(universe, list) and universe and all(isinstance(item, str) for item in universe),
        "item_universe must be a non-empty list of item ids",
    )
    _require(len(set(universe)) == len(universe), "item_universe must not contain duplicates")

    classes: dict[str, str] = {}
    status_classes = contract["status_classes"]
    _require(
        isinstance(status_classes, dict) and status_classes,
        "status_classes must be a non-empty object",
    )
    for class_name, glyphs in status_classes.items():
        _require(
            isinstance(glyphs, list) and glyphs and all(isinstance(g, str) and g for g in glyphs),
            f"status_classes[{class_name!r}] must be a non-empty list of glyphs",
        )
        for glyph in glyphs:
            _require(
                glyph not in classes,
                f"glyph {glyph!r} is claimed by both {classes.get(glyph)!r} and {class_name!r}",
            )
            classes[glyph] = class_name

    section_ids: set[str] = set()
    for section in contract["sections"]:
        for key in ("id", "heading_prefix", "kind"):
            _require(
                isinstance(section.get(key), str) and section[key],
                f"every section needs a non-empty {key!r}",
            )
        _require(section["id"] not in section_ids, f"duplicate section id: {section['id']}")
        section_ids.add(section["id"])
        _require(
            section["kind"] in {"historical", "current", "current_verdict"},
            f"section {section['id']!r} has an unknown kind {section['kind']!r}",
        )
        if section["kind"] == "historical":
            _require(
                isinstance(section.get("historical_marker"), str)
                and section["historical_marker"],
                f"historical section {section['id']!r} needs a historical_marker",
            )

    state_ids: set[str] = set()
    for state in contract["state_files"]:
        for key in ("id", "path", "pointer"):
            _require(
                isinstance(state.get(key), str) and state[key],
                f"every state file needs a non-empty {key!r}",
            )
        _require(state["id"] not in state_ids, f"duplicate state file id: {state['id']}")
        state_ids.add(state["id"])
        _require(state["pointer"].startswith("/"), "state file pointers must start with '/'")

    binding_ids: set[str] = set()
    for binding in contract["bindings"]:
        for key in ("id", "kind", "state_file", "pointer"):
            _require(
                isinstance(binding.get(key), str) and binding[key],
                f"every binding needs a non-empty {key!r}",
            )
        _require(binding["id"] not in binding_ids, f"duplicate binding id: {binding['id']}")
        binding_ids.add(binding["id"])
        _require(
            binding["state_file"] in state_ids,
            f"binding {binding['id']!r} names an unregistered state file",
        )
        if binding["kind"] == "item_class":
            _require(
                binding.get("item") in universe,
                f"binding {binding['id']!r} names an item outside item_universe",
            )
            rules = binding.get("allowed_classes_when")
            _require(
                isinstance(rules, list) and rules,
                f"binding {binding['id']!r} needs allowed_classes_when",
            )
            for rule in rules:
                _require(
                    isinstance(rule.get("values"), list) and rule["values"],
                    f"binding {binding['id']!r} has an empty values list",
                )
                _require(
                    isinstance(rule.get("classes"), list) and rule["classes"],
                    f"binding {binding['id']!r} has an empty classes list",
                )
                for class_name in rule["classes"]:
                    _require(
                        class_name in status_classes,
                        f"binding {binding['id']!r} names unknown class {class_name!r}",
                    )
        elif binding["kind"] == "verdict":
            mapping = binding.get("value_to_verdict")
            _require(
                isinstance(mapping, dict) and mapping,
                f"verdict binding {binding['id']!r} needs value_to_verdict",
            )
            for verdict in mapping.values():
                _require(
                    verdict in contract["verdict"]["required_tokens"],
                    f"verdict binding {binding['id']!r} maps to unknown verdict {verdict!r}",
                )
        else:
            raise ContractError(f"binding {binding['id']!r} has an unknown kind {binding['kind']!r}")

    for claim in contract["state_claims"]:
        for key in ("id", "state_file", "pointer"):
            _require(
                isinstance(claim.get(key), str) and claim[key],
                f"every state claim needs a non-empty {key!r}",
            )
        _require(
            claim["state_file"] in state_ids,
            f"state claim {claim['id']!r} names an unregistered state file",
        )
        for key in ("current_value_sections", "stale_value_sections", "stale_values"):
            _require(
                isinstance(claim.get(key), list),
                f"state claim {claim['id']!r} needs a {key!r} list",
            )
        for section_id in claim["current_value_sections"] + claim["stale_value_sections"]:
            _require(
                section_id in section_ids,
                f"state claim {claim['id']!r} names unknown section {section_id!r}",
            )

    plan = contract["plan_scope"]
    _require(plan.get("document") in documents, "plan_scope.document must name a document")
    for key in ("row_pattern", "item_reference_pattern"):
        _require(
            isinstance(plan.get(key), str) and plan[key],
            f"plan_scope.{key} is required",
        )
        try:
            re.compile(plan[key])
        except re.error as exc:
            raise ContractError(f"plan_scope.{key} is not a valid regex: {exc}") from exc
    _require(
        isinstance(plan.get("closed_markers"), list) and plan["closed_markers"],
        "plan_scope.closed_markers must be a non-empty list",
    )

    declared_ids: set[str] = set()
    for item in contract["declared_open_items"]:
        for key in ("id", "check", "summary", "owner", "target"):
            _require(
                isinstance(item.get(key), str) and item[key],
                f"every declared open item needs a non-empty {key!r}",
            )
        _require(item["id"] not in declared_ids, f"duplicate declared item id: {item['id']}")
        declared_ids.add(item["id"])
        _require(
            item["check"] in CHECK_IDS,
            f"declared item {item['id']!r} names an unknown check {item['check']!r}",
        )
        _require(
            item["owner"].strip().lower() not in UNASSIGNED_OWNER_VALUES,
            f"declared item {item['id']!r} has no real owner",
        )
        _require(
            item["target"].strip().lower() not in UNASSIGNED_OWNER_VALUES,
            f"declared item {item['id']!r} has no real target",
        )
        needles = item["coordinate_contains"]
        if isinstance(needles, str):
            needles = [needles]
        _require(
            isinstance(needles, list) and needles and all(isinstance(n, str) and n for n in needles),
            f"declared item {item['id']!r} needs coordinate_contains",
        )

    _require(
        isinstance(contract["verdict"], dict)
        and isinstance(contract["verdict"].get("pattern"), str)
        and contract["verdict"]["pattern"],
        "verdict.pattern is required",
    )
    try:
        re.compile(contract["verdict"]["pattern"])
    except re.error as exc:
        raise ContractError(f"verdict.pattern is not a valid regex: {exc}") from exc
    return contract


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.exists():
        raise ContractError(f"document not found: {relative}")
    return path.read_text(encoding="utf-8")


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split a markdown document into (heading_line, body) pairs.

    The first entry is the preamble, whose heading line is the empty string.
    """

    sections: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in text.splitlines():
        if HEADING_RE.match(line):
            sections.append((heading, "\n".join(body)))
            heading = line.strip()
            body = []
        else:
            body.append(line)
    sections.append((heading, "\n".join(body)))
    return sections


def _classify_cell(cell: str, glyph_to_class: Mapping[str, str]) -> str | None:
    """Classify a cell by the status glyph it *starts* with.

    Cells that merely end with a glyph (e.g. an owner cell reading ``Codex ✅``)
    must not be read as the status cell, so the match is anchored to the start
    after stripping markdown emphasis and whitespace.
    """

    stripped = cell.lstrip("*_` \t")
    for glyph, class_name in glyph_to_class.items():
        if stripped.startswith(glyph):
            return class_name
    return None


def item_rows(
    section_id: str,
    body: str,
    row_re: re.Pattern[str],
    glyph_to_class: Mapping[str, str],
) -> list[Row]:
    rows: list[Row] = []
    for line in body.splitlines():
        match = row_re.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.split("|")][1:-1]
        status_cell = ""
        status_class: str | None = None
        for cell in cells[1:]:
            candidate = _classify_cell(cell, glyph_to_class)
            if candidate is not None:
                status_cell = cell
                status_class = candidate
                break
        rows.append(Row(section_id, match.group(1), status_class, status_cell))
    return rows


def _resolve_pointer(document: Any, pointer: str) -> Any:
    current = document
    for token in pointer.strip("/").split("/"):
        if isinstance(current, dict):
            if token not in current:
                raise ContractError(f"pointer {pointer!r} does not exist")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise ContractError(f"pointer {pointer!r} does not exist") from exc
        else:
            raise ContractError(f"pointer {pointer!r} does not exist")
    return current


def audit(
    root: Path,
    contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    if contract is None:
        contract = load_contract(root / DEFAULT_CONTRACT)

    findings: list[Finding] = []
    glyph_to_class = {
        glyph: class_name
        for class_name, glyphs in contract["status_classes"].items()
        for glyph in glyphs
    }
    row_re = re.compile(contract["item_row_pattern"])

    # ---- C1: every section that carries C-item rows must be registered ------
    documents = contract["documents"]
    checklist_rel = documents["checklist"]
    checklist_sections = split_sections(_read(root, checklist_rel))
    registered: dict[str, dict[str, Any]] = {}
    for section in contract["sections"]:
        prefix = section["heading_prefix"]
        matches = [heading for heading, _ in checklist_sections if heading.startswith(prefix)]
        if not matches:
            findings.append(
                Finding(
                    "C1_section_registry",
                    f"section:{section['id']}",
                    f"registered heading {prefix!r} is no longer present in {checklist_rel}",
                )
            )
            continue
        heading = matches[0]
        body = next(body for candidate, body in checklist_sections if candidate == heading)
        registered[section["id"]] = {"heading": heading, "body": body, "kind": section["kind"]}

    for heading, body in checklist_sections:
        if not any(row_re.match(line) for line in body.splitlines()):
            continue
        if heading not in {entry["heading"] for entry in registered.values()}:
            findings.append(
                Finding(
                    "C1_section_registry",
                    f"unregistered-section:{heading or '<preamble>'}",
                    "this section carries C-item status rows but is not registered in the contract",
                )
            )

    # ---- C2: historical sections must keep their caveat ---------------------
    caveat = contract["verdict"].get("historical_caveat", "")
    for section in contract["sections"]:
        entry = registered.get(section["id"])
        if entry is None or section["kind"] != "historical":
            continue
        marker = section["historical_marker"]
        if marker not in entry["body"]:
            findings.append(
                Finding(
                    "C2_historical_marking",
                    f"section:{section['id']}",
                    f"historical marker {marker!r} is missing, so a superseded verdict could be cited as current",
                )
            )
        if caveat and caveat not in entry["body"]:
            findings.append(
                Finding(
                    "C2_historical_marking",
                    f"section:{section['id']}:caveat",
                    f"the document no longer states {caveat!r}",
                )
            )

    # ---- C3: the current table must judge every item exactly once -----------
    current_sections = [
        section
        for section in contract["sections"]
        if section["kind"] == "current" and section["id"] in registered
    ]
    current_rows: dict[str, Row] = {}
    for section in current_sections:
        entry = registered[section["id"]]
        rows = item_rows(section["id"], entry["body"], row_re, glyph_to_class)
        for row in rows:
            if row.status_class is None:
                findings.append(
                    Finding(
                        "C3_current_item_coverage",
                        f"section:{row.section_id}:{row.item}",
                        "row carries no recognised status glyph",
                    )
                )
                continue
            if row.item in current_rows:
                findings.append(
                    Finding(
                        "C3_current_item_coverage",
                        f"section:{row.section_id}:{row.item}:duplicate",
                        "the item is judged more than once in the current tables",
                    )
                )
                continue
            current_rows[row.item] = row
    for item in contract["item_universe"]:
        if item not in current_rows:
            findings.append(
                Finding(
                    "C3_current_item_coverage",
                    f"current-table:{item}",
                    "the current C-item table no longer judges this item",
                )
            )

    # ---- shared state file reads -------------------------------------------
    state_values: dict[str, Any] = {}
    for state in contract["state_files"]:
        document = json.loads(_read(root, state["path"]))
        try:
            value = _resolve_pointer(document, state["pointer"])
        except ContractError as exc:
            findings.append(
                Finding(
                    "C4_machine_state_bindings",
                    f"state:{state['id']}{state['pointer']}",
                    str(exc),
                )
            )
            continue
        state_values[state["id"]] = value

    # ---- C4: machine-state bindings ---------------------------------------
    for binding in contract["bindings"]:
        if binding["kind"] != "item_class":
            continue
        state_id = binding["state_file"]
        if state_id not in state_values:
            continue
        value = state_values[state_id]
        row = current_rows.get(binding["item"])
        if row is None or row.status_class is None:
            continue
        rule = next(
            (rule for rule in binding["allowed_classes_when"] if value in rule["values"]),
            None,
        )
        if rule is None:
            findings.append(
                Finding(
                    "C4_machine_state_bindings",
                    f"binding:{binding['id']}:{value}",
                    f"state value {value!r} is not covered by the contract; update the contract with an explicit rule",
                )
            )
            continue
        if row.status_class not in rule["classes"]:
            findings.append(
                Finding(
                    "C4_machine_state_bindings",
                    f"binding:{binding['id']}:{binding['item']}:{row.status_class}:vs:{value}",
                    f"{binding['item']} is reported as {row.status_class} while {state_id}{binding['pointer']} is {value!r}: {rule['reason']}",
                )
            )

    # ---- C5: state claims inside the current sections ----------------------
    for claim in contract["state_claims"]:
        state_id = claim["state_file"]
        if state_id not in state_values:
            continue
        value = state_values[state_id]
        for section_id in claim["current_value_sections"]:
            entry = registered.get(section_id)
            if entry is None:
                continue
            if str(value) not in entry["body"]:
                findings.append(
                    Finding(
                        "C5_state_claims",
                        f"state-claim:{claim['id']}:{section_id}:missing:{value}",
                        f"section {section_id!r} does not quote the current {state_id}{claim['pointer']} value {value!r}",
                    )
                )
        for section_id in claim["stale_value_sections"]:
            entry = registered.get(section_id)
            if entry is None:
                continue
            for stale in claim["stale_values"]:
                if stale in entry["body"]:
                    findings.append(
                        Finding(
                            "C5_state_claims",
                            f"state-claim:{claim['id']}:{section_id}:stale:{stale}",
                            f"section {section_id!r} still claims {stale!r} while the recorded state is {value!r}",
                        )
                    )

    # ---- C6: one verdict, and it matches the recorded state ---------------
    verdict_re = re.compile(contract["verdict"]["pattern"])
    observed = set()
    for _, body in checklist_sections:
        observed.update(verdict_re.findall(body))
    if len(observed) > 1:
        findings.append(
            Finding(
                "C6_verdict_agreement",
                "verdict:" + ",".join(sorted(observed)),
                "the document states more than one 工程侧 verdict",
            )
        )
    for binding in contract["bindings"]:
        if binding["kind"] != "verdict":
            continue
        state_id = binding["state_file"]
        if state_id not in state_values:
            continue
        value = state_values[state_id]
        expected = binding.get("value_to_verdict", {}).get(value)
        if expected is None:
            findings.append(
                Finding(
                    "C6_verdict_agreement",
                    f"binding:{binding['id']}:{value}",
                    f"state value {value!r} is not covered by the contract; update the contract with an explicit rule",
                )
            )
            continue
        for token in sorted(observed):
            if token != expected:
                findings.append(
                    Finding(
                        "C6_verdict_agreement",
                        f"verdict:{token}:vs:{value}",
                        f"the document states {token!r} while {state_id}{binding['pointer']} is {value!r}",
                    )
                )
        verdict_section = registered.get("final_verdict")
        if verdict_section is not None and expected not in verdict_section["body"]:
            findings.append(
                Finding(
                    "C6_verdict_agreement",
                    f"verdict:{expected}:missing-in-final-verdict",
                    "the final-verdict section does not state the verdict implied by the recorded state",
                )
            )

    # ---- C7: countdown plan day rows vs the current item table ------------
    plan = contract["plan_scope"]
    plan_text = _read(root, documents[plan["document"]])
    plan_row_re = re.compile(plan["row_pattern"])
    plan_item_re = re.compile(plan["item_reference_pattern"])
    for line in plan_text.splitlines():
        if not plan_row_re.match(line):
            continue
        cells = [cell.strip() for cell in line.split("|")][1:-1]
        if len(cells) < 3:
            continue
        day = cells[0].strip("* ")
        body = " | ".join(cells[2:])
        closed = any(marker in body for marker in plan["closed_markers"])
        for item in sorted(set(plan_item_re.findall(body))):
            row = current_rows.get(item)
            if row is None or row.status_class is None:
                continue
            checklist_closed = row.status_class == "closed"
            if closed and not checklist_closed:
                findings.append(
                    Finding(
                        "C7_plan_vs_checklist_scope",
                        f"plan:{day}:{item}:plan-closed-checklist-{row.status_class}",
                        f"{day} is marked closed in the countdown plan while the checklist reports {item} as {row.status_class}",
                    )
                )
            elif not closed and checklist_closed:
                findings.append(
                    Finding(
                        "C7_plan_vs_checklist_scope",
                        f"plan:{day}:{item}:plan-open-checklist-closed",
                        f"{day} still lists {item} as work to do while the checklist reports it closed",
                    )
                )

    # ---- declared open items ----------------------------------------------
    matches: dict[str, list[str]] = {
        item["id"]: [] for item in contract["declared_open_items"]
    }
    undeclared: list[Finding] = []
    for finding in findings:
        owner_item = None
        for item in contract["declared_open_items"]:
            if item["check"] != finding.check_id:
                continue
            needles = item["coordinate_contains"]
            if isinstance(needles, str):
                needles = [needles]
            if any(needle in finding.coordinate for needle in needles):
                owner_item = item
                break
        if owner_item is None:
            undeclared.append(finding)
        else:
            matches[owner_item["id"]].append(finding.coordinate)

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
        coordinate for entry in declared_status for coordinate in entry["coordinates"]
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


def _render(result: Mapping[str, Any]) -> str:
    lines = [
        f"release-status consistency: {result['status']}",
        f"contract_version={result['contract_version']} production_contacted=False network_used=False",
    ]
    for check in result["checks"]:
        flag = "PASS" if check["ok"] else ("OPEN" if check["declared_open"] else "FAIL")
        lines.append(f"  [{flag}] {check['id']}")
        if check["detail"]:
            for coordinate in check["detail"].split("; "):
                lines.append(f"          - {coordinate}")
    for item in result["declared_open_items"]:
        lines.append(
            f"  declared {item['status']}: {item['id']} (owner={item['owner']}, target={item['target']}, blocking={item['blocking']})"
        )
        for coordinate in item["coordinates"]:
            lines.append(f"          - {coordinate}")
    if result["errors"]:
        lines.append("undeclared drift:")
        for coordinate in result["errors"]:
            lines.append(f"  - {coordinate}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    contract_path = args.contract or (root / DEFAULT_CONTRACT)
    try:
        contract = load_contract(contract_path)
        result, undeclared = audit(root, contract)
    except ContractError as exc:
        print(f"contract error: {exc}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_render(result))

    if undeclared:
        return 1
    if result["status"] == "open":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
