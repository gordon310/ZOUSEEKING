import io
import zipfile
from datetime import datetime, timezone

from scripts.import_mlit_transactions import normalize_row, rows_from_zip


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
