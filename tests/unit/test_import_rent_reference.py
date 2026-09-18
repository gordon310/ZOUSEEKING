from pathlib import Path

from openpyxl import Workbook

from scripts.import_rent_reference import (
    parse_housing_land_workbook,
    parse_kouri_workbook,
)


def test_housing_land_parser_uses_excl_zero_and_maps_special_wards(tmp_path: Path):
    path = tmp_path / "housing.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "e122_4"
    sheet.append(["title"])
    sheet.append(["第122-4表"])
    for _ in range(2):
        sheet.append([])
    sheet.append([None, None, "表章項目", *([None] * 14)])
    sheet.append([None, None, "事項名", *([None] * 14)])
    sheet.append([None, None, "項目名", *([None] * 14)])
    sheet.append([None, None, "表章単位", *([None] * 14)])
    sheet.append(["地域識別コード", "地域区分", "住宅の所有の関係"] + [None] * 14)
    sheet.append(["a", "13000_東京都", "0_総数"] + [None] * 14)
    sheet.append(["0", "13101_千代田区", "3_民営借家"] + [None] * 12 + [3800, 3807])
    sheet.append(["1", "13100_特別区部", "3_民営借家"] + [None] * 12 + [2760, 2800])
    sheet.append(["2", "13102_中央区", "3_民営借家"] + [None] * 12 + ["-", "-"])
    workbook.save(path)

    rows, report = parse_housing_land_workbook(path)

    assert [(row["city"], row["ward"], row["rent_jpy_per_sqm_month_excl_zero"]) for row in rows] == [
        ("千代田区", "__not_subdivided__", 3807),
        ("东京23区", "__not_subdivided__", 2800),
    ]
    assert report.skipped == 1


def test_kouri_parser_converts_33sqm_month_to_sqm_month(tmp_path: Path):
    path = tmp_path / "kouri.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "B001-2"
    sheet.cell(10, 15, "地域")
    sheet.cell(10, 16, "01100")
    sheet.cell(11, 15, "地域")
    sheet.cell(11, 16, "札幌市")
    sheet.cell(12, 9, "2026年8月")
    sheet.cell(12, 10, 3001)
    sheet.cell(12, 11, "民営家賃")
    sheet.cell(12, 12, "1か月･3.3m2")
    sheet.cell(12, 16, 4233)
    workbook.save(path)

    rows, report = parse_kouri_workbook(path)

    assert rows[0]["city"] == "札幌市"
    assert rows[0]["observed_month"] == "2026-08"
    assert rows[0]["rent_jpy_per_sqm_month"] == 4233 / 3.3
    assert report.skipped == 0
