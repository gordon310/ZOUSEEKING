"""Market data engine: query -> numeric market snapshot report.

Reads the collected numeric snapshots (data/collected/*_sources.json, produced by the
P1 collection pipeline) and builds property reports with numeric fields plus
provenance metadata. Data classes follow AGENTS.md: these rows are scraped_aggregate
snapshots with explicit period/source notes; nothing here is modeled or synthetic.

D6a (2026-09-07): paid/deep reports consume the sale (closed-transaction) side only.
The rents side is SUUMO-sourced and not authorized for commercial display, so it is
carried in the data layer but never emitted into reports until a license exists.

Coverage: ward-level rows for 23ku (Tokyo), Osaka 23 wards, Yokohama 18 wards.
Queries outside coverage (or for asset types without data) resolve to None and the
caller keeps the existing honest empty-state path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
COLLECTED_DIR = ROOT / "data" / "collected"

FAMILY_SOURCES = {
    "jphouse_23ku": ("东京都", "jphouse_23ku_sources.json"),
    "jphouse_osaka_wards": ("大阪府", "jphouse_osaka_wards_sources.json"),
    "jphouse_yokohama_wards": ("神奈川县", "jphouse_yokohama_wards_sources.json"),
}

# Collected snapshots cover middle-market condominium transactions (中古マンション).
# Detached-house and other asset queries have no numeric snapshot -> honest empty state.
SUPPORTED_ASSET_TYPES = frozenset({"塔楼", "公寓", "中古マンション", "マンション"})
# 一户建 (detached) etc. intentionally unsupported until a numeric source exists.

LAYOUTS = ("1LDK", "2LDK", "3LDK")

MAN_YEN_TO_YEN = 10_000


@dataclass(frozen=True)
class WardSnapshot:
    family: str
    prefecture: str
    ward: str
    rents: Mapping[str, float | None]  # man-yen per month; SUUMO-sourced, NOT for display
    rents_period: str
    sale: Mapping[str, Any]
    sale_period: str
    source_file: str

    @property
    def unit_yen_per_sqm(self) -> float | None:
        raw = (self.sale or {}).get("unit_man_yen_per_sqm")
        return round(float(raw) * MAN_YEN_TO_YEN) if raw else None

    def layout_amount_yen(self, layout: str) -> int | None:
        prices = (self.sale or {}).get("layout_price_man_yen") or {}
        raw = prices.get(layout)
        return round(float(raw) * MAN_YEN_TO_YEN) if raw else None


def _load_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    return data.get("collected", []) if isinstance(data, dict) else []


def load_snapshots(collected_dir: Path = COLLECTED_DIR) -> list[WardSnapshot]:
    rows: list[WardSnapshot] = []
    for family, (prefecture, filename) in FAMILY_SOURCES.items():
        for item in _load_file(collected_dir / filename):
            ward = str(item.get("ward", "")).strip()
            if not ward:
                continue
            rents = item.get("rents") or {}
            sale = item.get("sale") or {}
            rows.append(
                WardSnapshot(
                    family=family,
                    prefecture=prefecture,
                    ward=ward,
                    rents={k: rents.get(k) for k in LAYOUTS},
                    rents_period=str(item.get("suumo_updated", "")).strip(),
                    sale=sale,
                    sale_period=str(sale.get("updated", "")).strip(),
                    source_file=filename,
                )
            )
    return rows


def match_snapshot(
    snapshots: list[WardSnapshot],
    prefecture: str,
    ward: str | None,
    asset_type: str | None,
) -> WardSnapshot | None:
    """Match a query to a ward snapshot. Asset type gates which families are usable.

    Detached-house and out-of-coverage queries return None (caller keeps honest
    empty-state). The ward is the finest granularity the numeric sources carry.
    """
    if not ward or asset_type in ("一户建", "一戸建て"):
        return None
    asset_type = asset_type or ""
    if asset_type and not any(t in asset_type for t in ("塔楼", "公寓", "マンション", "中古")):
        return None
    for row in snapshots:
        if row.prefecture == prefecture and row.ward == ward:
            return row
    return None


def _area_hint(layout: str) -> str:
    # Approx area bands used only as display context; not a numeric source.
    return {"1LDK": "约39–45㎡", "2LDK": "约59–65㎡", "3LDK": "约79–85㎡"}.get(layout, "")


def _fmt_yen(v: int) -> str:
    return f"约{round(v / MAN_YEN_TO_YEN)}万日元"


def _fmt_unit(v: float) -> str:
    return f"约{v / MAN_YEN_TO_YEN:,.2f}万日元/㎡"


def build_sale_report(snapshot: WardSnapshot, query: Mapping[str, Any]) -> dict[str, Any]:
    """Numeric sale-side report. rental rows are omitted (D6a: rents not licensed).

    Returns report shape compatible with property_reports JSONB columns:
    rows carry both numeric fields (amount_yen, unit_yen_per_sqm) and display
    strings; consumers must read the numeric fields for any calculation.
    """
    area_title = "".join(part for part in [query.get("prefecture", ""), query.get("city", ""), query.get("ward", "")] if part) or "日本"
    asset_label = str(query.get("asset_type") or "中古マンション")
    sale_rows = []
    for layout in LAYOUTS:
        amount_yen = snapshot.layout_amount_yen(layout)
        if amount_yen is None:
            continue
        unit = snapshot.unit_yen_per_sqm
        sale_rows.append(
            {
                "layout": layout,
                "area": _area_hint(layout),
                # numeric fields (authoritative for any calculation)
                "amount_yen": amount_yen,
                "unit_yen_per_sqm": unit,
                # display strings (compat with existing frontend rendering)
                "amount_jpy": _fmt_yen(amount_yen),
                "unit_jpy": _fmt_unit(unit) if unit else "",
                "period": snapshot.sale_period,
                "data_class": "scraped_aggregate",
            }
        )
    title = f"{area_title}{asset_label}成交参考"
    markdown_lines = [
        f"# {title}",
        "",
        f"数据:中古マンション成交均价(国交省取引数据整理),期间 {snapshot.sale_period or '未标注'}。",
        "租金侧对比暂缺:租金授权数据源待接入,当前不提供租买比。",
        "",
        "| 户型 | 面积参考 | 成交均价 | 平米单价 |",
        "| --- | --- | --- | --- |",
    ]
    for row in sale_rows:
        markdown_lines.append(
            f"| {row['layout']} | {row['area']} | {row['amount_jpy']} | {row['unit_jpy']} |"
        )
    return {
        "slug": f"jphouse_{snapshot.family}_{snapshot.ward}_{query.get('asset_type') or 'tower'}",
        "title": title,
        "publish_month": snapshot.sale_period,
        "markdown": "\n".join(markdown_lines),
        "xhs_content": "",
        "rental": [],
        "sale": sale_rows,
        "summary": {
            "title": "总而言之",
            "line": "、".join(f"{r['layout']} {r['amount_jpy']}" for r in sale_rows) if sale_rows else "暂无数据",
            "note": "成交均价为中古マンション口径;租金对比待授权源(见报告说明)。",
        },
        "images": [],
        "data_sources": [
            {
                "name": "国土交通省 土地総合情報システム(取引価格情報)整理",
                "period": snapshot.sale_period,
                "data_class": "scraped_aggregate",
                "usage": "中古マンション成交均价/平米单价,按户型",
                "rights": "政府开放数据,出所明記",
            }
        ],
        "raw_record": {
            "generated_by": "market-engine-v1",
            "source_file": snapshot.source_file,
            "ward": snapshot.ward,
            "query": {k: query.get(k) for k in ("prefecture", "city", "ward", "asset_type", "year", "month")},
        },
    }
