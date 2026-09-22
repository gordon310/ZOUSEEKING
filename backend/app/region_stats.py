"""Honest, numeric regional sale-price statistics for MLIT transaction rows."""

from __future__ import annotations

import re
from math import floor
from statistics import mean
from typing import Any

MIN_SAMPLE_SIZE = 5
TRADE_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
BUCKETS = ((0, 250_000), (250_000, 500_000), (500_000, 1_000_000), (1_000_000, None))
ASSET_TYPE_MAP = {
    "中古マンション等": "公寓",
    "宅地(土地と建物)": "独栋",
    "宅地(土地)": "土地",
    "土地": "土地",
}


def map_asset_type(raw_kind: str) -> str | None:
    return ASSET_TYPE_MAP.get((raw_kind or "").strip())


def parse_trade_quarter(period: object) -> tuple[int, int] | None:
    """Return the chronological key for a stored MLIT quarter, if valid."""

    match = TRADE_QUARTER_RE.fullmatch(str(period or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


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
            "mean_unit_price_jpy_per_sqm": mean(values),
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


def aggregate_region_trend_rows(rows: list[dict[str, Any]], *, asset_type: str) -> dict[str, Any]:
    """Build a chronological, non-interpolated series from exact transaction rows.

    This function deliberately has no source/provenance policy: the route owns
    that because each accepted aggregate needs the metadata from its exact
    supporting rows.  It does enforce the shared sample threshold before a
    period can participate in a trend.
    """

    grouped: dict[str, list[dict[str, Any]]] = {}
    invalid_period_rows: dict[str, int] = {}
    for row in rows:
        period = str(row.get("trade_quarter") or "")
        if parse_trade_quarter(period) is None:
            invalid_period_rows[period] = invalid_period_rows.get(period, 0) + 1
            continue
        grouped.setdefault(period, []).append(row)

    accepted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = [
        {"period": period, "reason": "invalid_trade_quarter", "sample_size": sample_size}
        for period, sample_size in invalid_period_rows.items()
    ]
    for period in sorted(grouped, key=lambda value: parse_trade_quarter(value) or (0, 0)):
        aggregate = aggregate_region_rows(grouped[period], asset_type=asset_type, period=period)
        if aggregate["status"] == "ok":
            aggregate["_supporting_rows"] = grouped[period]
            accepted.append(aggregate)
        else:
            excluded.append({
                "period": period,
                "reason": "insufficient_sample",
                "sample_size": int(aggregate["sample_size"]),
            })

    if len(accepted) < 2:
        excluded.extend(
            {"period": item["period"], "reason": "only_one_comparable_period", "sample_size": int(item["sample_size"])}
            for item in accepted
        )
        return {
            "status": "insufficient_periods",
            "period_count": len(accepted),
            "periods": [],
            "excluded_periods": sorted(excluded, key=lambda item: parse_trade_quarter(item["period"]) or (0, 0)),
        }

    return {
        "status": "ok",
        "period_count": len(accepted),
        "periods": accepted,
        "excluded_periods": sorted(excluded, key=lambda item: parse_trade_quarter(item["period"]) or (0, 0)),
    }
