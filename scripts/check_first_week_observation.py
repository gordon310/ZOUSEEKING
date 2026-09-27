#!/usr/bin/env python3
"""Validate the read-only and privacy contract for the first-week dashboard."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "docs/operations/first-week-observation-dashboard.json"
DEFAULT_MARKDOWN = ROOT / "docs/operations/first-week-observation-dashboard.md"

REQUIRED_METRIC_FIELDS = (
    "id",
    "metric",
    "source",
    "unit",
    "threshold",
    "healthy_state",
    "degraded_action",
    "owner",
    "windows",
)
WRITE_OR_DDL_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "grant",
    "revoke",
    "truncate",
    "copy",
    "vacuum",
    "call",
    "into",
)
PII_FIELD_NAMES = (
    "email",
    "name",
    "username",
    "phone",
    "ip",
    "token",
    "password",
    "cookie",
    "session",
    "owner_user_id",
    "user_id",
)
PROHIBITED_EXAGGERATIONS = (
    "实时行情",
    "保证准确",
    "确保准确",
    "必然上涨",
    "稳赚",
    "绝对",
)
NEGATION_CONTEXT = re.compile(r"不得|禁止|不能|不许|严禁|never|must not", re.IGNORECASE)
SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\n])")
COMMAND_WRITE_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "grant",
    "revoke",
    "truncate",
)


def _contains_field(text: str, field: str) -> bool:
    """Match SQL-style identifiers, including underscore-delimited components."""

    return re.search(r"(?<![A-Za-z0-9])" + re.escape(field) + r"(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _metric_label(metric: Any) -> str:
    if isinstance(metric, dict) and isinstance(metric.get("id"), str) and metric["id"]:
        return metric["id"]
    return "<missing-id>"


def _all_strings(value: Any, location: str = "json") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield location, value
    elif isinstance(value, dict):
        for key, nested in value.items():
            yield from _all_strings(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _all_strings(nested, f"{location}[{index}]")


def _prohibited_exaggerations(text: str) -> Iterable[str]:
    """Yield exaggerations used outside a sentence with an explicit prohibition."""

    for sentence in SENTENCE_BOUNDARY.split(text):
        if NEGATION_CONTEXT.search(sentence):
            continue
        for phrase in PROHIBITED_EXAGGERATIONS:
            if phrase in sentence:
                yield phrase


def _validate_language_structure(markdown: str) -> list[str]:
    """Assert the dashboard's current documented language structure.

    The current artifact is a single Chinese document, not a four-language
    document. Its title and explicit production-evidence disclaimer are the
    stable anchors used until a multilingual artifact is intentionally adopted.
    """

    required_markers = ("# 上线首周观察看板", "production_contacted = false")
    return [
        f"document: missing single-language anchor {marker!r}"
        for marker in required_markers
        if marker not in markdown
    ]


def validate_dashboard(json_path: Path = DEFAULT_JSON, markdown_path: Path = DEFAULT_MARKDOWN) -> list[str]:
    """Return every dashboard-contract violation without contacting services."""

    violations: list[str] = []
    try:
        dashboard = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"dashboard JSON: unable to read {json_path}: {error}"]

    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"dashboard document: unable to read {markdown_path}: {error}"]

    if not isinstance(dashboard, dict):
        return ["dashboard JSON: root must be an object"]

    window_ids = {
        window.get("id")
        for window in dashboard.get("windows", [])
        if isinstance(window, dict) and isinstance(window.get("id"), str)
    }
    if not window_ids:
        violations.append("dashboard JSON: no top-level windows[].id values")

    domains = dashboard.get("domains")
    if not isinstance(domains, list):
        violations.append("dashboard JSON: domains must be a list")
        domains = []

    for domain_index, domain in enumerate(domains):
        if not isinstance(domain, dict):
            violations.append(f"domain[{domain_index}]: must be an object")
            continue
        for field, value in domain.items():
            if field == "metrics":
                continue
            for location, text in _all_strings(value, f"domain[{domain_index}].{field}"):
                for phrase in _prohibited_exaggerations(text):
                    violations.append(f"{location}: prohibited exaggeration '{phrase}'")
        metrics = domain.get("metrics")
        if not isinstance(metrics, list):
            violations.append(f"domain[{domain_index}]: metrics must be a list")
            continue
        for metric in metrics:
            label = _metric_label(metric)
            if not isinstance(metric, dict):
                violations.append(f"metric {label}: must be an object")
                continue
            for field in REQUIRED_METRIC_FIELDS:
                if field not in metric:
                    violations.append(f"metric {label}: missing required field '{field}'")

            if "query" not in metric and "command" not in metric:
                violations.append(f"metric {label}: missing required observation probe 'query' or 'command'")

            query = metric.get("query")
            if not isinstance(query, str):
                if "query" in metric:
                    violations.append(f"metric {label}: query must be a string")
            else:
                if not re.match(r"^\s*select\b", query, re.IGNORECASE):
                    violations.append(f"metric {label}: query must start with select")
                for keyword in WRITE_OR_DDL_KEYWORDS:
                    if re.search(r"\b" + re.escape(keyword) + r"\b", query, re.IGNORECASE):
                        violations.append(f"metric {label}: query contains prohibited SQL keyword '{keyword}'")
                for field in PII_FIELD_NAMES:
                    if _contains_field(query, field):
                        violations.append(f"metric {label}: PII field '{field}' in query")

            command = metric.get("command")
            if not isinstance(command, str):
                if "command" in metric:
                    violations.append(f"metric {label}: command must be a string")
            else:
                for keyword in COMMAND_WRITE_KEYWORDS:
                    if re.search(r"\b" + re.escape(keyword) + r"\b", command, re.IGNORECASE):
                        violations.append(f"metric {label}: command contains prohibited write keyword '{keyword}'")

            source = metric.get("source")
            if isinstance(source, str):
                for field in PII_FIELD_NAMES:
                    if _contains_field(source, field):
                        violations.append(f"metric {label}: PII field '{field}' in source")
            elif "source" in metric:
                violations.append(f"metric {label}: source must be a string")

            metric_windows = metric.get("windows")
            if isinstance(metric_windows, list):
                for window in metric_windows:
                    if window not in window_ids:
                        violations.append(f"metric {label}: unknown window {window!r}")
            elif "windows" in metric:
                violations.append(f"metric {label}: windows must be a list")

            for location, value in _all_strings(metric, "metric"):
                for phrase in _prohibited_exaggerations(value):
                    violations.append(f"metric {label}: prohibited exaggeration '{phrase}' in {location}")

    for field, value in dashboard.items():
        if field == "domains":
            continue
        for location, text in _all_strings(value, f"json.{field}"):
            for phrase in _prohibited_exaggerations(text):
                violations.append(f"{location}: prohibited exaggeration '{phrase}'")
    for phrase in _prohibited_exaggerations(markdown):
        violations.append(f"document: prohibited exaggeration '{phrase}'")
    violations.extend(_validate_language_structure(markdown))
    return violations


def _metric_count(dashboard: dict[str, Any]) -> int:
    return sum(
        len(domain.get("metrics", []))
        for domain in dashboard.get("domains", [])
        if isinstance(domain, dict) and isinstance(domain.get("metrics"), list)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate the tracked dashboard artifacts")
    parser.add_argument("--json-path", type=Path, default=DEFAULT_JSON, help=argparse.SUPPRESS)
    parser.add_argument("--markdown-path", type=Path, default=DEFAULT_MARKDOWN, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")

    violations = validate_dashboard(args.json_path, args.markdown_path)
    if violations:
        for violation in violations:
            print(violation)
        return 1

    dashboard = json.loads(args.json_path.read_text(encoding="utf-8"))
    print(
        "first-week observation: PASS "
        f"({_metric_count(dashboard)} metrics; single-language Chinese title + production-contacted disclaimer; "
        f"{len(WRITE_OR_DDL_KEYWORDS)} SQL keywords, {len(PII_FIELD_NAMES)} PII fields, "
        f"{len(PROHIBITED_EXAGGERATIONS)} exaggeration phrases checked)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
