#!/usr/bin/env python3
"""Create a verified PostgreSQL custom dump using disposable client containers.

The runner intentionally has no PostgreSQL client or object-storage SDK
dependency on the host.  It keeps a local, checksumed artifact unless all S3
compatible object-store settings are supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


TABLES = (
    "mlit_transactions",
    "rent_reference_stats",
    "queries",
    "property_reports",
    "usage_events",
    "usage_quotas",
    "report_generation_outbox",
)
REQUIRED_S3_SETTINGS = (
    "BACKUP_S3_BUCKET",
    "BACKUP_S3_ENDPOINT",
    "BACKUP_S3_REGION",
    "BACKUP_S3_ACCESS_KEY_ID",
    "BACKUP_S3_SECRET_ACCESS_KEY",
)


class BackupError(RuntimeError):
    pass


def local_retention_directory(environment: Mapping[str, str]) -> Path:
    return Path(environment.get("BACKUP_LOCAL_DIR", "/var/backups/zouseeking"))


def object_storage_is_configured(environment: Mapping[str, str]) -> bool:
    return all(environment.get(name, "").strip() for name in REQUIRED_S3_SETTINGS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    archive: Path,
    *,
    created_at: str,
    pg_version: str,
    pg_dump_version: str,
    migration_versions: list[str],
    table_counts: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "created_at": created_at,
        "format": "postgres_custom",
        "artifact": {
            "filename": archive.name,
            "size_bytes": archive.stat().st_size,
            "sha256": sha256(archive),
        },
        "migration_versions": migration_versions,
        "table_row_counts": dict(table_counts),
        "postgres_version": pg_version,
        "pg_dump_version": pg_dump_version,
        "tool_version": "backup_database.py/1",
    }


def _run(command: list[str], *, environment: Mapping[str, str], label: str) -> str:
    result = subprocess.run(command, env={**os.environ, **environment}, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise BackupError(f"{label} failed (exit {result.returncode}): {detail}")
    return result.stdout.strip()


def _pg_container(
    image: str, command: list[str], *, output_dir: Path | None = None
) -> list[str]:
    invocation = ["docker", "run", "--rm", "-e", "DATABASE_URL"]
    if output_dir is not None:
        invocation.extend(["-v", f"{output_dir}:/backup"])
    return [*invocation, image, *command]


def _pg_query(image: str, sql: str, environment: Mapping[str, str]) -> str:
    return _run(
        _pg_container(
            image,
            [
                "sh", "-ceu",
                'psql --dbname="$DATABASE_URL" --no-psqlrc --tuples-only --no-align --command "$1"',
                "backup-query", sql,
            ],
        ),
        environment=environment,
        label="containerized PostgreSQL inventory query",
    )


def _parse_counts(raw: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in raw.splitlines():
        name, separator, value = line.partition("|")
        if not separator or name not in TABLES or not value.isdigit():
            raise BackupError("inventory returned an invalid table row-count record")
        counts[name] = int(value)
    if set(counts) != set(TABLES):
        raise BackupError("inventory did not return every required table row count")
    return counts


def _prune_local(directory: Path, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for path in directory.glob("zouseeking-*"):
        if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
            path.unlink()
            removed += 1
    return removed


def _upload_s3(archive: Path, manifest_path: Path, environment: Mapping[str, str]) -> None:
    prefix = environment.get("BACKUP_S3_PREFIX", "zouseeking/database").strip("/")
    target_prefix = f"s3://{environment['BACKUP_S3_BUCKET']}/{prefix}" if prefix else f"s3://{environment['BACKUP_S3_BUCKET']}"
    aws_environment = {
        **environment,
        "AWS_ACCESS_KEY_ID": environment["BACKUP_S3_ACCESS_KEY_ID"],
        "AWS_SECRET_ACCESS_KEY": environment["BACKUP_S3_SECRET_ACCESS_KEY"],
        "AWS_DEFAULT_REGION": environment["BACKUP_S3_REGION"],
    }
    for path in (archive, manifest_path):
        _run(
            [
                "docker", "run", "--rm",
                "-e", "AWS_ACCESS_KEY_ID", "-e", "AWS_SECRET_ACCESS_KEY", "-e", "AWS_DEFAULT_REGION",
                "-v", f"{path.parent}:/backup:ro",
                "amazon/aws-cli:2.27.1",
                "--endpoint-url", environment["BACKUP_S3_ENDPOINT"],
                "s3", "cp", f"/backup/{path.name}", f"{target_prefix}/{path.name}",
            ],
            environment=aws_environment,
            label=f"S3 upload for {path.name}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a containerized pg_dump with a JSON checksum manifest.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="source PostgreSQL URL (not printed)")
    parser.add_argument("--local-dir", help="local retention directory; default BACKUP_LOCAL_DIR or /var/backups/zouseeking")
    parser.add_argument("--retention-days", type=int, default=int(os.environ.get("BACKUP_RETENTION_DAYS", "14")))
    parser.add_argument("--pg-client-image", default=os.environ.get("BACKUP_PG_CLIENT_IMAGE", "postgres:17"))
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.retention_days < 1:
        parser.error("--retention-days must be at least 1")

    environment = dict(os.environ)
    environment["DATABASE_URL"] = args.database_url
    directory = Path(args.local_dir) if args.local_dir else local_retention_directory(environment)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        pg_version = _pg_query(args.pg_client_image, "select version()", environment)
        major = re.search(r"PostgreSQL (\d+)", pg_version)
        image_major = re.search(r":(\d+)(?:[.-]|$)", args.pg_client_image)
        if not major or not image_major or major.group(1) != image_major.group(1):
            raise BackupError("PostgreSQL server major version does not match BACKUP_PG_CLIENT_IMAGE")
        pg_dump_version = _run(_pg_container(args.pg_client_image, ["pg_dump", "--version"]), environment=environment, label="containerized pg_dump version")
        counts = _parse_counts(_pg_query(args.pg_client_image, " UNION ALL ".join(f"select '{table}' || '|' || count(*)::text from public.{table}" for table in TABLES), environment))
        migrations = [value for value in _pg_query(args.pg_client_image, "select version::text from supabase_migrations.schema_migrations order by version", environment).splitlines() if value]
        if not migrations:
            raise BackupError("migration ledger is empty")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = directory / f"zouseeking-{stamp}.dump"
        _run(_pg_container(args.pg_client_image, ["sh", "-ceu", 'pg_dump --dbname="$DATABASE_URL" --format=custom --no-owner --no-acl --schema=public --schema=supabase_migrations --file=/backup/' + archive.name], output_dir=directory), environment=environment, label="containerized pg_dump")
        manifest = build_manifest(archive, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), pg_version=pg_version, pg_dump_version=pg_dump_version, migration_versions=migrations, table_counts=counts)
        manifest_path = archive.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        removed = _prune_local(directory, args.retention_days)
        print(f"BACKUP_OK archive={archive} manifest={manifest_path} sha256={manifest['artifact']['sha256']} local_pruned={removed}")
        if object_storage_is_configured(environment):
            _upload_s3(archive, manifest_path, environment)
            print("BACKUP_S3_UPLOAD_OK")
        else:
            print(f"BACKUP_LOCAL_RETENTION_MODE directory={directory} reason=object_storage_not_configured")
        return 0
    except BackupError as exc:
        print(f"BACKUP_FAILED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
