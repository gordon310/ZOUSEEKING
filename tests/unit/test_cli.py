import csv
import json

import pytest

from jp_property_publisher.cli import make_report, normalize, read_records


CSV_COLUMNS = [
    "record_date",
    "market",
    "status",
    "prefecture",
    "ward",
    "building_name",
    "area_sqm",
    "amount_yen",
    "source_url",
    "verified_on",
    "rights_confirmed",
    "data_class",
]


def write_csv(path, rows, columns=CSV_COLUMNS):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{column: row.get(column, "") for column in columns} for row in rows])


def record(amount_yen, data_class="verified_observation"):
    return {
        "record_date": "2026-08-01",
        "market": "sale",
        "status": "closed",
        "prefecture": "Tokyo",
        "ward": "Minato",
        "building_name": "匿名化塔楼",
        "area_sqm": "50",
        "amount_yen": str(amount_yen),
        "source_url": "https://example.com/authorized-record",
        "verified_on": "2026-08-02",
        "rights_confirmed": "yes",
        "data_class": data_class,
    }


def test_read_records_requires_data_class(tmp_path):
    path = tmp_path / "records.csv"
    write_csv(path, [record(100_000_000)], columns=[column for column in CSV_COLUMNS if column != "data_class"])

    with pytest.raises(ValueError, match="data_class"):
        read_records(path)


def test_read_records_rejects_unknown_data_class(tmp_path):
    path = tmp_path / "records.csv"
    write_csv(path, [record(100_000_000, "unknown")])

    with pytest.raises(ValueError, match="data_class"):
        read_records(path)


def test_report_separates_data_classes_with_same_period_and_market(tmp_path):
    path = tmp_path / "records.csv"
    write_csv(path, [record(100_000_000), record(300_000_000, "synthetic_fixture")])

    records = normalize(read_records(path))
    output_dir = tmp_path / "report"
    make_report(records, "测试报告", output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["groups"] == [
        {
            "month": "2026-08",
            "market": "sale",
            "status": "closed",
            "data_class": "synthetic_fixture",
            "sample_count": "1",
            "median_amount_yen": "300000000",
            "median_price_per_sqm_yen": "6000000",
        },
        {
            "month": "2026-08",
            "market": "sale",
            "status": "closed",
            "data_class": "verified_observation",
            "sample_count": "1",
            "median_amount_yen": "100000000",
            "median_price_per_sqm_yen": "2000000",
        },
    ]


def test_report_rejects_modeled_estimates_as_factual_metrics(tmp_path):
    path = tmp_path / "records.csv"
    write_csv(path, [record(100_000_000, "modeled_estimate")])
    records = normalize(read_records(path))

    with pytest.raises(ValueError, match="modeled_estimate"):
        make_report(records, "不应发布", tmp_path / "report")
