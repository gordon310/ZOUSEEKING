#!/usr/bin/env python3
"""Offline gate for the canonical migration ledger (G4 migration dimension).

This check proves only static, repository-local facts: that the canonical
forward history is well-formed and append-only, that every already-applied
migration still hashes to the bytes that were pinned and recorded, that the
current documents claiming a zero-gap ledger still agree with the repository,
and that destructive SQL keywords only appear where they were registered.

It does not read the real production or staging migration ledger, does not
execute SQL, does not connect to any provider, and is not a substitute for the
live ledger read.  It uses no network, no credentials and no environment
variables, and it never writes to the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA_VERSION = 1
EXPECTED_CONTRACT = "migration-ledger-contract/v1"
DEFAULT_CONTRACT = Path("docs/architecture/migration-ledger-contract.json")
REQUIRED_KEYS = (
    "schema_version",
    "contract",
    "canonical_history",
    "migration_name_pattern",
    "manifest",
    "pinned_hashes",
    "recorded_artifacts",
    "live_ledger_claims",
    "destructive_statement_kinds",
    "destructive_statements",
)
BINDING_TARGETS = {"repo_count", "repo_max_version"}


def load_contract(path: Path) -> dict[str, Any]:
    """Load a migration-ledger contract JSON object."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("contract root must be an object")
    return data


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: Any) -> str:
    return value.as_posix() if isinstance(value, Path) else str(value)


def _within_root(root: Path, relative: str) -> Path | None:
    """Return the absolute path for a repo-relative path, or None if it escapes."""

    if not relative or relative.startswith("/") or ":" in relative.split("/")[0]:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _canonical_files(root: Path, contract: dict[str, Any]) -> list[str]:
    directory = root / str(contract.get("canonical_history", ""))
    if not directory.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix() for path in directory.glob("*.sql") if path.is_file()
    )


def _pointer(document: Any, pointer: str) -> Any:
    """Resolve a minimal JSON pointer (RFC 6901 subset) or raise KeyError/IndexError."""

    if pointer in ("", "/"):
        return document
    node = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise KeyError(f"{pointer}: cannot descend into {type(node).__name__}")
    return node


def _strip_sql_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", text)


