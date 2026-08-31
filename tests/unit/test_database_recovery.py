from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.database_recovery import (
    RecoveryError,
    inspect_custom_archive,
    local_pg_environment,
    run_local_restore_drill,
    validate_evidence_record,
    validate_target_database_name,
)


RESPONSIBLE = {
    "database_owner": "local_database_owner",
    "backup_operator": "local_backup_operator",
    "recovery_lead": "local_recovery_lead",
    "release_owner": "local_release_owner",
    "forward_fix_owner": "local_forward_fix_owner",
    "incident_commander": "local_incident_commander",
}


def completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def toc_output() -> str:
    return """;
; Archive created at 2026-08-30 05:35:00 JST
;     dbname: postgres
;     TOC Entries: 3
;     Format: CUSTOM
;     Dumped from database version: 15.8
;     Dumped by pg_dump version: 18.6
;
1; 1259 100 TABLE public properties postgres
2; 0 100 TABLE DATA public properties postgres
3; 0 0 ACL public TABLE properties postgres
"""


def write_archive(path: Path) -> str:
    path.write_bytes(b"PGDMP-local-synthetic-fixture")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_local_pg_environment_accepts_only_loopback_postgres_database() -> None:
    environment = local_pg_environment(
        "postgresql://postgres:test-password@127.0.0.1:54322/postgres"
    )

    assert environment == {
        "PGHOST": "127.0.0.1",
        "PGPORT": "54322",
        "PGUSER": "postgres",
        "PGPASSWORD": "test-password",
        "PGDATABASE": "postgres",
    }

    with pytest.raises(RecoveryError, match="loopback"):
        local_pg_environment(
            "postgresql://postgres:test-password@db.production.example:5432/postgres"
        )

    with pytest.raises(RecoveryError, match="maintenance database.*postgres"):
        local_pg_environment(
            "postgresql://postgres:test-password@127.0.0.1:54322/customer_database"
        )


def test_target_database_name_must_be_disposable_and_specific() -> None:
    assert validate_target_database_name("jpp_restore_20260830_a1") == "jpp_restore_20260830_a1"

    for unsafe_name in ("postgres", "production", "jpp_restore", "jpp_restore_PROD"):
        with pytest.raises(RecoveryError, match="disposable target"):
            validate_target_database_name(unsafe_name)


