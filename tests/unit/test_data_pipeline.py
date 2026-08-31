import hashlib
import json

import pytest

from jp_property_publisher.pipeline import load_policy, prepare_records, quality_check


POLICY = {
    "version": "trend-policy-v1",
    "trend": {
        "minimum_periods": 3,
        "minimum_samples_per_period": 5,
        "minimum_total_samples": 15,
        "group_by": [
            "prefecture",
            "ward",
            "market",
            "status",
            "data_class",
            "amount_unit",
            "currency",
        ],
    },
}


def fixture_registry():
    return {
        "sources": [
            {
                "source_id": "fixture",
                "name": "Local synthetic fixture",
                "source_type": "synthetic_fixture",
                "canonical_url": "https://example.invalid/synthetic",
                "permission_status": "not_applicable",
                "rights_evidence": "fixture-only",
                "terms_reviewed_on": "2026-08-01",
                "permitted_use": "internal",
                "owner": "test",
                "update_frequency": "manual",
                "parser_version": "parser-v1",
            }
        ]
    }


def strict_record(
    *,
    source_id="fixture",
    data_class="synthetic_fixture",
    snapshot_id="snap-1",
    snapshot_hash="",
    is_synthetic="yes",
    record_date="2026-01-15",
    record_id="record-1",
):
    return {
        "record_id": record_id,
        "record_date": record_date,
        "market": "sale",
        "status": "closed",
        "prefecture": "Tokyo",
        "ward": "Minato",
        "building_name": "Fixture Tower",
        "area_sqm": "50",
        "amount_yen": "100000000",
        "amount_unit": "jpy_total",
        "currency": "JPY",
        "source_id": source_id,
        "source_url": "https://example.invalid/synthetic",
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "snapshot_captured_at": "2026-01-31T00:00:00+00:00",
        "source_period_from": record_date[:7] + "-01",
        "source_period_to": record_date[:7] + "-31",
        "parser_version": "parser-v1",
        "verified_on": "2026-02-01",
        "rights_confirmed": "yes",
        "data_class": data_class,
        "is_synthetic": is_synthetic,
    }


def fixture_snapshots(tmp_path, content=b"fixture snapshot"):
    snapshot_path = tmp_path / "snapshot.bin"
    snapshot_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "snapshots": [
            {
                "snapshot_id": "snap-1",
                "source_id": "fixture",
                "source_url": "https://example.invalid/synthetic",
                "captured_at": "2026-01-31T00:00:00+00:00",
                "content_path": str(snapshot_path),
                "content_hash": digest,
                "byte_size": len(content),
                "http_status": 200,
                "parser_version": "parser-v1",
            }
        ]
    }


def test_missing_authorization_evidence_blocks_non_fixture_source(tmp_path):
    registry = {
        "sources": [
            {
                "source_id": "s1",
                "name": "Example partner",
                "source_type": "partner",
                "canonical_url": "https://example.test",
                "permission_status": "pending",
                "rights_evidence": "",
                "terms_reviewed_on": "",
                "permitted_use": "none",
                "owner": "",
                "update_frequency": "monthly",
                "parser_version": "parser-v1",
            }
        ]
    }
    record = strict_record(source_id="s1", data_class="verified_observation", is_synthetic="no")
    report = quality_check([record], registry, {"snapshots": []}, POLICY)

    assert report.publishable is False
    assert "authorization_missing" in {issue.code for issue in report.errors}


