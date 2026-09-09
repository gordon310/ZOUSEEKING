"""Deterministic evidence-aware completeness and free-preview calculations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True)
class FieldValue:
    value: Any
    confirmation_status: str
    confidence: str
    has_evidence: bool


DIMENSIONS: Mapping[str, Tuple[frozenset[str], frozenset[str]]] = {
    "identity": (
        frozenset({"building_name", "address", "area_sqm", "building_year"}),
        frozenset({"address", "area_sqm"}),
    ),
    "price_cost": (
        frozenset({"asking_price_jpy", "management_fee_jpy", "repair_reserve_jpy"}),
        frozenset({"asking_price_jpy"}),
    ),
    "yield": (
        frozenset({"monthly_rent_jpy", "management_fee_jpy", "repair_reserve_jpy"}),
        frozenset(),
    ),
    "building_management": (
        frozenset({"total_units", "management_fee_jpy", "repair_reserve_jpy"}),
        frozenset(),
    ),
    "legal_transaction": (
        frozenset({"land_right", "land_share"}),
        frozenset({"land_right"}),
    ),
    "source_trust": (
        frozenset({"building_name", "address", "asking_price_jpy", "area_sqm"}),
        frozenset(),
    ),
}

CONFIRMED_STATUSES = frozenset({"confirmed", "corrected"})
REVIEWABLE_CONFIDENCE = frozenset({"high", "medium"})
ACQUISITION_COST_ITEMS = (
    "中介手续费",
    "不动产取得税",
    "登记许可税和司法书士费用",
    "印花税",
    "固定资产税、都市计划税及交易清算",
    "贷款手续费、保证费和利息",
    "火灾险、地震险",
    "汇款、换汇和银行费用",
    "其他有证据的交易费用",
)


def _is_confirmed(field: FieldValue | None) -> bool:
    return bool(field and field.value is not None and field.confirmation_status in CONFIRMED_STATUSES)


def _is_trusted(field: FieldValue | None) -> bool:
    return bool(_is_confirmed(field) and field.has_evidence and field.confidence in REVIEWABLE_CONFIDENCE)


def _dimension_result(fields: Mapping[str, FieldValue], required: frozenset[str], critical: frozenset[str]) -> Dict[str, object]:
    missing = sorted(field_name for field_name in required if not _is_confirmed(fields.get(field_name)))
    missing_critical = sorted(field_name for field_name in missing if field_name in critical)
    conflicts = sorted(
        field_name
        for field_name in required
        if fields.get(field_name) and fields[field_name].confirmation_status == "conflict"
    )
    confirmed = len(required) - len(missing)
    total = len(required)
    percent = round(confirmed * 100 / total) if total else 100
    if missing_critical:
        status = "insufficient_data"
    elif confirmed == total:
        status = "complete"
    elif confirmed:
        status = "partial"
    else:
        status = "empty"
    return {
        "confirmed": confirmed,
        "total": total,
        "percent": percent,
        "status": status,
        "missing": missing,
        "missing_critical": missing_critical,
        "conflicts": conflicts,
    }


def calculate_completeness(fields: Mapping[str, FieldValue]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    for dimension, (required, critical) in DIMENSIONS.items():
        if dimension == "source_trust":
            trusted = frozenset(
                field_name for field_name in required if _is_trusted(fields.get(field_name))
            )
            missing = sorted(required - trusted)
            conflicts = sorted(
                field_name
                for field_name in required
                if fields.get(field_name) and fields[field_name].confirmation_status == "conflict"
            )
            confirmed = len(trusted)
            total = len(required)
            result[dimension] = {
                "confirmed": confirmed,
                "total": total,
                "percent": round(confirmed * 100 / total) if total else 100,
                "status": "complete" if confirmed == total else ("partial" if confirmed else "empty"),
                "missing": missing,
                "missing_critical": [],
                "conflicts": conflicts,
            }
            continue
        result[dimension] = _dimension_result(fields, required, critical)
    return result


def _risk_summary(dimensions: Mapping[str, Mapping[str, object]]) -> Dict[str, object]:
    items = []
    for dimension, result in dimensions.items():
        missing_critical = result["missing_critical"]
        conflicts = result["conflicts"]
        if missing_critical:
            items.append({
                "type": "missing_critical_evidence",
                "dimension": dimension,
                "fields": missing_critical,
                "severity": "high",
            })
        if conflicts:
            items.append({
                "type": "field_conflict",
                "dimension": dimension,
                "fields": conflicts,
                "severity": "medium",
            })
    counts = {
        "high": sum(item["severity"] == "high" for item in items),
        "medium": sum(item["severity"] == "medium" for item in items),
    }
    return {
        "status": "data_warnings" if items else "no_data_warnings",
        "total": len(items),
        "counts": counts,
        "items": items,
    }


def _comparable_check(
    fields: Mapping[str, FieldValue], snapshots_dir: Path | None = None
) -> Dict[str, object]:
    """Comparable market check against the collected numeric snapshots.

    Uses the confirmed address (prefecture + ward) when present. Returns an
    honest status: sufficient (with numeric reference rows), insufficient
    (out of coverage / address not resolved), not_checked (no address to check).
    Never approximates across wards.
    snapshots_dir is injectable so tests run against committed fixtures
    (data/collected is gitignored runtime data, absent in CI); production
    callers omit it and read the runtime collected directory.
    """
    address_field = fields.get("address")
    address = str(address_field.value).strip() if address_field and address_field.value else ""
    if not address:
        return {"status": "not_checked", "note": "缺少地址,无法检查可比市场。", "reference": []}
    from .market_engine import (
        build_sale_report,
        load_snapshots,
        match_snapshot_from_address,
    )

    snapshot = match_snapshot_from_address(
        address, load_snapshots(snapshots_dir)
    )
    if snapshot is None:
        return {"status": "insufficient", "note": "该地址所在区暂无覆盖(覆盖:东京23区/大阪市23区/横滨市18区)。", "reference": []}
    report = build_sale_report(snapshot, {"prefecture": snapshot.prefecture, "ward": snapshot.ward, "asset_type": "中古マンション"})
    return {
        "status": "sufficient",
        "note": "同区中古マンション成交参考(国交省取引数据,出所明記)。",
        "reference": report["sale"],
    }


def build_free_preview(
    fields: Mapping[str, FieldValue], *, snapshots_dir: Path | None = None
) -> Dict[str, object]:
    completeness = calculate_completeness(fields)
    from .cost_estimator import estimate_acquisition_costs

    acquisition_costs = estimate_acquisition_costs(fields)
    comparable = _comparable_check(fields, snapshots_dir)
    return {
        "completeness": completeness,
        "acquisition_costs": acquisition_costs,
        "risk_summary": _risk_summary(completeness),
        "comparable_status": comparable["status"],
        "comparable": comparable,
        "calculation_version": "free-preview-v1",
    }
