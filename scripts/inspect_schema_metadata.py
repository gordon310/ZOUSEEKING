#!/usr/bin/env python3
"""Create a data-free staging PostgreSQL schema inventory."""

import argparse
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple


METADATA_QUERIES = {
    "columns": """
        select table_schema, table_name, column_name, data_type, is_nullable
        from information_schema.columns
        where table_schema in ('public', 'auth')
        order by 1, 2, ordinal_position
    """,
    "constraints": """
        select table_schema, table_name, constraint_name, constraint_type
        from information_schema.table_constraints
        where table_schema in ('public', 'auth')
        order by 1, 2, 3
    """,
    "indexes": """
        select schemaname, tablename, indexname
        from pg_indexes
        where schemaname in ('public', 'auth')
        order by 1, 2, 3
    """,
    "rls": """
        select n.nspname, c.relname, c.relrowsecurity
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname in ('public', 'auth') and c.relkind in ('r', 'p')
        order by 1, 2
    """,
    "policies": """
        select schemaname, tablename, policyname, permissive, roles, cmd
        from pg_policies
        where schemaname = 'public'
        order by 1, 2, 3
    """,
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url-env",
        required=True,
        help="Name of the environment variable containing the staging database URL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown inventory output path.",
    )
    return parser.parse_args()


def run_query(database_url: str, query: str) -> List[List[str]]:
    environment = os.environ.copy()
    environment["PGDATABASE"] = database_url
    result = subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "--csv", "-t", "-c", query],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return list(csv.reader(io.StringIO(result.stdout)))


def collect_migration_ids() -> Tuple[str, Optional[str], List[List[str]]]:
    project_ref = os.environ.get("SUPABASE_STAGING_REF")
    if not project_ref:
        return "blocked", "SUPABASE_STAGING_REF is not set", []
    if shutil.which("supabase") is None:
        return "blocked", "supabase CLI is unavailable", []
    try:
        result = subprocess.run(
            ["supabase", "migration", "list", "--project-ref", project_ref],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return "blocked", "supabase migration list failed", []
    return "complete", None, [[token] for token in result.stdout.split() if token.isdigit()]


def render_inventory(
    status: str,
    reason: Optional[str],
    inventory: Dict[str, List[List[str]]],
    migration_status: str,
    migration_reason: Optional[str],
) -> str:
    lines = [
        "# Staging schema metadata inventory",
        "",
        "- `inventory_status={}`".format(status),
        "- `migration_inventory_status={}`".format(migration_status),
        "- `migration_baseline_status = reconciliation_required`",
        "- 不包含客户行数据。",
        "- 不包含 access token、Storage 对象、邮箱、姓名或数据库 URL。",
        "- 范围仅限表、列、约束、索引、RLS 状态、policy 名称与 migration ID 等元数据。",
        "",
        "可在受控 staging 环境使用以下只读命令复核：",
        "",
        "```bash",
        'supabase migration list --project-ref "$SUPABASE_STAGING_REF"',
        "psql \"$STAGING_DATABASE_URL\" -v ON_ERROR_STOP=1 -P pager=off \\",
        '  -c "select table_schema, table_name, column_name, data_type, is_nullable from information_schema.columns where table_schema in (\'public\',\'auth\') order by 1,2,ordinal_position"',
        "psql \"$STAGING_DATABASE_URL\" -v ON_ERROR_STOP=1 -P pager=off \\",
        '  -c "select schemaname, tablename, policyname, permissive, roles, cmd from pg_policies where schemaname=\'public\' order by 1,2,3"',
        "```",
    ]
    if reason:
        lines.extend(["- `blocked_reason={}`".format(reason), ""])
    else:
        lines.append("")
    if migration_reason:
        lines.extend(["- `migration_blocked_reason={}`".format(migration_reason), ""])

    for name, rows in inventory.items():
        lines.extend(["## {}".format(name), "", "记录数：{}".format(len(rows)), ""])
        if rows:
            lines.extend(["```text", *[" | ".join(row) for row in rows], "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_arguments()
    database_url = os.environ.get(args.database_url_env)
    if not database_url:
        content = render_inventory(
            "blocked",
            "required environment variable {} is not set".format(args.database_url_env),
            {},
            "blocked",
            "schema metadata collection is blocked",
        )
    elif shutil.which("psql") is None:
        content = render_inventory(
            "blocked", "psql is unavailable", {}, "blocked", "schema metadata collection is blocked"
        )
    else:
        try:
            inventory = {
                name: run_query(database_url, query) for name, query in METADATA_QUERIES.items()
            }
        except (subprocess.CalledProcessError, OSError):
            content = render_inventory(
                "blocked", "metadata query failed", {}, "blocked", "schema metadata collection is blocked"
            )
        else:
            migration_status, migration_reason, migration_rows = collect_migration_ids()
            if migration_status == "complete":
                inventory["migration_ids"] = migration_rows
            content = render_inventory(
                "complete", None, inventory, migration_status, migration_reason
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
