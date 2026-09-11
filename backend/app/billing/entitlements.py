"""Server-owned membership entitlement vocabulary and safe fallbacks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

UTC_PLUS_8 = timezone(timedelta(hours=8), name="UTC+08:00")
METRICS = ("query", "report", "stats_query", "export_row", "subscription_slot")
PERIODS = ("day", "month")

# The product specification is also the last-resort behavior when the database
# is empty or temporarily unavailable. Values are numeric and never parsed from UI text.
DEFAULT_ENTITLEMENTS: dict[str, dict[tuple[str, str], int]] = {
    "free_c": {("query", "day"): 3},
    "c_plus": {
        ("query", "month"): 100,
        ("report", "month"): 12,
        ("subscription_slot", "month"): 3,
    },
    "free_b": {
        ("query", "month"): 30,
        ("stats_query", "month"): 5,
    },
    "b_data_pro": {
        ("query", "month"): 500,
        ("stats_query", "month"): 100,
        ("subscription_slot", "month"): 10,
        ("export_row", "month"): 10000,
    },
}

# Compatibility for existing membership_tier values.
TIER_TO_PLAN = {"free": "free_c", "free_c": "free_c", "free_b": "free_b", "c_plus": "c_plus", "b_data_pro": "b_data_pro"}
PLAN_AUDIENCE = {"free_c": "c", "c_plus": "c", "free_b": "b", "b_data_pro": "b"}
logger = logging.getLogger(__name__)


def period_key(value: datetime, period: str) -> str:
    if period not in PERIODS:
        raise ValueError("period must be 'day' or 'month'")
    local = value.astimezone(UTC_PLUS_8)
    return local.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")


def plan_for_tier(tier: Optional[str], audience: Optional[str] = None) -> str:
    plan = TIER_TO_PLAN.get(str(tier or "free"), "free_c")
    if plan == "free_c" and audience == "b":
        return "free_b"
    return plan


def _row_value(rows: Iterable[Mapping[str, Any]], metric: str, period: str) -> Optional[int]:
    matches = [row for row in rows if row.get("metric") == metric and row.get("period") == period and row.get("active", True)]
    if not matches:
        return None
    return max(0, int(matches[0]["limit_units"]))


def entitlement_limit(
    plan_code: str,
    metric: str,
    period: str,
    *,
    rows: Optional[Iterable[Mapping[str, Any]]] = None,
    legacy_limit: Optional[int] = None,
) -> Optional[int]:
    """Resolve an entitlement with metric-level DB precedence."""
    if metric not in METRICS or period not in PERIODS:
        raise ValueError("unsupported metric or period")
    if rows is not None:
        materialized = list(rows)
        metric_rows = [
            row for row in materialized
            if row.get("metric") == metric and row.get("active", True)
        ]
        value = _row_value(metric_rows, metric, period)
        if value is not None:
            return value
        if metric_rows:
            return None
    if legacy_limit is not None and period == "month" and int(legacy_limit) > 0:
        return int(legacy_limit)
    return DEFAULT_ENTITLEMENTS.get(plan_code, {}).get((metric, period))


def normalize_entitlements(
    plan_code: str,
    *,
    rows: Optional[Iterable[Mapping[str, Any]]] = None,
    legacy: Optional[Mapping[str, Optional[int]]] = None,
) -> dict[tuple[str, str], int]:
    legacy = legacy or {}
    rows = list(rows) if rows is not None else None
    result: dict[tuple[str, str], int] = {}
    for metric in METRICS:
        for period in PERIODS:
            legacy_key = {
                "query": "monthly_query_limit",
                "report": "monthly_report_quota",
                "subscription_slot": "subscription_slots",
                "export_row": "export_rows_monthly",
            }.get(metric)
            value = entitlement_limit(plan_code, metric, period, rows=rows, legacy_limit=legacy.get(legacy_key) if legacy_key else None)
            if value is not None:
                result[(metric, period)] = value
    return result
