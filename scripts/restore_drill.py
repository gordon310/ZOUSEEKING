"""Run a logical export and catalog-only restore comparison against local PostgreSQL.

The source connection is used only by ``pg_dump`` and read-only catalog/count
queries.  The sole write target is a newly-created, disposable ``jpp_restore_``
database on the same loopback server, which is removed in ``finally``.
"""

from __future__ import annotations

import argparse
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
        with tempfile.TemporaryDirectory(prefix="jpp-restore-drill-") as temp:
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
            mismatches = [key for key in source if source[key] != restored.get(key)]
            if mismatches:
                raise DrillError("restore assertion mismatch: " + ", ".join(mismatches))
            print(f"ASSERTIONS_OK tables={len(TABLES)} migration_versions={len(source['migrations'])}")
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