def _destructive_counts(root: Path, contract: dict[str, Any], files: list[str]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    patterns = contract.get("destructive_statement_kinds", {})
    for relative in files:
        path = root / relative
        text = _strip_sql_comments(path.read_text(encoding="utf-8", errors="replace"))
        for kind, pattern in patterns.items():
            if not isinstance(pattern, str):
                continue
            found = len(re.findall(pattern, text, re.IGNORECASE))
            if found:
                counts[(relative, str(kind))] = found
    return counts


def _check_structure(root: Path, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in contract:
            errors.append(f"C7 contract is missing required key {key!r}")
    if errors:
        return errors

    if contract.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        errors.append(f"C7 schema_version must be {EXPECTED_SCHEMA_VERSION}")
    if contract.get("contract") != EXPECTED_CONTRACT:
        errors.append(f"C7 contract must be {EXPECTED_CONTRACT!r}")

    if _within_root(root, str(contract.get("canonical_history"))) is None:
        errors.append("C7 canonical_history must be a repo-relative directory")

    try:
        name_pattern = re.compile(str(contract.get("migration_name_pattern")))
        if "version" not in name_pattern.groupindex:
            errors.append("C7 migration_name_pattern needs a named 'version' group")
    except re.error as exc:
        errors.append(f"C7 migration_name_pattern does not compile: {exc}")

    manifest = contract.get("manifest")
    if not isinstance(manifest, dict) or _within_root(root, str(manifest.get("path"))) is None or not manifest.get("key"):
        errors.append("C7 manifest needs a repo-relative path and a key")

    for index, pin in enumerate(contract.get("pinned_hashes", [])):
        if not isinstance(pin, dict):
            errors.append(f"C7 pinned_hashes[{index}] must be an object")
            continue
        if _within_root(root, _relative(pin.get("file", ""))) is None:
            errors.append(f"C7 pinned_hashes[{index}].file must be repo-relative")
        if not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("sha256", ""))):
            errors.append(f"C7 pinned_hashes[{index}].sha256 must be a lowercase sha256")

    for index, artifact in enumerate(contract.get("recorded_artifacts", [])):
        if not isinstance(artifact, dict):
            errors.append(f"C7 recorded_artifacts[{index}] must be an object")
            continue
        if _within_root(root, _relative(artifact.get("evidence", ""))) is None:
            errors.append(f"C7 recorded_artifacts[{index}].evidence must be repo-relative")
        for key in ("file_pointer", "sha256_pointer"):
            if not str(artifact.get(key, "")).startswith("/"):
                errors.append(f"C7 recorded_artifacts[{index}].{key} must be a JSON pointer")

    claims = contract.get("live_ledger_claims", [])
    if not claims:
        errors.append("C7 live_ledger_claims must register at least one current claim")
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"C7 live_ledger_claims[{index}] must be an object")
            continue
        if _within_root(root, _relative(claim.get("document", ""))) is None:
            errors.append(f"C7 live_ledger_claims[{index}].document must be repo-relative")
        required = claim.get("occurrences_required")
        if not isinstance(required, int) or required < 1:
            errors.append(f"C7 live_ledger_claims[{index}].occurrences_required must be a positive integer")
        try:
            compiled = re.compile(str(claim.get("pattern")))
        except re.error as exc:
            errors.append(f"C7 live_ledger_claims[{index}].pattern does not compile: {exc}")
            continue
        if set(compiled.groupindex) != {"production", "repo", "max_version"}:
            errors.append(
                f"C7 live_ledger_claims[{index}].pattern must name groups production, repo, max_version"
            )
        bindings = claim.get("bindings")
        if not isinstance(bindings, dict) or set(bindings) != {"production", "repo", "max_version"}:
            errors.append(f"C7 live_ledger_claims[{index}].bindings must cover the three groups")
        elif any(target not in BINDING_TARGETS for target in bindings.values()):
            errors.append(f"C7 live_ledger_claims[{index}].bindings must target {sorted(BINDING_TARGETS)}")

    kinds = contract.get("destructive_statement_kinds")
    if not isinstance(kinds, dict) or not kinds:
        errors.append("C7 destructive_statement_kinds must declare at least one keyword group")
    else:
        for kind, pattern in kinds.items():
            try:
                re.compile(str(pattern))
            except re.error as exc:
                errors.append(f"C7 destructive_statement_kinds[{kind}] does not compile: {exc}")

    for index, entry in enumerate(contract.get("destructive_statements", [])):
        if not isinstance(entry, dict):
            errors.append(f"C7 destructive_statements[{index}] must be an object")
            continue
        if _within_root(root, _relative(entry.get("file", ""))) is None:
            errors.append(f"C7 destructive_statements[{index}].file must be repo-relative")
        if isinstance(kinds, dict) and entry.get("kind") not in kinds:
            errors.append(f"C7 destructive_statements[{index}].kind is not declared in destructive_statement_kinds")
        if not isinstance(entry.get("count"), int) or entry.get("count") < 1:
            errors.append(f"C7 destructive_statements[{index}].count must be a positive integer")
    return errors


def _check_names(root: Path, contract: dict[str, Any], files: list[str]) -> list[str]:
    errors: list[str] = []
    try:
        pattern = re.compile(str(contract["migration_name_pattern"]))
    except re.error:
        return errors
    versions: list[str] = []
    by_version: dict[str, list[str]] = {}
    for relative in files:
        match = pattern.match(Path(relative).name)
        if match is None:
            errors.append(f"C1 {relative}: filename does not match the migration name pattern")
            continue
        version = match.group("version")
        versions.append(version)
        by_version.setdefault(version, []).append(relative)
    for version, members in sorted(by_version.items()):
        if len(members) > 1:
            errors.append(f"C1 migration version {version} is duplicated by {sorted(members)}")
    if versions != sorted(versions):
        inversion = next(
            (versions[index] for index in range(1, len(versions)) if versions[index] < versions[index - 1]),
            "",
        )
        errors.append(f"C1 canonical history is not in ascending version order: first inversion at {inversion}")
    return errors


