import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
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
COLUMNS = [
    "record_id",
    "record_date",
    "market",
    "status",
    "prefecture",
    "ward",
    "building_name",
    "area_sqm",
    "amount_yen",
    "amount_unit",
    "currency",
    "source_id",
    "source_url",
    "snapshot_id",
    "snapshot_hash",
    "snapshot_captured_at",
    "source_period_from",
    "source_period_to",
    "parser_version",
    "verified_on",
    "rights_confirmed",
    "data_class",
    "is_synthetic",
]


def make_record(month, index, *, status="closed", snapshot_hash=""):
    market = "sale" if status == "closed" else "rental"
    amount_unit = "jpy_total" if market == "sale" else "jpy_monthly"
    return {
        "record_id": f"{month}-{status}-{index}",
        "record_date": f"{month}-15",
        "market": market,
        "status": status,
        "prefecture": "Tokyo",
        "ward": "Minato",
        "building_name": "Fixture Tower",
        "area_sqm": str(50 + index),
        "amount_yen": str(100_000_000 + index * 1_000_000),
        "amount_unit": amount_unit,
        "currency": "JPY",
        "source_id": "fixture",
        "source_url": "https://example.invalid/synthetic",
        "snapshot_id": "snap-1",
        "snapshot_hash": snapshot_hash,
        "snapshot_captured_at": "2026-01-31T00:00:00+00:00",
        "source_period_from": f"{month}-01",
        "source_period_to": f"{month}-28",
        "parser_version": "parser-v1",
        "verified_on": "2026-02-01",
        "rights_confirmed": "yes",
        "data_class": "synthetic_fixture",
        "is_synthetic": "yes",
    }


def write_inputs(tmp_path, rows):
    snapshot_path = tmp_path / "snapshot.txt"
    content = b"fixture snapshot"
    snapshot_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    for row in rows:
        if row["snapshot_hash"] == "__VALID__":
            row["snapshot_hash"] = digest
    csv_path = tmp_path / "records.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "source-registry-v1",
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
                        "owner": "tests",
                        "update_frequency": "manual",
                        "parser_version": "parser-v1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    snapshots_path = tmp_path / "snapshots.json"
    snapshots_path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(POLICY), encoding="utf-8")
    return csv_path, registry_path, snapshots_path, policy_path


def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "jp_property_publisher", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_prepare_writes_separate_listing_closed_metrics_and_quality_report(tmp_path):
    rows = [
        make_record(month, index, status=status, snapshot_hash="__VALID__")
        for month in ("2026-01", "2026-02", "2026-03")
        for status in ("listing", "closed")
        for index in range(5)
    ]
    input_path, registry_path, snapshots_path, policy_path = write_inputs(tmp_path, rows)
    output_dir = tmp_path / "out"

    result = run_cli(
        "prepare",
        "--input",
        str(input_path),
        "--registry",
        str(registry_path),
        "--snapshots",
        str(snapshots_path),
        "--policy",
        str(policy_path),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stderr
    report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert report["publishable"] is True
    with (output_dir / "monthly_metrics.csv").open(encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    assert {row["status"] for row in metric_rows} == {"listing", "closed"}
    assert {row["trend_eligible"] for row in metric_rows} == {"True"}


def test_prepare_returns_nonzero_and_preserves_report_for_missing_provenance(tmp_path):
    rows = [make_record("2026-01", 0, snapshot_hash="")]
    input_path, registry_path, snapshots_path, policy_path = write_inputs(tmp_path, rows)
    output_dir = tmp_path / "out"

    result = run_cli(
        "prepare",
        "--input",
        str(input_path),
        "--registry",
        str(registry_path),
        "--snapshots",
        str(snapshots_path),
        "--policy",
        str(policy_path),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 2
    report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert report["publishable"] is False
    assert any(issue["code"] == "provenance_missing" for issue in report["errors"])


def test_prepare_empty_csv_retains_quality_report(tmp_path):
    input_path, registry_path, snapshots_path, policy_path = write_inputs(tmp_path, [])
    output_dir = tmp_path / "out"

    result = run_cli(
        "prepare",
        "--input",
        str(input_path),
        "--registry",
        str(registry_path),
        "--snapshots",
        str(snapshots_path),
        "--policy",
        str(policy_path),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 2
    report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert any(issue["code"] == "dataset_empty" for issue in report["errors"])
    assert (output_dir / "prepared.csv").read_text(encoding="utf-8").splitlines() == [",".join(COLUMNS + ["month", "price_per_sqm_yen"])]


def test_fixture_pipeline_is_reproducible_and_labeled_synthetic(tmp_path):
    output_dir = tmp_path / "out"
    result = run_cli(
        "prepare",
        "--input",
        str(ROOT / "tests/fixtures/data_pipeline/records.csv"),
        "--registry",
        str(ROOT / "tests/fixtures/data_pipeline/registry.json"),
        "--snapshots",
        str(ROOT / "tests/fixtures/data_pipeline/snapshots.json"),
        "--policy",
        str(ROOT / "configs/data_quality_policy.json"),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["data_class"] == "synthetic_fixture"
    assert summary["trend_eligible"] is True
    assert any("不代表真实市场" in limitation for limitation in summary["limitations"])


def test_quality_check_can_write_json_without_preparing_metrics(tmp_path):
    rows = [make_record("2026-01", 0, snapshot_hash="__VALID__")]
    input_path, registry_path, snapshots_path, policy_path = write_inputs(tmp_path, rows)
    output_path = tmp_path / "quality.json"

    result = run_cli(
        "quality-check",
        "--input",
        str(input_path),
        "--registry",
        str(registry_path),
        "--snapshots",
        str(snapshots_path),
        "--policy",
        str(policy_path),
        "--output",
        str(output_path),
    )

    assert result.returncode == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["input_record_count"] == 1
    assert payload["publishable"] is True