def test_source_url_must_stay_under_registered_path(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    snapshots["snapshots"][0]["source_url"] = "https://example.invalid/other"
    record = strict_record(snapshot_hash=snapshot_hash)
    record["source_url"] = "https://example.invalid/other"

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "source_url_mismatch" in {issue.code for issue in report.errors}


def test_snapshot_hash_is_checked_against_local_bytes(tmp_path):
    content = b"fixture snapshot"
    snapshot_path = tmp_path / "snapshot.bin"
    snapshot_path.write_bytes(content)
    snapshots = {
        "snapshots": [
            {
                "snapshot_id": "snap-1",
                "source_id": "fixture",
                "source_url": "https://example.invalid/synthetic",
                "captured_at": "2026-01-31T00:00:00+00:00",
                "content_path": str(snapshot_path),
                "content_hash": "bad",
                "byte_size": len(content),
                "http_status": 200,
                "parser_version": "parser-v1",
            }
        ]
    }
    record = strict_record(source_id="fixture", snapshot_hash="bad")
    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "snapshot_hash_mismatch" in {issue.code for issue in report.errors}


def test_trend_requires_three_periods_and_five_rows_per_period(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    records = []
    for month in ("2026-01", "2026-02", "2026-03"):
        for index in range(4):
            record = strict_record(
                record_id=f"{month}-{index}",
                record_date=f"{month}-15",
                snapshot_hash=snapshot_hash,
            )
            record["source_period_from"] = f"{month}-01"
            record["source_period_to"] = f"{month}-28"
            records.append(record)

    report = quality_check(records, fixture_registry(), snapshots, POLICY)

    assert report.trend_eligibility[0].eligible is False
    assert report.trend_eligibility[0].reason == "trend_insufficient_sample"


def test_duplicate_record_id_and_business_fingerprint_are_blockers(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    first = strict_record(snapshot_hash=snapshot_hash, record_id="same")
    second = strict_record(snapshot_hash=snapshot_hash, record_id="same")

    report = quality_check([first, second], fixture_registry(), snapshots, POLICY)

    codes = {issue.code for issue in report.errors}
    assert "duplicate_record_id" in codes
    assert "duplicate_business_record" in codes
    assert report.publishable is False


def test_missing_provenance_fields_are_reported(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)
    record["source_period_from"] = ""
    record["parser_version"] = ""
    record["source_id"] = ""

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert {"provenance_missing", "source_missing"}.issubset({issue.code for issue in report.errors})


def test_synthetic_flag_must_match_data_class(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash, is_synthetic="no")

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "synthetic_flag_mismatch" in {issue.code for issue in report.errors}


def test_null_registry_owner_does_not_count_as_authorization(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    registry = fixture_registry()
    source = registry["sources"][0]
    source.update(
        {
            "source_type": "partner",
            "permission_status": "confirmed",
            "rights_evidence": "tests/fixtures/authorization.txt",
            "terms_reviewed_on": "2026-01-01",
            "permitted_use": "public_aggregate",
            "owner": None,
        }
    )
    record = strict_record(snapshot_hash=snapshot_hash, data_class="verified_observation", is_synthetic="no")

    report = quality_check([record], registry, snapshots, POLICY)

    assert "authorization_missing" in {issue.code for issue in report.errors}


def test_source_registry_requires_a_versioned_object(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"sources": []}), encoding="utf-8")

    try:
        from jp_property_publisher.pipeline import load_registry

        load_registry(path)
    except ValueError as error:
        assert "registry_version" in str(error)
    else:
        raise AssertionError("unversioned source registry should be rejected")


def test_source_registry_rejects_unknown_source_type(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "registry_version": "source-registry-v1",
                "sources": [
                    {
                        "source_id": "bad",
                        "source_type": "untrusted_unknown",
                        "canonical_url": "https://example.test",
                        "permission_status": "pending",
                        "permitted_use": "none",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    from jp_property_publisher.pipeline import load_registry

    with pytest.raises(ValueError, match="source_type"):
        load_registry(path)


def test_null_provenance_is_treated_as_missing(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)
    record["source_id"] = None

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "provenance_missing" in {issue.code for issue in report.errors}


def test_modeled_estimates_are_blocked_and_excluded_from_metrics(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash, data_class="modeled_estimate", is_synthetic="no")

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "modeled_estimate_blocked" in {issue.code for issue in report.errors}
    assert report.groups == []
    assert report.publishable is False


def test_mixed_synthetic_and_factual_rows_are_blocked_from_publication(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    fixture_hash = snapshots["snapshots"][0]["content_hash"]
    factual_content = b"authorized snapshot"
    factual_path = tmp_path / "factual.bin"
    factual_path.write_bytes(factual_content)
    factual_hash = hashlib.sha256(factual_content).hexdigest()
    snapshots["snapshots"].append(
        {
            "snapshot_id": "snap-factual",
            "source_id": "factual",
            "source_url": "https://example.test/authorized",
            "captured_at": "2026-01-31T00:00:00+00:00",
            "content_path": str(factual_path),
            "content_hash": factual_hash,
            "byte_size": len(factual_content),
            "http_status": 200,
            "parser_version": "parser-v1",
        }
    )
    registry = fixture_registry()
    registry["sources"].append(
        {
            "source_id": "factual",
            "name": "Authorized partner",
            "source_type": "partner",
            "canonical_url": "https://example.test/authorized",
            "permission_status": "confirmed",
            "rights_evidence": "tests/fixtures/authorization.txt",
            "terms_reviewed_on": "2026-01-01",
            "permitted_use": "public_aggregate",
            "owner": "data-team",
            "update_frequency": "monthly",
            "parser_version": "parser-v1",
        }
    )
    factual = strict_record(
        source_id="factual",
        data_class="verified_observation",
        snapshot_id="snap-factual",
        snapshot_hash=factual_hash,
        is_synthetic="no",
    )
    factual["source_url"] = "https://example.test/authorized"

    report = quality_check(
        [strict_record(snapshot_hash=fixture_hash), factual],
        registry,
        snapshots,
        POLICY,
    )

    assert report.publishable is False
    assert report.publication_scope == "blocked_mixed_fixture"


def test_extreme_values_are_visible_as_warnings_without_silent_repair(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)
    record["area_sqm"] = "1200"
    record["amount_yen"] = "1500000000000"

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert {issue.code for issue in report.warnings} == {"suspicious_value"}
    assert report.publishable is True


def test_nonfinite_numeric_values_are_blocked(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)
    record["area_sqm"] = "NaN"
    record["amount_yen"] = "Infinity"

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert {"invalid_area", "invalid_amount"}.issubset({issue.code for issue in report.errors})
    assert prepare_records([record])[0]["price_per_sqm_yen"] == ""


def test_snapshot_hash_must_be_hex_and_capture_time_must_have_timezone(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)
    record["snapshot_hash"] = "g" * 64
    record["snapshot_captured_at"] = "2026-01-31T00:00:00"

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    codes = {issue.code for issue in report.errors}
    assert "invalid_snapshot_hash" in codes
    assert "invalid_snapshot_captured_at" in codes


def test_unreadable_snapshot_is_reported_without_crashing(tmp_path):
    snapshot_path = tmp_path / "snapshot-directory"
    snapshot_path.mkdir()
    snapshots = {
        "snapshots": [
            {
                "snapshot_id": "snap-1",
                "source_id": "fixture",
                "source_url": "https://example.invalid/synthetic",
                "captured_at": "2026-01-31T00:00:00+00:00",
                "content_path": str(snapshot_path),
                "content_hash": "0" * 64,
                "byte_size": 0,
                "http_status": 200,
                "parser_version": "parser-v1",
            }
        ]
    }
    record = strict_record(snapshot_hash="0" * 64)

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "snapshot_content_unreadable" in {issue.code for issue in report.errors}


def test_record_snapshot_capture_time_must_match_manifest(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)
    record["snapshot_captured_at"] = "2026-02-01T00:00:00+00:00"

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "snapshot_captured_at_mismatch" in {issue.code for issue in report.errors}


def test_snapshot_manifest_requires_hash_path_and_parser_version(tmp_path):
    snapshot_path = tmp_path / "snapshot.bin"
    snapshot_path.write_bytes(b"fixture snapshot")
    snapshots = {
        "snapshots": [
            {
                "snapshot_id": "snap-1",
                "source_id": "fixture",
                "source_url": "https://example.invalid/synthetic",
                "captured_at": "2026-01-31T00:00:00+00:00",
                "content_path": str(snapshot_path),
                "content_hash": "",
                "byte_size": 16,
                "http_status": 200,
                "parser_version": "",
            }
        ]
    }
    record = strict_record(snapshot_hash="0" * 64)

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert "snapshot_manifest_missing" in {issue.code for issue in report.errors}


def test_policy_rejects_unknown_group_field(tmp_path):
    path = tmp_path / "policy.json"
    policy = {
        "version": "trend-policy-v1",
        "trend": {
            "minimum_periods": 3,
            "minimum_samples_per_period": 5,
            "minimum_total_samples": 15,
            "group_by": ["not_a_record_field"],
        },
    }
    path.write_text(json.dumps(policy), encoding="utf-8")

    try:
        load_policy(path)
    except ValueError as error:
        assert "group_by" in str(error)
    else:
        raise AssertionError("unknown group field should be rejected")


def test_policy_requires_versioned_object(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text("[]", encoding="utf-8")

    try:
        load_policy(path)
    except ValueError as error:
        assert "object" in str(error)
    else:
        raise AssertionError("non-object policy should be rejected")


def test_record_parser_version_must_match_registered_source(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    registry = fixture_registry()
    registry["sources"][0]["parser_version"] = "parser-v2"
    record = strict_record(snapshot_hash=snapshot_hash)

    report = quality_check([record], registry, snapshots, POLICY)

    assert "parser_version_mismatch" in {issue.code for issue in report.errors}


def test_source_registry_parser_version_is_required(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    registry = fixture_registry()
    registry["sources"][0]["parser_version"] = ""
    record = strict_record(snapshot_hash=snapshot_hash)

    report = quality_check([record], registry, snapshots, POLICY)

    assert "source_parser_version_missing" in {issue.code for issue in report.errors}


def test_empty_dataset_is_not_publishable(tmp_path):
    report = quality_check([], fixture_registry(), {"snapshots": []}, POLICY)

    assert report.publishable is False
    assert "dataset_empty" in {issue.code for issue in report.errors}


def test_metrics_record_missing_value_policy(tmp_path):
    snapshots = fixture_snapshots(tmp_path)
    snapshot_hash = snapshots["snapshots"][0]["content_hash"]
    record = strict_record(snapshot_hash=snapshot_hash)

    report = quality_check([record], fixture_registry(), snapshots, POLICY)

    assert report.groups[0]["missing_value_policy"] == "exclude_invalid_rows_and_report_error"
    assert report.groups[0]["source_ids"] == "fixture"
    assert report.groups[0]["snapshot_ids"] == "snap-1"
    assert report.groups[0]["snapshot_hashes"] == snapshot_hash
    assert report.groups[0]["snapshot_captured_at_from"] == "2026-01-31T00:00:00+00:00"
    assert report.groups[0]["snapshot_captured_at_to"] == "2026-01-31T00:00:00+00:00"