def _check_manifest(root: Path, contract: dict[str, Any], files: list[str]) -> list[str]:
    manifest = contract["manifest"]
    path = root / str(manifest["path"])
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"C2 cannot read the ownership manifest {manifest['path']}: {exc}"]
    declared_history = document.get("canonical_forward_history")
    errors: list[str] = []
    if declared_history != contract["canonical_history"]:
        errors.append(
            f"C2 {manifest['path']} declares canonical_forward_history={declared_history!r}, "
            f"contract says {contract['canonical_history']!r}"
        )
    names = document.get(manifest["key"])
    if not isinstance(names, list):
        return [f"C2 {manifest['path']} key {manifest['key']!r} must be a list"]
    declared = [f"{contract['canonical_history']}/{name}" for name in names]
    for relative in files:
        if relative not in declared:
            errors.append(f"C2 {relative} is on disk but missing from {manifest['path']}")
    for relative in declared:
        if relative not in files:
            errors.append(f"C2 {manifest['path']} lists {relative}, which is not on disk")
    if declared != files:
        errors.append(
            f"C2 {manifest['path']} is not in the append-only canonical order "
            f"({len(declared)} declared, {len(files)} on disk)"
        )
    return errors


def _check_pins(root: Path, contract: dict[str, Any], files: list[str]) -> list[str]:
    errors: list[str] = []
    pin_set = [str(pin.get("file", "")) if isinstance(pin, dict) else "" for pin in contract["pinned_hashes"]]
    seen: set[str] = set()
    for relative in pin_set:
        if relative in seen:
            errors.append(f"C3 {relative} is pinned more than once")
        seen.add(relative)
    for relative in files:
        if relative not in seen:
            errors.append(f"C3 {relative} has no pinned sha256 (add its hash with the migration)")
    for relative in pin_set:
        if relative and relative not in files:
            errors.append(f"C3 {relative} is pinned but not on disk")
    for pin in contract["pinned_hashes"]:
        if not isinstance(pin, dict):
            continue
        relative = str(pin.get("file", ""))
        if relative not in files:
            continue
        actual = _sha256(root / relative)
        if actual != pin.get("sha256"):
            errors.append(
                f"C3 {relative}: sha256 drift, pinned {pin.get('sha256')}, on disk {actual}"
            )
    return errors


def _check_recorded_artifacts(root: Path, contract: dict[str, Any], files: list[str]) -> list[str]:
    errors: list[str] = []
    pins = {
        str(pin.get("file")): pin.get("sha256")
        for pin in contract["pinned_hashes"]
        if isinstance(pin, dict)
    }
    for artifact in contract["recorded_artifacts"]:
        artifact_id = artifact.get("id", "<unnamed>")
        evidence_path = root / str(artifact["evidence"])
        try:
            document = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"C4 {artifact_id}: cannot read {artifact['evidence']}: {exc}")
            continue
        try:
            recorded_file = _pointer(document, str(artifact["file_pointer"]))
            recorded_sha = _pointer(document, str(artifact["sha256_pointer"]))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            errors.append(f"C4 {artifact_id}: cannot resolve recorded coordinates ({exc})")
            continue
        relative = str(recorded_file)
        if relative not in files:
            errors.append(f"C4 {artifact_id}: recorded migration {relative} is not in the canonical history")
            continue
        actual = _sha256(root / relative)
        if actual != recorded_sha:
            errors.append(
                f"C4 {artifact_id}: {relative} no longer matches the recorded sha256 "
                f"(recorded {recorded_sha}, on disk {actual})"
            )
        if pins.get(relative) != recorded_sha:
            errors.append(
                f"C4 {artifact_id}: pinned sha256 for {relative} disagrees with the recorded value "
                f"({pins.get(relative)} vs {recorded_sha})"
            )
    return errors


