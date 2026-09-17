import io
import gzip
import threading
import json
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.request
from urllib.parse import parse_qs, urlparse

import scripts.import_mlit_transactions as importer
from scripts.import_mlit_transactions import (
    decode_xit001_response,
    normalize_xit001_rows,
    normalize_row,
    rows_from_zip,
)
from backend.app.region_names import RegionMappingReport


def sample_row():
    return {
        "種類": "中古マンション等", "都道府県名": "東京都", "市区町村名": "港区",
        "取引時期": "2025年第1四半期", "取引価格（総額）": "190000000", "面積（㎡）": "55",
        "最寄駅：名称": "汐留", "最寄駅：距離（分）": "4", "間取り": "１ＬＤＫ＋Ｓ",
    }


def test_normalizes_real_official_csv_shape_and_derives_numeric_unit_price():
    row = normalize_row(sample_row(), datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert row["asset_type"] == "公寓"
    assert row["trade_quarter"] == "2025Q1"
    assert row["unit_price_jpy_per_sqm"] == 190000000 / 55
    assert row["city"] == "港区"
    assert len(row["source_record_key"]) == 64


def test_normalizes_mlit_region_to_frontend_shape_and_preserves_japanese_raw():
    row = normalize_xit001_rows(
        [{
            "Type": "中古マンション等", "Prefecture": "新潟県", "Municipality": "南魚沼郡湯沢町",
            "Period": "2025年第1四半期", "TradePrice": "10000000", "Area": "50", "FloorPlan": "2LDK",
        }], datetime(2026, 9, 16, tzinfo=timezone.utc)
    )[0][0]
    assert (row["prefecture"], row["city"], row["ward"]) == ("新潟县", "湯泽町", None)
    assert row["raw"]["Prefecture"] == "新潟県"
    assert row["raw"]["Municipality"] == "南魚沼郡湯沢町"


def test_normalization_report_counts_original_unmapped_city():
    report = RegionMappingReport()
    rows, skipped = normalize_xit001_rows(
        [{
            "Type": "中古マンション等", "Prefecture": "新潟県", "Municipality": "不存在市",
            "Period": "2025年第1四半期", "TradePrice": "10000000", "Area": "50",
        }], datetime(2026, 9, 16, tzinfo=timezone.utc), region_report=report
    )
    assert rows == []
    assert skipped == 0
    assert report.unmapped_city == 1
    assert report.city_samples == ["不存在市"]


def test_summary_prints_unmapped_region_samples(capsys):
    importer.print_unmapped_samples(
        skipped_unmapped_type=0,
        report=RegionMappingReport(
            unmapped_prefecture=1,
            unmapped_city=2,
            prefecture_samples=["未知县"],
            city_samples=["未知市", "另一市"],
        ),
    )

    assert capsys.readouterr().out.splitlines() == [
        "unmapped_prefecture_samples=未知县",
        "unmapped_city_samples=未知市,另一市",
    ]


def test_decodes_cp932_zip_and_skips_unusable_rows():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        import csv
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=list(sample_row()), lineterminator="\n")
        writer.writeheader(); writer.writerow(sample_row())
        archive.writestr("transactions.csv", text.getvalue().encode("cp932"))
    rows = rows_from_zip(output.getvalue(), datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert len(rows) == 1


def test_maps_recorded_xit001_rows_and_computes_missing_unit_price():
    payload = json.loads(Path("tests/fixtures/mlit_xit001_sample.json").read_text())
    rows, skipped_unmapped = normalize_xit001_rows(payload["data"], datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert skipped_unmapped == 1
    assert len(rows) == 2
    assert rows[0]["asset_kind"] == "中古マンション等"
    assert rows[0]["asset_type"] == "公寓"
    assert rows[0]["city"] == "港区"
    assert rows[0]["ward"] is None
    assert rows[0]["unit_price_jpy_per_sqm"] == 2_000_000
    assert rows[0]["trade_quarter"] == "2025Q1"
    assert rows[0]["nearest_station"] is None
    assert rows[0]["raw"]["DistrictName"] == "芝浦"


def test_decodes_gzip_xit001_response():
    body = json.dumps({"status": "OK", "data": []}, ensure_ascii=False).encode()
    assert decode_xit001_response(gzip.compress(body), "gzip") == {"status": "OK", "data": []}


def test_treats_xit001_404_as_no_data():
    assert decode_xit001_response(b"", "", status_code=404) == {"status": "NO_DATA", "data": []}


def test_parser_defaults_to_five_thousand_row_chunks_and_allows_override():
    assert importer.parser().parse_args([]).chunk_size == 5000
    assert importer.parser().parse_args(["--chunk-size", "123"]).chunk_size == 123


def test_deduplicates_chunk_by_source_record_key_and_keeps_first_row():
    first = {"source_record_key": "same", "value": "first"}
    second = {"source_record_key": "same", "value": "second"}
    third = {"source_record_key": "other", "value": "third"}

    unique, skipped = importer._deduplicate_chunk([first, second, third])

    assert unique == [first, third]
    assert skipped == 1


def test_requests_local_xit001_server_with_area_and_secret_header():
    seen = {"requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            seen["requests"].append((query, self.headers.get("Ocp-Apim-Subscription-Key")))
            if query.get("quarter") == ["2"]:
                self.send_response(404)
                self.end_headers()
                return
            body = gzip.compress(json.dumps({"status": "OK", "data": []}).encode())
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old_url = importer.XIT001_URL
    importer.XIT001_URL = f"http://127.0.0.1:{server.server_port}/ex-api/external/XIT001"
    local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
    try:
        assert importer.request_xit001({"year": "2025", "quarter": "1", "area": "13", "language": "ja"}, "local-test-key", local_opener)["status"] == "OK"
        assert importer.request_xit001({"year": "2025", "quarter": "2", "area": "13", "language": "ja"}, "local-test-key", local_opener)["status"] == "NO_DATA"
    finally:
        importer.XIT001_URL = old_url
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert seen["requests"][0][0] == {"year": ["2025"], "quarter": ["1"], "area": ["13"], "language": ["ja"]}
    assert seen["requests"][0][1] == "local-test-key"
    assert seen["requests"][1][0] == {"year": ["2025"], "quarter": ["2"], "area": ["13"], "language": ["ja"]}
