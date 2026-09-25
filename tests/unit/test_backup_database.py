from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.backup_database as backup_database
from scripts.backup_database import (
    BackupError,
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


def test_remote_retention_days_prefers_its_explicit_value_and_falls_back_to_local() -> None:
    assert backup_database._remote_retention_days(
        {"BACKUP_RETENTION_DAYS": "14", "BACKUP_S3_RETENTION_DAYS": "21"}
    ) == 21
    assert backup_database._remote_retention_days({"BACKUP_RETENTION_DAYS": "14"}) == 14

    with pytest.raises(BackupError, match="BACKUP_S3_RETENTION_DAYS must be an integer"):
        backup_database._remote_retention_days({"BACKUP_S3_RETENTION_DAYS": "not-a-number"})
    with pytest.raises(BackupError, match="BACKUP_S3_RETENTION_DAYS must be at least 1"):
        backup_database._remote_retention_days({"BACKUP_S3_RETENTION_DAYS": "0"})


def test_prune_remote_deletes_only_expired_backup_pair_under_configured_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    prefix = "zouseeking/database"
    old_dump = f"{prefix}/zouseeking-20000101T000000Z.dump"
    old_manifest = f"{prefix}/zouseeking-20000101T000000Z.manifest.json"
    recent_dump = f"{prefix}/zouseeking-29990101T000000Z.dump"
    recent_manifest = f"{prefix}/zouseeking-29990101T000000Z.manifest.json"

    def fake_run(command: list[str], *, environment: dict[str, str], label: str) -> str:
        commands.append(command)
        if label == "S3 remote backup inventory":
            return json.dumps(
                [
                    [old_dump, "2000-01-01T00:00:00+00:00"],
                    [old_manifest, "2000-01-01T00:00:00+00:00"],
                    [recent_dump, "2999-01-01T00:00:00+00:00"],
                    [recent_manifest, "2999-01-01T00:00:00+00:00"],
                    [f"{prefix}/unrelated.txt", "2000-01-01T00:00:00+00:00"],
                    ["other-prefix/zouseeking-20000101T000000Z.dump", "2000-01-01T00:00:00+00:00"],
                ]
            )
        return ""

    monkeypatch.setattr(backup_database, "_run", fake_run)
    environment = {
        "BACKUP_S3_BUCKET": "test-bucket",
        "BACKUP_S3_ENDPOINT": "https://s3.example.invalid",
        "BACKUP_S3_REGION": "auto",
        "BACKUP_S3_ACCESS_KEY_ID": "access",
        "BACKUP_S3_SECRET_ACCESS_KEY": "secret",
        "BACKUP_S3_PREFIX": prefix,
    }

    assert backup_database._prune_remote(environment, retention_days=14) == 2
    deletion_targets = [command[-1] for command in commands if "s3" in command and "rm" in command]
    assert deletion_targets == [f"s3://test-bucket/{old_dump}", f"s3://test-bucket/{old_manifest}"]
    assert all(target.startswith(f"s3://test-bucket/{prefix}/zouseeking-") for target in deletion_targets)


def test_remote_prune_failure_does_not_fail_successful_backup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_pg_query(image: str, sql: str, environment: dict[str, str]) -> str:
        if sql == "select version()":
            return "PostgreSQL 17.6"
        if "schema_migrations" in sql:
            return "20260923000000"
        return "\n".join(f"{table}|1" for table in backup_database.TABLES)

    def fake_run(command: list[str], *, environment: dict[str, str], label: str) -> str:
        if label == "containerized pg_dump":
            archive_name = command[-1].split("--file=/backup/", 1)[1]
            (tmp_path / archive_name).write_bytes(b"PGDMP-test")
            return ""
        return "pg_dump (PostgreSQL) 17.6"

    monkeypatch.setattr(backup_database, "_pg_query", fake_pg_query)
    monkeypatch.setattr(backup_database, "_run", fake_run)
    monkeypatch.setattr(backup_database, "_prune_local", lambda directory, retention_days: 0)
    monkeypatch.setattr(backup_database, "_upload_s3", lambda archive, manifest_path, environment: None)
    monkeypatch.setattr(
        backup_database, "_prune_remote", lambda environment, retention_days: (_ for _ in ()).throw(BackupError("list failed"))
    )
    for name, value in {
        "BACKUP_S3_BUCKET": "test-bucket",
        "BACKUP_S3_ENDPOINT": "https://s3.example.invalid",
        "BACKUP_S3_REGION": "auto",
        "BACKUP_S3_ACCESS_KEY_ID": "access",
        "BACKUP_S3_SECRET_ACCESS_KEY": "secret",
        "BACKUP_S3_RETENTION_DAYS": "14",
    }.items():
        monkeypatch.setenv(name, value)

    assert backup_database.main(["--database-url", "postgresql://test.invalid/db", "--local-dir", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "BACKUP_S3_UPLOAD_OK" in captured.out
    assert "BACKUP_S3_PRUNE_FAILED reason=list failed" in captured.err
