from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from sync_content_library_to_supabase import query_key, record_location


def test_record_location_uses_structured_c_end_location_not_title() -> None:
    record = {
        "title": "东京都东京23区港区塔楼，租还是买？",
        "prefecture": "东京都",
        "city": "港区",
        "ward": "",
    }

    assert record_location(record) == {
        "prefecture": "东京都",
        "city": "港区",
        "ward": "未細分",
    }
    assert query_key(record_location(record), "塔楼", "2026年9月") == "东京都::港区::未細分::塔楼::2026::9"


def test_record_location_rejects_records_without_structured_location() -> None:
    assert record_location({"title": "东京港区塔楼，租还是买？"}) == {
        "prefecture": "",
        "city": "",
        "ward": "",
    }
