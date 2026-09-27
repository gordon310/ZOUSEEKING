"""Collect the first-week observation dashboard through read-only channels only."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "docs" / "operations" / "first-week-observation-dashboard.json"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "grant", "revoke",
    "truncate", "copy", "vacuum", "call", "into",
)
FORBIDDEN_RE = re.compile(r"\b(?:%s)\b" % "|".join(FORBIDDEN_KEYWORDS), re.IGNORECASE)
PII_COLUMN_SUBSTRINGS = (
    "email", "name", "username", "phone", "ip", "token", "password", "cookie",
    "session", "owner_user_id", "user_id",
)


def load_contract(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("domains"), list):
        raise ValueError("contract_has_no_domains")
    return payload


def contract_metrics(contract: dict) -> list[tuple[str, dict]]:
    records = []
    for domain in contract["domains"]:
        domain_id = domain.get("id")
        metrics = domain.get("metrics")
        if not isinstance(domain_id, str) or not isinstance(metrics, list):
            raise ValueError("contract_has_invalid_domain")
        for metric in metrics:
            if not isinstance(metric, dict):
                raise ValueError("contract_has_invalid_metric")
            records.append((domain_id, metric))
    return records


def validate_read_only_sql(sql: str) -> tuple[bool, str | None]:
    stripped = sql.strip()
    if not re.match(r"^select\b", stripped, re.IGNORECASE):
        return False, "sql_must_start_with_select"
    if ";" in stripped.rstrip(";"):
        return False, "sql_multiple_statements"
    match = FORBIDDEN_RE.search(stripped)
    if match:
        return False, "sql_forbidden_keyword_%s" % match.group(0).lower()
    return True, None


def validate_read_only_command(command: str) -> tuple[bool, str | None]:
    match = FORBIDDEN_RE.search(command)
    if match:
        return False, "command_forbidden_keyword_%s" % match.group(0).lower()
    return True, None


def metric_record(metric: dict, domain: str) -> dict:
    source_kind = "query" if isinstance(metric.get("query"), str) else "command"
    action = metric.get(source_kind)
    if not isinstance(action, str):
        raise ValueError("metric_has_no_action")
    return {
        "id": metric.get("id"),
        "domain": domain,
        "source_kind": source_kind,
        "windows": metric.get("windows"),
        "action": action,
        "status": "not_collected",
        "value": None,
        "threshold": metric.get("threshold"),
        "verdict": "manual_review",
        "owner": metric.get("owner"),
    }


def split_select_columns(sql: str) -> list[str]:
    body = sql.strip().rstrip(";")
    start = re.match(r"select\b", body, re.IGNORECASE)
    if not start:
        return []
    depth = 0
    quote = None
    end = len(body)
    index = start.end()
    while index < len(body):
        char = body[index]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and re.match(r"from\b", body[index:], re.IGNORECASE):
            end = index
            break
        index += 1
    select_list = body[start.end():end]
    columns, current, depth = [], [], 0
    for char in select_list:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        columns.append("".join(current).strip())
    names = []
    for position, column in enumerate(columns, 1):
        alias = re.search(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", column, re.IGNORECASE)
        bare = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)$", column)
        names.append(alias.group(1) if alias else (bare.group(1) if bare else "column_%d" % position))
    return names


def parse_query_value(sql: str, stdout: str) -> tuple[dict, list[str], bool, list[dict], int, bool]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return {}, [], False, [], 0, False
    names = split_select_columns(sql)
    truncated = len(names) > 8
    dropped, rows = [], []
    for line in lines[:20]:
        result = {}
        for name, value in list(zip(names, line.split("|")))[:8]:
            if any(marker in name.lower() for marker in PII_COLUMN_SUBSTRINGS):
                if name not in dropped:
                    dropped.append(name)
            else:
                result[name] = value
        rows.append(result)
    return rows[0], dropped, truncated, rows, len(lines), len(lines) > 20


def parse_command_value(stdout: str) -> dict:
    lines = stdout.splitlines()
    return {"stdout_lines": lines[:20], "stdout_lines_total": len(lines)}


def command_verdict(metric_id: str, stdout: str, returncode: int) -> str:
    if metric_id == "readiness_probe":
        return "ok" if returncode == 0 else "breach"
    if metric_id == "worker_liveness":
        services = set(stdout.splitlines())
        return "ok" if {"api", "report-worker", "worker", "nginx"}.issubset(services) else "breach"
    if metric_id == "backup_freshness":
        if "OBSERVABILITY_OK" in stdout:
            return "ok"
        if "OBSERVABILITY_ALERT" in stdout:
            return "breach"
        return "manual_review"
    if metric_id == "container_restarts":
        return "ok" if all(item in stdout for item in ("failed=0", "zombie_running=0", "pending_due=0")) else "breach"
    if metric_id == "publish_gate_violations":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return "breach"
        violations = payload.get("non_synthetic_violations")
        copies = payload.get("copies")
        hashes_match = (
            copies.get("sha256_match") is True
            if isinstance(copies, dict)
            else payload.get("canonical_sha256") == payload.get("web_sha256")
        )
        empty = violations == [] or violations == 0
        return "ok" if empty and hashes_match else "breach"
    return "manual_review"


def command_is_available(args: list[str]) -> bool:
    return bool(args) and ("/" in args[0] or shutil.which(args[0]) is not None)


def add_curl_user_agent(args: list[str], user_agent: str) -> list[str]:
    if args and args[0] == "curl" and "-A" not in args and "--user-agent" not in args:
        return args + ["-A", user_agent]
    return args


def trusted_commands() -> set[str]:
    return {
        metric["command"]
        for _, metric in contract_metrics(load_contract(DEFAULT_CONTRACT))
        if isinstance(metric.get("command"), str)
    }


def output_path_default() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("/tmp/first-week-observation-%s.json" % timestamp)


def under_docs(path: Path) -> bool:
    try:
        path.resolve().relative_to((REPO_ROOT / "docs").resolve())
        return True
    except ValueError:
        return False


def collect(args: argparse.Namespace, contract: dict) -> tuple[dict, int]:
    metrics = []
    contacted = False
    trusted = trusted_commands()
    for domain, metric in contract_metrics(contract):
        record = metric_record(metric, domain)
        action = record["action"]
        if record["source_kind"] == "query":
            valid, reason = validate_read_only_sql(action)
            if not valid:
                record.update(status="failed", reason=reason, error_class="ReadOnlyGuardError")
                metrics.append(record)
                continue
            command = [args.psql, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-c", "BEGIN READ ONLY; %s; COMMIT;" % action.rstrip(";")]
            environment = dict(os.environ)
            environment["PGOPTIONS"] = "-c default_transaction_read_only=on"
            environment["PGDATABASE"] = args.database_url
            try:
                contacted = True
                result = subprocess.run(command, env=environment, text=True, capture_output=True, timeout=args.command_timeout, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                record.update(status="failed", reason="query_execution_failed", error_class=type(exc).__name__)
            else:
                if result.returncode:
                    record.update(status="failed", reason="query_process_nonzero", error_class="ProcessExitError")
                else:
                    value, dropped, truncated, rows, rows_total, rows_truncated = parse_query_value(action, result.stdout)
                    record.update(status="measured", value=value, rows=rows, rows_total=rows_total)
                    if dropped:
                        record["pii_column_dropped"] = dropped
                    if truncated:
                        record["value_truncated"] = True
                    if rows_truncated:
                        record["rows_truncated"] = True
            metrics.append(record)
            continue
        valid, reason = validate_read_only_command(action)
        if not valid:
            record.update(status="failed", reason=reason, error_class="ReadOnlyGuardError")
            metrics.append(record)
            continue
        if action not in trusted:
            record.update(status="failed", reason="command_not_in_contract", error_class="CommandWhitelistError")
            metrics.append(record)
            continue
        command = add_curl_user_agent(shlex.split(action), args.curl_user_agent)
        if not command_is_available(command):
            record.update(status="not_collected", reason="command_unavailable")
            metrics.append(record)
            continue
        try:
            contacted = True
            result = subprocess.run(command, text=True, capture_output=True, timeout=args.command_timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(status="failed", reason="command_execution_failed", error_class=type(exc).__name__)
        else:
            record["value"] = parse_command_value(result.stdout)
            if result.returncode:
                record.update(status="failed", reason="command_process_nonzero", error_class="ProcessExitError", verdict=command_verdict(record["id"], result.stdout, result.returncode))
            else:
                record.update(status="measured", verdict=command_verdict(record["id"], result.stdout, result.returncode))
        metrics.append(record)
    totals = {status: sum(record["status"] == status for record in metrics) for status in ("measured", "not_collected", "failed")}
    report = {
        "schema_version": 1,
        "artifact": "first-week-observation-collection",
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(args.contract),
        "read_only": True,
        "production_contacted": contacted,
        "totals": totals,
        "metrics": metrics,
    }
    exit_code = 1 if totals["failed"] or any(record["verdict"] == "breach" for record in metrics) else 0
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="parse and print the collection plan without execution")
    parser.add_argument("--execute", action="store_true", help="execute approved read-only collection")
    parser.add_argument("--allow-read-only", action="store_true", help="second opt-in required with --execute")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="PostgreSQL URL for read-only psql queries")
    parser.add_argument("--psql", default="psql", help="psql binary")
    parser.add_argument("--command-timeout", type=float, default=30.0, help="per-command timeout in seconds")
    parser.add_argument("--curl-user-agent", default=DEFAULT_UA, help="user agent appended only to curl commands missing one")
    parser.add_argument("--output", type=Path, default=None, help="report path for --execute")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.plan and args.execute:
        parser.error("--plan and --execute are mutually exclusive")
    if not args.execute:
        args.plan = True
    if args.output is not None and under_docs(args.output):
        parser.error("--output under repository docs/ is forbidden")
    if args.execute and not args.allow_read_only:
        parser.error("--execute requires --allow-read-only")
    if args.execute and not args.database_url:
        parser.error("--execute requires --database-url or DATABASE_URL")
    try:
        contract = load_contract(args.contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error("contract cannot be parsed: %s" % type(exc).__name__)
    if args.plan:
        for domain, metric in contract_metrics(contract):
            record = metric_record(metric, domain)
            print(json.dumps({"id": record["id"], "type": record["source_kind"], "windows": record["windows"], "action": record["action"]}, ensure_ascii=False))
        return 0
    args.output = args.output or output_path_default()
    report, exit_code = collect(args, contract)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
