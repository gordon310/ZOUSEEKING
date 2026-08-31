from pathlib import Path
import os
import subprocess
import sys

from scripts import inspect_schema_metadata


def test_inventory_document_forbids_member_rows_and_secrets():
    text = Path("docs/architecture/staging-schema-inventory.md").read_text()
    assert "不包含客户行数据" in text
    assert "不包含 access token" in text
    assert "migration_baseline_status" in text


def test_inventory_records_the_authorized_staging_metadata_snapshot():
    text = Path("docs/architecture/staging-schema-inventory.md").read_text()

    for marker in (
        "inventory_status=complete",
        "migration_inventory_status=complete",
        "live_write_status=not_attempted",
        "| public tables | 22 |",
        "| columns | 263 |",
        "| constraints | 97 |",
        "| indexes | 72 |",
        "| policies | 20 |",
        "| trigger events | 18 |",
        "| enum labels | 5 |",
        "| selected role table grants | 315 |",
        "| `anon` | 77 |",
        "| `authenticated` | 84 |",
        "| `service_role` | 154 |",
        "20260825000400",
        "20260827000500",
        "20260828000100",
    ):
        assert marker in text


def test_inventory_requires_an_explicit_database_url_environment_variable():
    result = subprocess.run(
        [sys.executable, "scripts/inspect_schema_metadata.py"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--database-url-env" in result.stderr


def test_inventory_records_blocked_status_without_staging_url(tmp_path):
    output = tmp_path / "inventory.md"
    environment = os.environ.copy()
    environment.pop("MISSING_STAGING_DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_schema_metadata.py",
            "--database-url-env",
            "MISSING_STAGING_DATABASE_URL",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert "inventory_status=blocked" in output.read_text()


def test_migration_history_is_blocked_without_project_ref(monkeypatch):
    monkeypatch.delenv("SUPABASE_STAGING_REF", raising=False)

    status, reason, migration_ids = inspect_schema_metadata.collect_migration_ids()

    assert status == "blocked"
    assert reason == "SUPABASE_STAGING_REF is not set"
    assert migration_ids == []


def test_migration_history_is_blocked_without_supabase_cli(monkeypatch):
    monkeypatch.setenv("SUPABASE_STAGING_REF", "staging-project")
    monkeypatch.setattr(inspect_schema_metadata.shutil, "which", lambda _: None)

    status, reason, migration_ids = inspect_schema_metadata.collect_migration_ids()

    assert status == "blocked"
    assert reason == "supabase CLI is unavailable"
    assert migration_ids == []


def test_metadata_queries_do_not_read_application_rows():
    query_text = "\n".join(inspect_schema_metadata.METADATA_QUERIES.values()).lower()

    assert "information_schema.columns" in query_text
    assert "information_schema.table_constraints" in query_text
    assert "pg_indexes" in query_text
    assert "pg_policies" in query_text
    for forbidden in ("insert ", "update ", "delete ", "copy ", "public.", "auth.users"):
        assert forbidden not in query_text
