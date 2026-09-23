#!/usr/bin/env python3
"""Audit the tracked content-library copies without mutating either one."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "content_library.json"
WEB = ROOT / "web" / "content-library.json"
REQUIRED_ALL = ("data_class", "source_id", "source_url", "prefecture", "city", "ward", "asset_type")
REQUIRED_NON_SYNTHETIC = ("retrieved_at", "source_period", "transformation_version", "rights_status")


def _missing(record: dict, fields: tuple[str, ...]) -> list[str]:
    return [field for field in fields if not str(record.get(field) or "").strip()]


def audit() -> dict:
    canonical_bytes = CANONICAL.read_bytes()
    web_bytes = WEB.read_bytes()
    canonical = json.loads(canonical_bytes)
    web = json.loads(web_bytes)
    violations = []
    for record in canonical:
        data_class = str(record.get("data_class") or "")
        missing = _missing(record, REQUIRED_ALL)
        if data_class != "synthetic_fixture":
            missing.extend(field for field in REQUIRED_NON_SYNTHETIC if field not in missing and not str(record.get(field) or "").strip())
        if missing:
            violations.append({"id": record.get("id"), "data_class": data_class or None, "missing": sorted(missing)})
    return {
        "schema_version": 1,
        "canonical_record_count": len(canonical),
        "web_record_count": len(web),
        "missing_field_counts": {field: sum(field in _missing(record, REQUIRED_ALL) for record in canonical) for field in REQUIRED_ALL},
        "non_synthetic_violations": [item for item in violations if item["data_class"] != "synthetic_fixture"],
        "all_record_violations": violations,
        "copies": {
            "canonical_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            "web_sha256": hashlib.sha256(web_bytes).hexdigest(),
            "sha256_match": canonical_bytes == web_bytes,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["non_synthetic_violations"] and report["copies"]["sha256_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
