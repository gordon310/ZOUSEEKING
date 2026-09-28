"""Check static quota call sites and edges only.

This check proves only that static call sites and call edges exist.  It does
not prove runtime behavior, database atomicity, or replace real quota tests.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Iterable


EXPECTED_SCHEMA = "quota-enforcement-contract/v1"
DEFAULT_CONTRACT = Path("docs/architecture/quota-enforcement-contract.json")


def load_contract(path: Path) -> dict:
    """Load a quota-enforcement contract JSON object."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("contract root must be an object")
    return data


def _function_index(tree: ast.AST) -> dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    index: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}

    def visit(node: ast.AST, parents: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = ".".join([*parents, child.name])
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    index.setdefault(name, []).append(child)
                visit(child, [*parents, child.name])
            else:
                visit(child, parents)

    visit(tree, [])
    return index


def _call_leaf(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _calls(function: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and _call_leaf(node.func) == name
    ]


def _resolve(
    index: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]], name: str
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | None, str | None]:
    matches = index.get(name, [])
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, "not found"
    return None, "not unique"


def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_indexes(
    root: Path, paths: Iterable[str]
) -> tuple[dict[str, ast.Module], dict[str, dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]], list[str]]:
    trees: dict[str, ast.Module] = {}
    indexes: dict[str, dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]] = {}
    errors: list[str] = []
    for relative in sorted(set(paths)):
        path = root / relative
        if not path.is_file():
            errors.append(f"file {relative}: missing")
            continue
        try:
            tree = _parse_module(path)
        except (OSError, SyntaxError) as exc:
            errors.append(f"file {relative}: unreadable ({exc})")
            continue
        trees[relative] = tree
        indexes[relative] = _function_index(tree)
    return trees, indexes, errors


def _contract_errors(contract: dict) -> list[str]:
    errors: list[str] = []
    if contract.get("schema") != EXPECTED_SCHEMA:
        errors.append("C5 contract: schema must be quota-enforcement-contract/v1")
    sites = contract.get("call_sites")
    edges = contract.get("edges")
    if not isinstance(sites, list) or not sites:
        errors.append("C5 contract: call_sites must be a non-empty list")
        sites = []
    if not isinstance(edges, list) or not edges:
        errors.append("C5 contract: edges must be a non-empty list")
        edges = []
    ids: list[Any] = []
    for site in sites:
        if not isinstance(site, dict) or any(key not in site for key in ("id", "file", "function", "metric", "endpoints", "note")):
            errors.append("C5 contract: call site missing required keys")
            continue
        ids.append(site["id"])
    for edge in edges:
        if not isinstance(edge, dict) or any(key not in edge for key in ("id", "kind", "from")):
            errors.append("C5 contract: edge missing required keys")
            continue
        if edge.get("kind") == "direct_call" and "to" not in edge:
            errors.append(f"C5 contract: edge {edge.get('id', '<unknown>')} missing to")
        if edge.get("kind") == "depends_provider" and any(key not in edge for key in ("provider", "injected_call")):
            errors.append(f"C5 contract: edge {edge.get('id', '<unknown>')} missing dependency keys")
        ids.append(edge["id"])
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    errors.extend(f"C5 contract: duplicate id {value}" for value in duplicates)
    return errors


def _function_for(
    file_name: str,
    function_name: str,
    indexes: dict[str, dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]],
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | None, str | None]:
    index = indexes.get(file_name)
    if index is None:
        return None, "file unavailable"
    return _resolve(index, function_name)


def _check_call_sites(contract: dict, indexes: dict[str, dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]]) -> list[str]:
    errors: list[str] = []
    for site in contract.get("call_sites", []):
        if not isinstance(site, dict) or not all(key in site for key in ("id", "file", "function", "metric")):
            continue
        function, reason = _function_for(site["file"], site["function"], indexes)
        if function is None:
            errors.append(f"C1 call site {site['id']}: function {site['function']} {reason}")
            continue
        calls = _calls(function, "consume_current_entitlement")
        if not calls:
            errors.append(f"C1 call site {site['id']}: consume_current_entitlement missing")
            continue
        actual_metrics: list[str] = []
        for call in calls:
            metric = next((keyword.value for keyword in call.keywords if keyword.arg == "metric"), None)
            if isinstance(metric, ast.Constant) and isinstance(metric.value, str):
                actual_metrics.append(metric.value)
            else:
                actual_metrics.append("<non-literal>")
        if site["metric"] not in actual_metrics:
            errors.append(f"C1 call site {site['id']}: expected metric {site['metric']}, actual {', '.join(actual_metrics)}")
    return errors


def _has_depends(function: ast.AST, provider_name: str) -> bool:
    arguments = function.args if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) else None
    if arguments is None:
        return False
    defaults = [*arguments.defaults, *(value for value in arguments.kw_defaults if value is not None)]
    for default in defaults:
        if not isinstance(default, ast.Call) or _call_leaf(default.func) != "Depends" or not default.args:
            continue
        if _call_leaf(default.args[0]) == provider_name:
            return True
    return False


