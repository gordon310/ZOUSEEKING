#!/usr/bin/env python3
"""Build the runtime JIS municipality lookup from the official XLSX file."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable


NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DEFAULT_SOURCE = Path("data/source/jis-codes-2024-01-01.xlsx")
DEFAULT_OUTPUT = Path("data/municipality_codes.json")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall(f"{NAMESPACE}si")]


def _row_values(row: ET.Element, shared: list[str]) -> list[str]:
    values: list[str] = []
    for cell in row.findall(f"{NAMESPACE}c"):
        value = cell.find(f"{NAMESPACE}v")
        if value is None:
            values.append("")
        elif cell.get("t") == "s":
            values.append(shared[int(value.text or "0")])
        else:
            values.append(value.text or "")
    return values


def parse_rows(rows: Iterable[list[str]]) -> dict[str, dict[str, str]]:
    codes: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row or row[0] == "団体コード":
            continue
        code, prefecture, city = (row + [""])[:3]
        code = code.strip()
        prefecture = prefecture.strip()
        city = city.strip()
        if len(code) != 6 or not code.isdigit() or not prefecture or not city:
            continue
        codes[code[:5]] = {"prefecture": prefecture, "city": city}
    return codes


def build_codes_from_xlsx(source: Path) -> dict[str, dict[str, str]]:
    with zipfile.ZipFile(source) as archive:
        shared = _shared_strings(archive)
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        return parse_rows(_row_values(row, shared) for row in root.findall(f".//{NAMESPACE}row"))


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT
    codes = build_codes_from_xlsx(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(codes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    examples = list(codes.items())[:3]
    print(f"wrote {len(codes)} municipality codes to {output}")
    print(f"examples: {json.dumps(examples, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