def test_inspect_custom_archive_verifies_checksum_and_reports_metadata_only(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "local.dump"
    expected_sha256 = write_archive(archive)

    def runner(args, **_kwargs):
        assert args == ["pg_restore", "--list", str(archive)]
        return completed(args, stdout=toc_output())

    evidence = inspect_custom_archive(archive, expected_sha256, runner=runner)

    assert evidence == {
        "artifact_name": "local.dump",
        "artifact_size_bytes": 29,
        "sha256": expected_sha256,
        "checksum_verified": True,
        "archive_format": "custom",
        "dumped_from_postgres_version": "15.8",
        "dumped_by_pg_dump_version": "18.6",
        "toc_entry_count": 3,
        "table_data_entry_count": 1,
        "toc_verified": True,
    }


def test_inspect_custom_archive_stops_before_pg_restore_on_checksum_mismatch(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "local.dump"
    write_archive(archive)
    called = False

    def runner(args, **_kwargs):
        nonlocal called
        called = True
        return completed(args, stdout=toc_output())

    with pytest.raises(RecoveryError, match="checksum mismatch"):
        inspect_custom_archive(archive, "0" * 64, runner=runner)

    assert called is False


def test_evidence_record_requires_named_recovery_roles_and_live_approval() -> None:
    record = {
        "record_version": 1,
        "gate_status": "pass",
        "source": {
            "environment": "local",
            "data_scope": "synthetic_or_empty",
            "provider": "local_supabase",
        },
        "backup": {
            "identifier": "local-backup-1",
            "kind": "custom_format_logical",
            "sha256": "a" * 64,
            "checksum_verified": True,
        },
        "restore": {
            "target_kind": "disposable_local_database",
            "result": "pass",
            "cleanup_result": "pass",
            "assertions": [{"name": "schema.sql", "status": "pass"}],
        },
        "responsible": dict(RESPONSIBLE),
        "authorization": {
            "live_write_status": "not_authorized",
            "approved_scope": "local_disposable_only",
            "approval_record": None,
        },
    }

    assert validate_evidence_record(record) == []

    invalid_gate = copy.deepcopy(record)
    invalid_gate["gate_status"] = "unknown"
    assert "gate_status must be pass or blocked" in validate_evidence_record(invalid_gate)

    invalid_assertion = copy.deepcopy(record)
    invalid_assertion["restore"]["assertions"] = [None]
    assert "passing evidence requires every assertion to pass" in validate_evidence_record(
        invalid_assertion
    )

    del record["responsible"]["recovery_lead"]
    assert "responsible.recovery_lead is required" in validate_evidence_record(record)

    record["responsible"] = dict(RESPONSIBLE)
    record["source"]["environment"] = "production"
    errors = validate_evidence_record(record)
    assert "production evidence requires explicit live-write approval" in errors
    assert "production evidence requires an approval record" in errors

    record["source"]["environment"] = "local"
    record["responsible"]["recovery_lead"] = "TBD"
    assert "responsible.recovery_lead must name an assigned owner" in validate_evidence_record(
        record
    )


def test_provider_managed_backup_uses_backup_and_restore_ids_when_no_hash_exists() -> None:
    record = {
        "record_version": 1,
        "gate_status": "pass",
        "source": {
            "environment": "staging",
            "data_scope": "provider_managed_backup",
            "provider": "supabase",
        },
        "backup": {
            "identifier": "provider-backup-20260830",
            "kind": "provider_physical",
            "checksum_mode": "provider_managed_identifier",
            "sha256": None,
            "checksum_verified": False,
        },
        "restore": {
            "target_kind": "isolated_provider_clone",
            "provider_job_identifier": "provider-restore-job-20260830",
            "result": "pass",
            "cleanup_result": "pass",
            "assertions": [{"name": "catalog-and-rls", "status": "pass"}],
        },
        "responsible": {
            **copy.deepcopy(RESPONSIBLE),
            "security_reviewer": "staging_security_reviewer",
            "billing_owner": "staging_billing_owner",
        },
        "authorization": {
            "live_write_status": "approved",
            "approved_scope": "staging_backup_to_isolated_clone",
            "approval_record": "release-record-20260830",
            "billing_approval_record": "billing-record-20260830",
            "maintenance_window": "2026-08-30T14:00:00+09:00/2026-08-30T15:00:00+09:00",
        },
    }

    assert validate_evidence_record(record) == []

    local_claim = copy.deepcopy(record)
    local_claim["source"]["environment"] = "local"
    assert (
        "provider-managed backup evidence must identify staging or production"
        in validate_evidence_record(local_claim)
    )

    wrong_kind = copy.deepcopy(record)
    wrong_kind["backup"]["kind"] = "custom_format_logical"
    assert (
        "provider-managed integrity requires provider_physical or provider_pitr"
        in validate_evidence_record(wrong_kind)
    )

    del record["responsible"]["security_reviewer"]
    del record["authorization"]["billing_approval_record"]
    errors = validate_evidence_record(record)
    assert "responsible.security_reviewer is required for live evidence" in errors
    assert "provider clone evidence requires billing approval" in errors


def test_failed_assertion_stops_later_checks_and_cleans_created_target(tmp_path: Path) -> None:
    archive = tmp_path / "local.dump"
    expected_sha256 = write_archive(archive)
    first = tmp_path / "01_failure.sql"
    second = tmp_path / "02_must_not_run.sql"
    first.write_text("select 1 / 0;", encoding="utf-8")
    second.write_text("create table must_not_run(id int);", encoding="utf-8")
    report_path = tmp_path / "report.json"
    calls: list[list[str]] = []

    def runner(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["pg_restore", "--list"]:
            return completed(args, stdout=toc_output())
        if args[0] == "psql":
            return completed(args, returncode=1, stderr="division by zero")
        return completed(args)

    record = run_local_restore_drill(
        artifact=archive,
        expected_sha256=expected_sha256,
        connection_url="postgresql://postgres:test-password@127.0.0.1:54322/postgres",
        target_database="jpp_restore_unit_failure",
        assertion_files=[first, second],
        backup_identifier="local-unit-backup",
        responsible=RESPONSIBLE,
        report_path=report_path,
        runner=runner,
    )

    assert record["gate_status"] == "blocked"
    assert record["backup"]["checksum_mode"] == "sha256"
    assert record["restore"]["result"] == "fail"
    assert record["restore"]["cleanup_result"] == "pass"
    assert record["restore"]["assertions"] == [
        {"name": "01_failure.sql", "status": "fail", "error_class": "psql_exit_1"},
        {"name": "02_must_not_run.sql", "status": "not_run"},
    ]
    assert not any(str(second) in argument for call in calls for argument in call)
    assert calls[-1][0] == "dropdb"
    assert "test-password" not in json.dumps(record)
    assert "test-password" not in report_path.read_text(encoding="utf-8")


def test_createdb_failure_never_drops_a_target_not_created_by_the_drill(tmp_path: Path) -> None:
    archive = tmp_path / "local.dump"
    expected_sha256 = write_archive(archive)
    report_path = tmp_path / "report.json"
    calls: list[list[str]] = []

    def runner(args, **_kwargs):
        calls.append(args)
        if args[:2] == ["pg_restore", "--list"]:
            return completed(args, stdout=toc_output())
        if args[0] == "createdb":
            return completed(args, returncode=1, stderr="database already exists")
        return completed(args)

    record = run_local_restore_drill(
        artifact=archive,
        expected_sha256=expected_sha256,
        connection_url="postgresql://postgres:test-password@127.0.0.1:54322/postgres",
        target_database="jpp_restore_existing_target",
        assertion_files=[],
        backup_identifier="local-unit-backup",
        responsible=RESPONSIBLE,
        report_path=report_path,
        runner=runner,
    )

    assert record["restore"]["result"] == "fail"
    assert record["restore"]["cleanup_result"] == "not_needed"
    assert all(call[0] != "dropdb" for call in calls)
