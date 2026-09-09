from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WEB_LIBRARY = ROOT / "web" / "content-library.json"


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def query_key(prefecture: str, city: str, ward: str | None, asset_type: str, year: int, month: int) -> str:
    return "::".join([prefecture, city, ward or "全部区", asset_type, str(year), str(month)])


def query_title(prefecture: str, city: str, ward: str | None, asset_type: str, year: int, month: int) -> str:
    area = "".join(part for part in [prefecture, city, ward or ""] if part)
    return f"{area or '日本'}{asset_type}｜{year}年{month}月"


def record_location(record: dict[str, Any]) -> dict[str, str]:
    title = record.get("title", "")
    if title.startswith("东京"):
        return {"prefecture": "东京都", "city": "东京23区", "ward": title.removeprefix("东京").split("塔楼")[0]}
    if title.startswith("大阪"):
        return {"prefecture": "大阪府", "city": "大阪市", "ward": title.removeprefix("大阪").split("塔楼")[0]}
    if title.startswith("横滨"):
        return {"prefecture": "神奈川县", "city": "横滨市", "ward": title.removeprefix("横滨").split("塔楼")[0]}
    return {"prefecture": "", "city": "", "ward": ""}


def load_local_records() -> list[dict[str, Any]]:
    if not WEB_LIBRARY.exists():
        return []
    return json.loads(WEB_LIBRARY.read_text(encoding="utf-8"))


def match_local_record(prefecture: str, city: str, ward: str | None, asset_type: str, year: int, month: int) -> dict[str, Any] | None:
    month_text = f"{year}年{month}月"
    for record in load_local_records():
        loc = record_location(record)
        if loc["prefecture"] != prefecture:
            continue
        if loc["city"] != city:
            continue
        if ward and loc["ward"] != ward:
            continue
        if asset_type == "塔楼" and "塔楼" not in record.get("title", ""):
            continue
        if asset_type != "塔楼" and record.get("asset_type") != asset_type:
            continue
        if record.get("publish_month") != month_text:
            continue
        return record
    return None


def xhs_content_from_record(record: dict[str, Any]) -> str:
    title = record.get("title", "")
    markdown = record.get("markdown", "")
    return f"{title}\n\n{markdown}".strip()


def report_from_local_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": record.get("slug"),
        "title": record.get("title"),
        "publish_month": record.get("publish_month"),
        "markdown": record.get("markdown", ""),
        "xhs_content": xhs_content_from_record(record),
        "rental": record.get("rental", []),
        "sale": record.get("sale", []),
        "summary": record.get("summary", {}),
        "images": record.get("images", []),
        "data_sources": record.get("data_sources", []),
        "raw_record": record,
    }


def placeholder_xhs(prefecture: str, city: str, ward: str | None, asset_type: str, year: int, month: int) -> str:
    title = query_title(prefecture, city, ward, asset_type, year, month)
    return (
        f"# {title}\n\n"
        f"{title}，租还是买？\n\n"
        "这条查询已记录。报告只使用已获授权的公开数据(成交参考以国土交通省取引価格情報为准)；未授权数据源不采集、不输出。"
    )


# Placeholder (no-snapshot) reports carry NO data_sources: nothing was collected/derived yet, and listing unlicensed feeds (SUUMO/Tochidai/etc.) would misrepresent them as authorized sources (D6a / 2026-09-07 source matrix).
def fallback_sources(prefecture: str, city: str, ward: str | None) -> list[dict[str, str]]:
    return []
