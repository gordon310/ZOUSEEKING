"""Backfill structured library fields from title text and field-options vocabulary."""

from __future__ import annotations

import json
import re
from pathlib import Path

import generate_xhs_package as generator


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "data" / "content_library.json"
FIELD_OPTIONS = ROOT / "web" / "field-options.json"
ASSET_TYPES = ("一户建", "塔楼", "公寓")


def infer_location(record: dict, options: dict) -> dict[str, str]:
    title = str(record.get("title") or "")
    asset_type = next((value for value in ASSET_TYPES if value in title), "")
    if not asset_type:
        raise ValueError(f"cannot infer asset_type from title: {title}")
    prefecture = next((value for value in options["prefectures"] if value in title), "")
    if not prefecture:
        raise ValueError(f"cannot infer prefecture from title: {title}")
    cities = options["cities"].get(prefecture, [])
    city = max((value for value in cities if value in title), key=len, default="")
    if not city:
        raise ValueError(f"cannot infer city from title: {title}")
    wards = options.get("wards", {}).get(f"{prefecture}::{city}", [])
    ward = max((value for value in wards if value in title), key=len, default="未細分")
    return {"prefecture": prefecture, "city": city, "ward": ward, "asset_type": asset_type}


def backfill(path: Path = LIBRARY) -> tuple[list[dict], int]:
    options = json.loads(FIELD_OPTIONS.read_text(encoding="utf-8"))
    records = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for record in records:
        asset_type_is_legacy = record.get("asset_type") not in options.get("assetTypes", [])
        if asset_type_is_legacy or not all(
            str(record.get(field) or "").strip() for field in ("prefecture", "city", "ward")
        ):
            record.update(infer_location(record, options))
            record["regions"] = [record["city"]]
            record["search_text"] = " ".join(
                [
                    record.get("title", ""),
                    record.get("template_name", ""),
                    record.get("publish_month", ""),
                    record["asset_type"],
                    " ".join(record.get("regions", [])),
                    " ".join(record.get("layouts", [])),
                    record.get("markdown", ""),
                    " ".join(record.get("hashtags", [])),
                ]
            ).lower()
            changed += 1
        generator.validate_library_record(record)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    generator.write_web_library(records)
    return records, changed


if __name__ == "__main__":
    records, changed = backfill()
    print(json.dumps({"records": len(records), "backfilled": changed}, ensure_ascii=False))