def _check_live_claims(root: Path, contract: dict[str, Any], files: list[str]) -> list[str]:
    errors: list[str] = []
    versions = [Path(relative).name[:14] for relative in files]
    actual = {
        "repo_count": str(len(files)),
        "repo_max_version": max(versions) if versions else "",
    }
    for claim in contract["live_ledger_claims"]:
        claim_id = claim.get("id", "<unnamed>")
        document = root / str(claim["document"])
        try:
            text = document.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"C5 {claim_id}: cannot read {claim['document']}: {exc}")
            continue
        matches = list(re.finditer(str(claim["pattern"]), text))
        required = claim.get("occurrences_required", 1)
        if len(matches) != required:
            errors.append(
                f"C5 {claim_id}: {claim['document']} contains {len(matches)} claim(s), expected {required}"
            )
            continue
        group = matches[0].groupdict()
        for name, target in claim["bindings"].items():
            if group.get(name) != actual[target]:
                errors.append(
                    f"C5 {claim_id}: {name}={group.get(name)!r} but the repository says {actual[target]!r}"
                )
    return errors


def _check_destructive(root: Path, contract: dict[str, Any], files: list[str]) -> list[str]:
    errors: list[str] = []
    actual = _destructive_counts(root, contract, files)
    registered: dict[tuple[str, str], int] = {}
    for entry in contract["destructive_statements"]:
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get("file")), str(entry.get("kind")))
        if key in registered:
            errors.append(f"C6 {key[0]}: {key[1]} is registered more than once")
        registered[key] = int(entry.get("count", 0))
    for (relative, kind), count in sorted(actual.items()):
        expected = registered.get((relative, kind), 0)
        if expected != count:
            errors.append(
                f"C6 {relative}: {kind} appears {count} time(s), registered {expected}"
            )
    for (relative, kind), count in sorted(registered.items()):
        if (relative, kind) not in actual:
            errors.append(
                f"C6 {relative}: {kind} is registered ({count}) but no longer present in the migration"
            )
    return errors


def check_repo(root: Path, contract: dict[str, Any]) -> list[str]:
    """Return offline migration-ledger violations for ``root``; an empty list passes."""

    structure = _check_structure(root, contract)
    if structure:
        return structure
    files = _canonical_files(root, contract)
    if not files:
        return [f"C1 {contract['canonical_history']} holds no migration files"]
    errors: list[str] = []
    errors.extend(_check_names(root, contract, files))
    errors.extend(_check_manifest(root, contract, files))
    errors.extend(_check_pins(root, contract, files))
    errors.extend(_check_recorded_artifacts(root, contract, files))
    errors.extend(_check_live_claims(root, contract, files))
    errors.extend(_check_destructive(root, contract, files))
    return errors


CHECK_LABELS = (
    "C1 filename and version integrity",
    "C2 ownership manifest matches the canonical history",
    "C3 pinned sha256 for every applied migration",
    "C4 recorded production-line hashes still match",
    "C5 current zero-gap ledger claims match the repository",
    "C6 destructive statements are registered",
    "C7 contract structure",
)


def _print_pins(root: Path, contract: dict[str, Any]) -> int:
    files = _canonical_files(root, contract)
    block = [{"file": relative, "sha256": _sha256(root / relative)} for relative in files]
    print(json.dumps(block, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline canonical migration-ledger guard")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--print-pins", action="store_true", dest="print_pins")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    contract_path = args.contract or root / DEFAULT_CONTRACT
    try:
        contract = load_contract(contract_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if args.as_json:
            print(json.dumps({"status": "fail", "errors": [f"contract: {exc}"]}, ensure_ascii=False))
        else:
            print(f"FAIL contract: {exc}")
        return 1
    if args.print_pins:
        return _print_pins(root, contract)
    errors = check_repo(root, contract)
    status = "PASS" if not errors else "FAIL"
    if args.as_json:
        print(json.dumps({"status": status.lower(), "errors": errors}, ensure_ascii=False))
    else:
        for label in CHECK_LABELS:
            failed = [error for error in errors if error.startswith(label.split(" ", 1)[0] + " ")]
            print(f"{'FAIL' if failed else 'PASS'} {label}" + (f": {failed[0]}" if failed else ""))
        for error in errors:
            if not any(error.startswith(label.split(" ", 1)[0] + " ") for label in CHECK_LABELS):
                print(f"FAIL {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
