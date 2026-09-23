from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.backup_database import (
    build_manifest,
    local_retention_directory,
    object_storage_is_configured,
)


def test_manifest_is_machine_readable_and_carries_restore_assertions(tmp_path: Path) -> None:
    archive = tmp_path / "database.dump"
    archive.write_bytes(b"PGDMP-test-archive")

    manifest = build_manifest(
        archive,
        created_at="2026-09-23T03:10:00+09:00",
        pg_version="PostgreSQL 17.6",
        pg_dump_version="pg_dump (PostgreSQL) 17.6",
        migration_versions=["20260901000000", "20260902000000"],
        table_counts={"queries": 2, "usage_events": 3},
    )

    assert manifest["artifact"]["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest["artifact"]["size_bytes"] == archive.stat().st_size
    assert manifest["migration_versions"] == ["20260901000000", "20260902000000"]
    assert manifest["table_row_counts"] == {"queries": 2, "usage_events": 3}
    assert manifest["format"] == "postgres_custom"


def test_object_storage_requires_complete_environment_and_local_directory_is_configurable(
    tmp_path: Path,
) -> None:
    assert object_storage_is_configured({}) is False
    assert object_storage_is_configured({"BACKUP_S3_BUCKET": "bucket"}) is False
    assert object_storage_is_configured(
        {
            "BACKUP_S3_BUCKET": "bucket",
            "BACKUP_S3_ENDPOINT": "https://s3.example.invalid",
            "BACKUP_S3_REGION": "ap-southeast-1",
            "BACKUP_S3_ACCESS_KEY_ID": "access",
            "BACKUP_S3_SECRET_ACCESS_KEY": "secret",
        }
    ) is True
    assert local_retention_directory({"BACKUP_LOCAL_DIR": str(tmp_path)}) == tmp_path
