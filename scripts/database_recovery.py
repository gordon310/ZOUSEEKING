"""Verify a custom-format backup against a disposable local PostgreSQL target.

The executable path in this module is deliberately local-only. Provider backup
and live restore steps belong to the operator runbook and require separate
authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import unquote, urlparse


Runner = Callable[..., subprocess.CompletedProcess]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TARGET_PATTERN = re.compile(r"^jpp_restore_[a-z0-9][a-z0-9_]{2,62}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RESPONSIBLE_FIELDS = (
    "database_owner",
    "backup_operator",
    "recovery_lead",
    "release_owner",
    "forward_fix_owner",
    "incident_commander",
)
LIVE_RESPONSIBLE_FIELDS = ("security_reviewer", "billing_owner")
UNASSIGNED_OWNER_VALUES = {"tbd", "todo", "unassigned", "unknown", "none", "null"}


class RecoveryError(RuntimeError):
    """Raised when a recovery safety or artifact check fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def local_pg_environment(connection_url: str) -> dict[str, str]:
    """Convert a loopback maintenance URL to libpq environment variables."""

    parsed = urlparse(connection_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RecoveryError("local recovery requires a PostgreSQL connection URL")
    if parsed.hostname not in LOCAL_HOSTS:
        raise RecoveryError("local recovery accepts loopback database hosts only")

    database = parsed.path.lstrip("/")
    if database != "postgres":
        raise RecoveryError("local recovery maintenance database must be postgres")
    if not parsed.username:
        raise RecoveryError("local recovery connection requires a database user")

    environment = {
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGUSER": unquote(parsed.username),
        "PGDATABASE": "postgres",
    }
    if parsed.password is not None:
        environment["PGPASSWORD"] = unquote(parsed.password)
    return environment


def validate_target_database_name(name: str) -> str:
    """Require a narrow name that cannot be confused with a persistent database."""

    if not TARGET_PATTERN.fullmatch(name):
        raise RecoveryError(
            "disposable target database must match jpp_restore_[a-z0-9][a-z0-9_]{2,62}"
        )
    return name


def _header_value(toc: str, label: str) -> Optional[str]:
    match = re.search(rf"^;\s+{re.escape(label)}:\s*(.+?)\s*$", toc, flags=re.MULTILINE)
    return match.group(1) if match else None


def inspect_custom_archive(
    artifact: Path,
    expected_sha256: str,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Verify checksum and custom archive metadata without extracting table rows."""

    artifact = Path(artifact)
    if not artifact.is_file() or artifact.is_symlink():
        raise RecoveryError("backup artifact must be a regular, non-symlink file")
    if not SHA256_PATTERN.fullmatch(expected_sha256):
        raise RecoveryError("expected SHA-256 must contain 64 lowercase hexadecimal characters")

    actual_sha256 = _sha256(artifact)
    if actual_sha256 != expected_sha256:
        raise RecoveryError("backup artifact checksum mismatch")

    with artifact.open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            raise RecoveryError("backup artifact is not a PostgreSQL custom-format archive")

    result = runner(
        ["pg_restore", "--list", str(artifact)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryError(f"pg_restore list failed with exit code {result.returncode}")

    archive_format = (_header_value(result.stdout, "Format") or "").lower()
    if archive_format != "custom":
        raise RecoveryError("pg_restore did not report a custom-format archive")

    toc_entries = [line for line in result.stdout.splitlines() if re.match(r"^\d+;", line)]
    if not toc_entries:
        raise RecoveryError("pg_restore table of contents is empty")

    return {
        "artifact_name": artifact.name,
        "artifact_size_bytes": artifact.stat().st_size,
        "sha256": actual_sha256,
        "checksum_verified": True,
        "archive_format": archive_format,
        "dumped_from_postgres_version": _header_value(
            result.stdout, "Dumped from database version"
        ),
        "dumped_by_pg_dump_version": _header_value(result.stdout, "Dumped by pg_dump version"),
        "toc_entry_count": len(toc_entries),
        "table_data_entry_count": sum(" TABLE DATA " in line for line in toc_entries),
        "toc_verified": True,
    }


def _mapping_value(record: Mapping[str, Any], *path: str) -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def validate_evidence_record(record: Mapping[str, Any]) -> list[str]:
    """Return release-gate errors without mutating the evidence record."""

    errors: list[str] = []
    if record.get("record_version") != 1:
        errors.append("record_version must be 1")

    responsible = record.get("responsible")
    for field in RESPONSIBLE_FIELDS:
        value = responsible.get(field) if isinstance(responsible, Mapping) else None
        if not isinstance(value, str) or not value.strip():
            errors.append(f"responsible.{field} is required")
        elif value.strip().lower() in UNASSIGNED_OWNER_VALUES:
            errors.append(f"responsible.{field} must name an assigned owner")

    backup_identifier = _mapping_value(record, "backup", "identifier")
    if not isinstance(backup_identifier, str) or not backup_identifier.strip():
        errors.append("backup.identifier is required")

    checksum_mode = _mapping_value(record, "backup", "checksum_mode") or "sha256"
    sha256 = _mapping_value(record, "backup", "sha256")
    if checksum_mode == "sha256":
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            errors.append("backup.sha256 must be a lowercase SHA-256 digest")
        if _mapping_value(record, "backup", "checksum_verified") is not True:
            errors.append("backup.checksum_verified must be true")
    elif checksum_mode == "provider_managed_identifier":
        backup_kind = _mapping_value(record, "backup", "kind")
        if backup_kind not in {"provider_physical", "provider_pitr"}:
            errors.append(
                "provider-managed integrity requires provider_physical or provider_pitr"
            )
        claimed_environment = _mapping_value(record, "source", "environment")
        if claimed_environment not in {"staging", "production"}:
            errors.append(
                "provider-managed backup evidence must identify staging or production"
            )
        if sha256 not in {None, ""}:
            errors.append("provider-managed backup must not claim an unavailable SHA-256")
        if _mapping_value(record, "backup", "checksum_verified") is not False:
            errors.append("provider-managed backup must record checksum_verified=false")
        restore_job = _mapping_value(record, "restore", "provider_job_identifier")
        if not isinstance(restore_job, str) or not restore_job.strip():
            errors.append("provider-managed backup requires a provider restore job identifier")
    else:
        errors.append("backup.checksum_mode must be sha256 or provider_managed_identifier")

    environment = _mapping_value(record, "source", "environment")
    if environment not in {"local", "staging", "production"}:
        errors.append("source.environment must be local, staging, or production")

    gate_status = record.get("gate_status")
    if gate_status not in {"pass", "blocked"}:
        errors.append("gate_status must be pass or blocked")
    assertions = _mapping_value(record, "restore", "assertions")
    if gate_status == "pass":
        if _mapping_value(record, "restore", "result") != "pass":
            errors.append("passing evidence requires restore.result=pass")
        if _mapping_value(record, "restore", "cleanup_result") != "pass":
            errors.append("passing evidence requires restore.cleanup_result=pass")
        if not isinstance(assertions, list) or not assertions:
            errors.append("passing evidence requires at least one assertion")
        elif any(
            not isinstance(item, Mapping) or item.get("status") != "pass"
            for item in assertions
        ):
            errors.append("passing evidence requires every assertion to pass")

    if environment in {"staging", "production"}:
        for field in LIVE_RESPONSIBLE_FIELDS:
            value = responsible.get(field) if isinstance(responsible, Mapping) else None
            if not isinstance(value, str) or not value.strip():
                errors.append(f"responsible.{field} is required for live evidence")
            elif value.strip().lower() in UNASSIGNED_OWNER_VALUES:
                errors.append(f"responsible.{field} must name an assigned owner")
        if _mapping_value(record, "authorization", "live_write_status") != "approved":
            errors.append(f"{environment} evidence requires explicit live-write approval")
        approval_record = _mapping_value(record, "authorization", "approval_record")
        if not isinstance(approval_record, str) or not approval_record.strip():
            errors.append(f"{environment} evidence requires an approval record")
        maintenance_window = _mapping_value(record, "authorization", "maintenance_window")
        if not isinstance(maintenance_window, str) or not maintenance_window.strip():
            errors.append(f"{environment} evidence requires a maintenance window")
        approved_scope = _mapping_value(record, "authorization", "approved_scope")
        if not isinstance(approved_scope, str) or not approved_scope.strip():
            errors.append(f"{environment} evidence requires an approved scope")
        if _mapping_value(record, "restore", "target_kind") == "isolated_provider_clone":
            billing_approval = _mapping_value(
                record, "authorization", "billing_approval_record"
            )
            if not isinstance(billing_approval, str) or not billing_approval.strip():
                errors.append("provider clone evidence requires billing approval")

    return errors


def _command_environment(pg_environment: Mapping[str, str]) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update(pg_environment)
    return environment


def _run(
    runner: Runner,
    args: list[str],
    *,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess:
    return runner(
        args,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
    )


def run_local_restore_drill(
    *,
    artifact: Path,
    expected_sha256: str,
    connection_url: str,
    target_database: str,
    assertion_files: Sequence[Path],
    backup_identifier: str,
    responsible: Mapping[str, str],
    report_path: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Restore one archive, stop on the first failed check, and remove only its target."""

    target_database = validate_target_database_name(target_database)
    pg_environment = local_pg_environment(connection_url)
    process_environment = _command_environment(pg_environment)
    artifact = Path(artifact)
    report_path = Path(report_path)
    assertions = [Path(path) for path in assertion_files]
    for assertion in assertions:
        if not assertion.is_file() or assertion.is_symlink():
            raise RecoveryError(f"assertion file is not a regular file: {assertion.name}")
    if not backup_identifier.strip():
        raise RecoveryError("backup identifier is required")

    archive = inspect_custom_archive(artifact, expected_sha256, runner=runner)
    record: dict[str, Any] = {
        "record_version": 1,
        "gate_status": "blocked",
        "recorded_at": _utc_now(),
        "source": {
            "environment": "local",
            "data_scope": "synthetic_or_empty",
            "provider": "local_supabase",
        },
        "backup": {
            "identifier": backup_identifier,
            "kind": "custom_format_logical",
            "checksum_mode": "sha256",
            **archive,
        },
        "restore": {
            "target_kind": "disposable_local_database",
            "target_database": target_database,
            "result": "fail",
            "cleanup_result": "not_needed",
            "assertions": [],
        },
        "responsible": dict(responsible),
        "authorization": {
            "live_write_status": "not_authorized",
            "approved_scope": "local_disposable_only",
            "approval_record": None,
        },
        "limitations": [
            "This record covers a local synthetic-or-empty archive only.",
            "It is not evidence for staging or production recoverability.",
            "The tool did not connect to a provider-managed environment.",
        ],
    }

    created_by_drill = False
    try:
        create_result = _run(
            runner,
            ["createdb", target_database],
            environment=process_environment,
        )
        if create_result.returncode != 0:
            record["restore"]["error_class"] = f"createdb_exit_{create_result.returncode}"
            return record
        created_by_drill = True

        restore_result = _run(
            runner,
            ["pg_restore", "--exit-on-error", "--dbname", target_database, str(artifact)],
            environment=process_environment,
        )
        if restore_result.returncode != 0:
            record["restore"]["error_class"] = f"pg_restore_exit_{restore_result.returncode}"
            record["restore"]["assertions"] = [
                {"name": assertion.name, "status": "not_run"} for assertion in assertions
            ]
        else:
            assertion_results: list[dict[str, str]] = []
            failed = False
            for assertion in assertions:
                if failed:
                    assertion_results.append({"name": assertion.name, "status": "not_run"})
                    continue
                result = _run(
                    runner,
                    [
                        "psql",
                        "--dbname",
                        target_database,
                        "--set",
                        "ON_ERROR_STOP=1",
                        "--file",
                        str(assertion),
                    ],
                    environment=process_environment,
                )
                if result.returncode == 0:
                    assertion_results.append({"name": assertion.name, "status": "pass"})
                else:
                    assertion_results.append(
                        {
                            "name": assertion.name,
                            "status": "fail",
                            "error_class": f"psql_exit_{result.returncode}",
                        }
                    )
                    failed = True
            record["restore"]["assertions"] = assertion_results
            if assertions and not failed:
                record["restore"]["result"] = "pass"
    finally:
        if created_by_drill:
            cleanup_result = _run(
                runner,
                ["dropdb", "--if-exists", target_database],
                environment=process_environment,
            )
            record["restore"]["cleanup_result"] = (
                "pass" if cleanup_result.returncode == 0 else "fail"
            )
        if (
            record["restore"]["result"] == "pass"
            and record["restore"]["cleanup_result"] == "pass"
        ):
            record["gate_status"] = "pass"
        _write_json(report_path, record)

    return record


def _responsible_from_args(args: argparse.Namespace) -> dict[str, str]:
    return {field: getattr(args, field) for field in RESPONSIBLE_FIELDS}


def _add_responsible_arguments(parser: argparse.ArgumentParser) -> None:
    for field in RESPONSIBLE_FIELDS:
        parser.add_argument(f"--{field.replace('_', '-')}", dest=field, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and restore-test custom-format backups on disposable local targets only."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Verify checksum and archive TOC")
    inspect_parser.add_argument("--artifact", type=Path, required=True)
    inspect_parser.add_argument("--expected-sha256", required=True)
    inspect_parser.add_argument("--output", type=Path)

    drill_parser = subparsers.add_parser(
        "drill", help="Restore to a newly created loopback database and remove it"
    )
    drill_parser.add_argument("--artifact", type=Path, required=True)
    drill_parser.add_argument("--expected-sha256", required=True)
    drill_parser.add_argument("--database-url-env", default="LOCAL_RECOVERY_DATABASE_URL")
    drill_parser.add_argument("--target-database", required=True)
    drill_parser.add_argument("--assertion", action="append", type=Path, default=[])
    drill_parser.add_argument("--backup-identifier", required=True)
    drill_parser.add_argument("--report", type=Path, required=True)
    _add_responsible_arguments(drill_parser)

    validate_parser = subparsers.add_parser(
        "validate-record", help="Validate responsibility and release-gate fields"
    )
    validate_parser.add_argument("record", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            evidence = inspect_custom_archive(args.artifact, args.expected_sha256)
            if args.output:
                _write_json(args.output, evidence)
            else:
                print(json.dumps(evidence, indent=2, sort_keys=True))
            return 0

        if args.command == "validate-record":
            record = json.loads(args.record.read_text(encoding="utf-8"))
            errors = validate_evidence_record(record)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print("recovery evidence record is valid")
            return 0

        connection_url = os.environ.get(args.database_url_env, "")
        if not connection_url:
            raise RecoveryError(f"missing environment variable: {args.database_url_env}")
        record = run_local_restore_drill(
            artifact=args.artifact,
            expected_sha256=args.expected_sha256,
            connection_url=connection_url,
            target_database=args.target_database,
            assertion_files=args.assertion,
            backup_identifier=args.backup_identifier,
            responsible=_responsible_from_args(args),
            report_path=args.report,
        )
        return 0 if record["gate_status"] == "pass" else 1
    except (OSError, RecoveryError, json.JSONDecodeError) as exc:
        print(f"database recovery check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
