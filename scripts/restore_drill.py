"""Run a logical export and catalog-only restore comparison against local PostgreSQL.

The source connection is used only by ``pg_dump`` and read-only catalog/count
queries.  The sole write target is a newly-created, disposable ``jpp_restore_``
database on the same loopback server, which is removed in ``finally``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse


TABLES = (
    "mlit_transactions",
    "rent_reference_stats",
    "queries",
    "property_reports",
    "usage_events",
    "usage_quotas",
    "report_generation_outbox",
)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TARGET_RE = re.compile(r"^jpp_restore_[a-z0-9_]{3,63}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class DrillError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_backup_manifest(path: Path, archive: Path | None = None) -> tuple[Path, dict[str, int], tuple[str, ...]]:
    """Load a backup manifest and verify the referenced custom archive hash."""

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrillError(f"backup manifest cannot be read: {exc}") from exc
    artifact = manifest.get("artifact") if isinstance(manifest, dict) else None
    counts = manifest.get("table_row_counts") if isinstance(manifest, dict) else None
    migrations = manifest.get("migration_versions") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("manifest_version") != 1 or manifest.get("format") != "postgres_custom":
        raise DrillError("backup manifest has an unsupported format or version")
    if not isinstance(artifact, dict) or not isinstance(artifact.get("filename"), str) or not isinstance(artifact.get("sha256"), str):
        raise DrillError("backup manifest is missing artifact filename or SHA-256")
    if archive is None:
        archive = path.parent / artifact["filename"]
    if not archive.is_file() or archive.name != artifact["filename"]:
        raise DrillError("backup archive is missing or does not match manifest filename")
    if file_sha256(archive) != artifact["sha256"]:
        raise DrillError("backup archive SHA-256 does not match manifest")
    if not isinstance(counts, dict) or set(counts) != set(TABLES) or any(not isinstance(value, int) or value < 0 for value in counts.values()):
        raise DrillError("backup manifest does not contain valid required table row counts")
    if not isinstance(migrations, list) or not migrations or any(not isinstance(value, str) or not value for value in migrations):
        raise DrillError("backup manifest does not contain migration versions")
    return archive, counts, tuple(migrations)


def pg_environment(url: str, *, database: str | None = None) -> dict[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in LOCAL_HOSTS:
        raise DrillError("restore drill accepts only a loopback PostgreSQL URL")
    source_db = parsed.path.lstrip("/")
    if not source_db or not parsed.username:
        raise DrillError("database URL must include database name and user")
    env = {"PGHOST": parsed.hostname, "PGPORT": str(parsed.port or 5432), "PGUSER": unquote(parsed.username), "PGDATABASE": database or source_db}
    if parsed.password is not None:
        env["PGPASSWORD"] = unquote(parsed.password)
    return env


def run(args: list[str], env: dict[str, str], *, label: str) -> str:
    result = subprocess.run(args, env={**os.environ, **env}, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise DrillError(f"{label} failed (exit {result.returncode}): {detail}")
    return result.stdout


def query(env: dict[str, str], sql: str) -> list[str]:
    # psql is forced into a read-only transaction even for the source catalog checks.
    output = run(["psql", "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-c", f"BEGIN READ ONLY; {sql}; COMMIT;"], {**env, "PGOPTIONS": "-c default_transaction_read_only=on"}, label="read-only assertion")
    return [line for line in output.splitlines() if line]


def inventory(env: dict[str, str]) -> dict[str, tuple[str, ...]]:
    data: dict[str, tuple[str, ...]] = {}
    for table in TABLES:
        data[f"count:{table}"] = tuple(query(env, f"select count(*) from public.{table}"))
        data[f"constraints:{table}"] = tuple(query(env, "select conname from pg_constraint c join pg_class r on r.oid=c.conrelid join pg_namespace n on n.oid=r.relnamespace where n.nspname='public' and r.relname='{}' order by conname".format(table)))
        data[f"policies:{table}"] = tuple(query(env, "select policyname from pg_policies where schemaname='public' and tablename='{}' order by policyname".format(table)))
    data["migrations"] = tuple(query(env, "select version::text from supabase_migrations.schema_migrations order by version"))
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a local source read-only, restore it to a disposable target, compare catalog/counts, then clean up.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="loopback source URL; source is read-only")
    parser.add_argument("--target-database", help="optional disposable jpp_restore_* database name")
    parser.add_argument("--backup-manifest", type=Path, help="JSON manifest from backup_database.py; restores its checksum-verified archive")
    parser.add_argument("--backup-archive", type=Path, help="optional archive path when it is not next to the manifest")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    source_env = pg_environment(args.database_url)
    target = args.target_database or f"jpp_restore_drill_{secrets.token_hex(6)}"
    if not TARGET_RE.fullmatch(target) or target == source_env["PGDATABASE"]:
        raise DrillError("target must be a distinct disposable jpp_restore_* database")
    maintenance_env = pg_environment(args.database_url, database="postgres")
    created = False
    try:
        print("SOURCE_READ_ONLY export and inventory started")
        source = inventory(source_env)
        manifest_counts: dict[str, int] | None = None
        manifest_migrations: tuple[str, ...] | None = None
        with tempfile.TemporaryDirectory(prefix="jpp-restore-drill-") as temp:
            if args.backup_manifest:
                archive, manifest_counts, manifest_migrations = load_backup_manifest(args.backup_manifest, args.backup_archive)
                print(f"BACKUP_MANIFEST_OK archive={archive} sha256_verified=true")
            else:
                archive = Path(temp) / "source.dump"
                # The drill intentionally scopes the artifact to application data plus
                # the migration ledger.  Provider-managed auth/realtime internals have
                # their own recovery procedures and cannot be restored by an ordinary
                # PostgreSQL role on the local Supabase stack.
                run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--schema=public", "--schema=supabase_migrations", "--file", str(archive)], source_env, label="logical export")
                print(f"EXPORT_OK artifact_bytes={archive.stat().st_size}")
            run(["createdb", "--template=template0", target], maintenance_env, label="create disposable target")
            created = True
            print(f"RESTORE_TARGET_CREATED database={target}")
            # template0 supplies public.  Keep that schema and preload the
            # application extensions; the dump TOC is filtered to avoid trying
            # to create public a second time.
            target_env = pg_environment(args.database_url, database=target)
            run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-c", "create schema if not exists auth; create table if not exists auth.users (id uuid primary key); create or replace function auth.uid() returns uuid language sql stable as 'select null::uuid'; create extension if not exists btree_gist; create extension if not exists pgcrypto; create extension if not exists pg_trgm; create extension if not exists \"uuid-ossp\""], target_env, label="prepare disposable target")
            # Only primary keys are copied from auth, solely to satisfy public
            # foreign keys in the isolated target.  No auth profile/token data
            # is exported, and this source query remains read-only.
            auth_ids = query(source_env, "select id::text from auth.users order by id")
            if any(not UUID_RE.fullmatch(value) for value in auth_ids):
                raise DrillError("auth user identifier inventory contained a non-UUID")
            if auth_ids:
                values = ",".join(f"('{value}'::uuid)" for value in auth_ids)
                run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-c", f"insert into auth.users(id) values {values}"], target_env, label="seed disposable auth foreign-key stubs")
            toc = run(["pg_restore", "--list", str(archive)], maintenance_env, label="read archive table of contents")
            restore_list = Path(temp) / "restore.list"
            restore_list.write_text("\n".join(line for line in toc.splitlines() if " SCHEMA - public " not in line) + "\n", encoding="utf-8")
            run(["pg_restore", "--use-list", str(restore_list), "--exit-on-error", "--no-owner", "--no-acl", "--dbname", target, str(archive)], maintenance_env, label="restore")
            print("RESTORE_OK")
            restored = inventory(pg_environment(args.database_url, database=target))
            if manifest_counts is not None and manifest_migrations is not None:
                mismatches = [
                    f"count:{table}"
                    for table in TABLES
                    if restored.get(f"count:{table}") != (str(manifest_counts[table]),)
                ]
                if restored["migrations"] != manifest_migrations:
                    mismatches.append("migrations")
            else:
                mismatches = [key for key in source if source[key] != restored.get(key)]
            if mismatches:
                raise DrillError("restore assertion mismatch: " + ", ".join(mismatches))
            migration_count = len(manifest_migrations) if manifest_migrations is not None else len(source["migrations"])
            print(f"ASSERTIONS_OK tables={len(TABLES)} migration_versions={migration_count}")
        return 0
    except DrillError as exc:
        print(f"RESTORE_DRILL_FAILED {exc}", file=sys.stderr)
        return 1
    finally:
        if created:
            try:
                run(["dropdb", "--if-exists", target], maintenance_env, label="cleanup disposable target")
                print(f"CLEANUP_OK database={target}")
            except DrillError as exc:
                print(f"CLEANUP_FAILED {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
