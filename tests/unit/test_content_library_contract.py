from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from backfill_content_library_regions import infer_location


OPTIONS = json.loads(Path("web/field-options.json").read_text(encoding="utf-8"))


def test_canonical_and_web_libraries_have_six_vocab_checked_records() -> None:
    canonical = json.loads(Path("data/content_library.json").read_text(encoding="utf-8"))
    web = json.loads(Path("web/content-library.json").read_text(encoding="utf-8"))
    assert canonical == web
    assert len(canonical) == 6
    for record in canonical:
        assert all(record.get(field) for field in ("prefecture", "city", "ward", "asset_type"))
        assert record["prefecture"] in OPTIONS["prefectures"]
        assert record["city"] in OPTIONS["cities"][record["prefecture"]]
        assert record["asset_type"] in OPTIONS["assetTypes"]


def test_backfill_uses_frontend_vocabulary_for_legacy_titles() -> None:
    assert infer_location({"title": "新潟县新潟市塔楼，租还是买？"}, OPTIONS) == {
        "prefecture": "新潟县",
        "city": "新潟市",
        "ward": "未細分",
        "asset_type": "塔楼",
    }
    assert infer_location({"title": "大阪府大阪市生野区一户建，租还是买？"}, OPTIONS) == {
        "prefecture": "大阪府",
        "city": "大阪市",
        "ward": "生野区",
        "asset_type": "一户建",
    }
    assert infer_location({"title": "东京都东京23区港区塔楼，租还是买？"}, OPTIONS) == {
        "prefecture": "东京都",
        "city": "港区",
        "ward": "未細分",
        "asset_type": "塔楼",
    }
