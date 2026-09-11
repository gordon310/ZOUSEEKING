from __future__ import annotations

import zipfile
from pathlib import Path

from backend.app.recognition.municipality import lookup_municipality
from scripts.build_municipality_codes import build_codes_from_xlsx


def test_build_codes_from_small_xlsx_skips_prefecture_rows(tmp_path: Path):
    source = tmp_path / "fixture.xlsx"
    shared = """<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><si><t>団体コード</t></si><si><t>北海道</t></si><si><t>札幌市</t></si><si><t></t></si><si><t>131016</t></si></sst>"""
    sheet = """<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>
      <row><c t=\"s\"><v>0</v></c><c t=\"s\"><v>1</v></c><c t=\"s\"><v>2</v></c></row>
      <row><c t=\"s\"><v>4</v></c><c t=\"s\"><v>1</v></c><c t=\"s\"><v>2</v></c></row>
      <row><c t=\"s\"><v>4</v></c><c t=\"s\"><v>1</v></c><c t=\"s\"><v>3</v></c></row>
    </sheetData></worksheet>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)

    assert build_codes_from_xlsx(source) == {"13101": {"prefecture": "北海道", "city": "札幌市"}}


def test_lookup_municipality_splits_designated_city_and_ward():
    assert lookup_municipality("27127", codes={"27127": {"prefecture": "大阪府", "city": "大阪市北区"}}) == {
        "prefecture": "大阪府",
        "city": "大阪市",
        "ward": "北区",
    }


def test_lookup_municipality_returns_none_for_unknown_code():
    assert lookup_municipality("99999") is None