def _check_edges(contract: dict, indexes: dict[str, dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]]) -> list[str]:
    errors: list[str] = []
    for edge in contract.get("edges", []):
        if not isinstance(edge, dict) or not isinstance(edge.get("from"), dict):
            continue
        edge_id = edge.get("id", "<unknown>")
        source, reason = _function_for(edge["from"].get("file", ""), edge["from"].get("function", ""), indexes)
        if source is None:
            errors.append(f"C2 edge {edge_id}: from function {reason}")
            continue
        if edge.get("kind") == "direct_call":
            target = edge.get("to", {})
            if not isinstance(target, dict):
                errors.append(f"C2 edge {edge_id}: invalid to")
                continue
            target_function, target_reason = _function_for(target.get("file", ""), target.get("function", ""), indexes)
            if target_function is None:
                errors.append(f"C2 edge {edge_id}: to function {target_reason}")
            elif not _calls(source, target["function"].split(".")[-1]):
                errors.append(f"C2 edge {edge_id}: direct call missing")
        elif edge.get("kind") == "depends_provider":
            provider = edge.get("provider", {})
            if not isinstance(provider, dict):
                errors.append(f"C2 edge {edge_id}: invalid provider")
                continue
            provider_function, provider_reason = _function_for(provider.get("file", ""), provider.get("function", ""), indexes)
            if provider_function is None:
                errors.append(f"C2 edge {edge_id}: provider function {provider_reason}")
                continue
            if not _has_depends(source, provider["function"].split(".")[-1]):
                errors.append(f"C2 edge {edge_id}: Depends provider missing")
            if not _calls(source, edge.get("injected_call", "")):
                errors.append(f"C2 edge {edge_id}: injected call missing")
            then = edge.get("then")
            if isinstance(then, dict):
                target, target_reason = _function_for(then.get("file", ""), then.get("function", ""), indexes)
                if target is None:
                    errors.append(f"C2 edge {edge_id}: then function {target_reason}")
                elif not _calls(provider_function, then["function"].split(".")[-1]):
                    errors.append(f"C2 edge {edge_id}: then call missing")
        else:
            errors.append(f"C2 edge {edge_id}: unsupported kind {edge.get('kind')}")
    return errors


def _imports_entitlement(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "consume_current_entitlement" for alias in node.names)
        for node in ast.walk(tree)
    )


def _check_module_coverage(root: Path, contract: dict) -> list[str]:
    registered = {site.get("file") for site in contract.get("call_sites", []) if isinstance(site, dict)}
    definition = contract.get("definition_module")
    errors: list[str] = []
    for path in sorted((root / "backend/app").glob("**/*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == definition:
            continue
        try:
            tree = _parse_module(path)
        except (OSError, SyntaxError) as exc:
            errors.append(f"C3 module {relative}: unreadable ({exc})")
            continue
        if _imports_entitlement(tree) and relative not in registered:
            errors.append(f"C3 module {relative}: imports consume_current_entitlement but is unregistered")
    return errors


def _check_metrics(root: Path, contract: dict) -> list[str]:
    definition = contract.get("definition_module")
    if not isinstance(definition, str) or not (root / definition).is_file():
        return ["C4 definition module: missing"]
    try:
        tree = _parse_module(root / definition)
    except (OSError, SyntaxError) as exc:
        return [f"C4 definition module: unreadable ({exc})"]
    meter_map: ast.Dict | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "METER_MAP" for target in node.targets):
            if isinstance(node.value, ast.Dict):
                meter_map = node.value
                break
    if meter_map is None:
        return ["C4 definition module: METER_MAP missing"]
    keys = {key.value for key in meter_map.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    metrics = {site.get("metric") for site in contract.get("call_sites", []) if isinstance(site, dict)}
    return [f"C4 metric {metric}: not in METER_MAP" for metric in sorted(metrics - keys) if isinstance(metric, str)]


def check_repo(root: Path, contract: dict) -> list[str]:
    """Return static-contract violations for ``root``; an empty list passes."""
    errors = _contract_errors(contract)
    files: list[str] = []
    for collection in (contract.get("call_sites", []), contract.get("edges", [])):
        for item in collection:
            if not isinstance(item, dict):
                continue
            for coordinate in (item.get("from"), item.get("to"), item.get("provider"), item.get("then")):
                if isinstance(coordinate, dict) and isinstance(coordinate.get("file"), str):
                    files.append(coordinate["file"])
            if isinstance(item.get("file"), str):
                files.append(item["file"])
    _, indexes, file_errors = _module_indexes(root, files)
    errors.extend(f"C1/C2 {error}" for error in file_errors)
    errors.extend(_check_call_sites(contract, indexes))
    errors.extend(_check_edges(contract, indexes))
    errors.extend(_check_module_coverage(root, contract))
    errors.extend(_check_metrics(root, contract))
    return errors


def _check_labels(contract: dict, errors: list[str]) -> list[str]:
    labels = [f"C1 {site.get('id', '<unknown>')}" for site in contract.get("call_sites", []) if isinstance(site, dict)]
    labels += [f"C2 {edge.get('id', '<unknown>')}" for edge in contract.get("edges", []) if isinstance(edge, dict)]
    labels += ["C3 module coverage", "C4 metric set", "C5 contract structure"]
    return labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline static quota enforcement guard")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    contract_path = args.contract or root / DEFAULT_CONTRACT
    try:
        contract = load_contract(contract_path)
        errors = check_repo(root, contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        contract = {}
        errors = [f"contract: {exc}"]
    status = "PASS" if not errors else "FAIL"
    checks = _check_labels(contract, errors)
    if args.as_json:
        print(json.dumps({"status": status, "errors": errors, "checks": checks}, ensure_ascii=False))
    else:
        failed = set(errors)
        for label in checks:
            matching = [error for error in failed if label.split(" ", 1)[-1] in error]
            print(f"{'FAIL' if matching else 'PASS'} {label}" + (f": {matching[0]}" if matching else ""))
        for error in errors:
            if not any(label.split(" ", 1)[-1] in error for label in checks):
                print(f"FAIL {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
