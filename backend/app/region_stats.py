"""Honest, numeric regional sale-price statistics for MLIT transaction rows."""

from __future__ import annotations

from math import floor
from typing import Any

MIN_SAMPLE_SIZE = 5
BUCKETS = ((0, 250_000), (250_000, 500_000), (500_000, 1_000_000), (1_000_000, None))
ASSET_TYPE_MAP = {
    "中古マンション等": "公寓",
    "宅地(土地と建物)": "独栋",
    "宅地(土地)": "土地",
    "土地": "土地",
}


def map_asset_type(raw_kind: str) -> str | None:
    return ASSET_TYPE_MAP.get((raw_kind or "").strip())


def _percentile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    low = floor(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def aggregate_region_rows(rows: list[dict[str, Any]], *, asset_type: str, period: str) -> dict[str, Any]:
    values = sorted(
        float(row["unit_price_jpy_per_sqm"])
        for row in rows
        if row.get("unit_price_jpy_per_sqm") is not None and float(row["unit_price_jpy_per_sqm"]) > 0
    )
    result: dict[str, Any] = {
        "status": "ok" if len(values) >= MIN_SAMPLE_SIZE else "insufficient_sample",
        "sample_size": len(values),
        "period": period,
        "asset_type": asset_type,
        "rent_sale_ratio": {"available": False, "reason": "租金数据未授权"},
    }
    if len(values) < MIN_SAMPLE_SIZE:
        result["message"] = "样本不足"
        return result
    result.update(
        {
            "median_unit_price_jpy_per_sqm": _percentile(values, 0.5),
            "p25": _percentile(values, 0.25),
            "p75": _percentile(values, 0.75),
            "distribution": [
                {"lower": lower, "upper": upper, "count": sum(lower <= value < upper if upper else lower <= value for value in values)}
                for lower, upper in BUCKETS
            ],
        }
    )
    return result
