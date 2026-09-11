#!/usr/bin/env python3
"""Build aggregate snapshots containing only authorized source fields."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES_VERSION = "licensed-aggregate-v1"
DEFAULT_FAMILIES = (
    "jphouse_23ku",
    "jphouse_osaka_wards",
    "jphouse_yokohama_wards",
)
_TOP_LEVEL_FIELDS = {"count", "failed_count", "failed", "collected"}
_RECORD_FIELDS = {"ward", "config", "output", "sale"}
_SALE_FIELDS = {"layout_price_man_yen", "unit_man_yen_per_sqm", "updated"}


def _filter_record(record: dict[str, Any], filtered_fields: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in record.items():
        if key not in _RECORD_FIELDS:
            filtered_fields.add("source_update" if key == "suumo_updated" else key)
            continue
        if key != "sale":
            result[key] = copy.deepcopy(value)
            continue
        if not isinstance(value, dict):
            filtered_fields.add("sale")
            continue
        sale: dict[str, Any] = {}
        for sale_key, sale_value in value.items():
            if sale_key in _SALE_FIELDS:
                sale[sale_key] = copy.deepcopy(sale_value)
            else:
                filtered_fields.add(f"sale.{sale_key}")
        result["sale"] = sale
    return result


def _filter_entries(entries: list[Any], filtered_fields: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("aggregate entry must be an object")
        result.append(_filter_record(entry, filtered_fields))
    return result


def filter_aggregate(data: Any) -> tuple[Any, dict[str, Any]]:
    """Return a same-shaped aggregate with unlicensed fields removed."""
    filtered_fields: set[str] = set()
    if isinstance(data, list):
        result = _filter_entries(data, filtered_fields)
        summary = {
            "fields": sorted(filtered_fields),
            "reason": "unlicensed_source",
            "rules_version": RULES_VERSION,
        }
        result.append({"_filtered": summary})
        return result, summary
    if not isinstance(data, dict):
        raise ValueError("aggregate root must be a list or object")

    result: dict[str, Any] = {}
    for key, value in data.items():
        if key == "collected":
            if not isinstance(value, list):
                filtered_fields.add("collected")
                continue
            result[key] = _filter_entries(value, filtered_fields)
        elif key in _TOP_LEVEL_FIELDS:
            result[key] = copy.deepcopy(value)
        else:
            filtered_fields.add(key)
    summary = {
        "fields": sorted(filtered_fields),
        "reason": "unlicensed_source",
        "rules_version": RULES_VERSION,
    }
    result["_filtered"] = summary
    return result, summary


def build_family(family: str, root: Path = ROOT) -> tuple[Path, dict[str, Any]]:
    input_path = root / "data" / "collected" / f"{family}_sources.json"
    output_path = root / "data" / "collected_licensed" / f"{family}_sources.json"
    data = json.loads(input_path.read_text(encoding="utf-8"))
    filtered, summary = filter_aggregate(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("families", nargs="*", default=DEFAULT_FAMILIES)
    args = parser.parse_args()
    for family in args.families:
        output_path, summary = build_family(family)
        fields = ", ".join(summary["fields"]) or "(none)"
        kept = "ward, config, output (when present), sale.layout_price_man_yen, " \
            "sale.unit_man_yen_per_sqm, sale.updated"
        print(f"{family}: kept fields: {kept}; filtered fields: {fields}; output={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
