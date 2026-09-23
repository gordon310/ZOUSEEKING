#!/usr/bin/env python3
"""Use the content-library owner workflow to label legacy JPHOUSE examples."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "content_library.json"
WEB = ROOT / "web" / "content-library.json"


def main() -> int:
    records = json.loads(CANONICAL.read_text(encoding="utf-8"))
    for record in records:
        record["data_class"] = "synthetic_fixture"
        record["source_id"] = "synthetic_fixture:jphouse_worker"
        record["source_url"] = "local://jphouse-worker/synthetic-fixture"
        record["data_sources"] = [{
            "id": record["source_id"],
            "name": "JPHOUSE synthetic fixture generator",
            "url": record["source_url"],
            "usage": "Non-market example; never a verified observation or market statistic.",
        }]
    payload = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    CANONICAL.write_text(payload, encoding="utf-8")
    WEB.write_text(payload, encoding="utf-8")
    print(json.dumps({"labeled": len(records), "data_class": "synthetic_fixture"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
