"""Offline preparation and quality gates for auditable multi-month datasets.

This module deliberately has no network, database, or storage dependencies.  A
caller supplies local CSV rows, a source registry, and a snapshot manifest; the
quality gate returns structured issues instead of silently repairing provenance.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


STRICT_COLUMNS: Tuple[str, ...] = (
    "record_id",
    "record_date",
    "market",
    "status",
    "prefecture",
    "ward",
    "building_name",
    "area_sqm",
    "amount_yen",
    "amount_unit",
    "currency",
    "source_id",
    "source_url",
    "snapshot_id",
    "snapshot_hash",
    "snapshot_captured_at",
    "source_period_from",
    "source_period_to",
    "parser_version",
    "verified_on",
    "rights_confirmed",
    "data_class",
    "is_synthetic",
)
ALLOWED_MARKETS = {"sale", "rental"}
ALLOWED_STATUSES = {"listing", "closed"}
ALLOWED_DATA_CLASSES = {
    "verified_observation",
    "scraped_aggregate",
    "modeled_estimate",
    "synthetic_fixture",
}
ALLOWED_SOURCE_TYPES = {"official", "partner", "user_submitted", "synthetic_fixture"}
ALLOWED_PERMISSION_STATUSES = {"confirmed", "pending", "denied", "not_applicable"}
ALLOWED_PERMITTED_USE = {"internal", "public_aggregate", "none"}
DEFAULT_GROUP_BY: Tuple[str, ...] = (
    "prefecture",
    "ward",
    "market",
    "status",
    "data_class",
    "amount_unit",
    "currency",
)


def _clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


@dataclass(frozen=True)
class SourceRegistration:
    source_id: str
    name: str
    source_type: str
    canonical_url: str
    permission_status: str
    rights_evidence: str
    terms_reviewed_on: str
    permitted_use: str
    owner: str
    update_frequency: str
    parser_version: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceRegistration":
        return cls(
            source_id=_clean_text(value.get("source_id", "")),
            name=_clean_text(value.get("name", "")),
            source_type=_clean_text(value.get("source_type", "")),
            canonical_url=_clean_text(value.get("canonical_url", "")),
            permission_status=_clean_text(value.get("permission_status", "")),
            rights_evidence=_clean_text(value.get("rights_evidence", "")),
            terms_reviewed_on=_clean_text(value.get("terms_reviewed_on", "")),
            permitted_use=_clean_text(value.get("permitted_use", "")),
            owner=_clean_text(value.get("owner", "")),
            update_frequency=_clean_text(value.get("update_frequency", "")),
            parser_version=_clean_text(value.get("parser_version", "")),
        )


@dataclass(frozen=True)
class SnapshotManifest:
    snapshot_id: str
    source_id: str
    source_url: str
    captured_at: str
    content_path: str
    content_hash: str
    byte_size: int
    http_status: Optional[int]
    parser_version: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SnapshotManifest":
        byte_size = value.get("byte_size", 0)
        try:
            byte_size = int(byte_size)
        except (TypeError, ValueError):
            byte_size = -1
        status = value.get("http_status")
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        return cls(
            snapshot_id=_clean_text(value.get("snapshot_id", "")),
            source_id=_clean_text(value.get("source_id", "")),
            source_url=_clean_text(value.get("source_url", "")),
            captured_at=_clean_text(value.get("captured_at", "")),
            content_path=_clean_text(value.get("content_path", "")),
            content_hash=_clean_text(value.get("content_hash", "")).lower(),
            byte_size=byte_size,
            http_status=status,
            parser_version=_clean_text(value.get("parser_version", "")),
        )


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    row_number: Optional[int] = None
    severity: str = "error"
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrendEligibility:
    group: Dict[str, str]
    periods: int
    total_samples: int
    minimum_samples_in_period: int
    eligible: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QualityReport:
    errors: List[QualityIssue] = field(default_factory=list)
    warnings: List[QualityIssue] = field(default_factory=list)
    groups: List[Dict[str, Any]] = field(default_factory=list)
    trend_eligibility: List[TrendEligibility] = field(default_factory=list)
    publishable: bool = False
    publication_scope: str = "blocked"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "groups": self.groups,
            "trend_eligibility": [item.to_dict() for item in self.trend_eligibility],
            "publishable": self.publishable,
            "publication_scope": self.publication_scope,
        }


def load_policy(path: Path) -> Dict[str, Any]:
    """Load and validate a versioned quality policy from JSON."""

    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError("quality policy must be a JSON object")
    if not isinstance(policy.get("version"), str) or not policy["version"].strip():
        raise ValueError("quality policy version is required")
    trend = policy.get("trend")
    if not isinstance(trend, dict):
        raise ValueError("quality policy must contain a trend object")
    for key in ("minimum_periods", "minimum_samples_per_period", "minimum_total_samples"):
        value = trend.get(key)
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"trend policy {key} must be a positive integer")
    group_by = trend.get("group_by")
    if not isinstance(group_by, list) or not group_by:
        raise ValueError("trend policy group_by must be a non-empty list")
    unknown_fields = set(group_by) - set(STRICT_COLUMNS)
    if unknown_fields:
        raise ValueError("trend policy group_by contains unknown fields: " + ", ".join(sorted(unknown_fields)))
    return policy


def load_registry(path: Path) -> Dict[str, SourceRegistration]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source registry must be a JSON object")
    if not isinstance(payload.get("registry_version"), str) or not payload["registry_version"].strip():
        raise ValueError("source registry registry_version is required")
    values = payload.get("sources")
    if not isinstance(values, list):
        raise ValueError("source registry must contain a sources list")
    registry: Dict[str, SourceRegistration] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise ValueError("source registry entries must be JSON objects")
        source = SourceRegistration.from_mapping(raw)
        if not source.source_id:
            raise ValueError("source registry source_id is required")
        if source.source_id in registry:
            raise ValueError(f"duplicate source_id: {source.source_id}")
        if source.source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {source.source_type}")
        parsed = urlparse(source.canonical_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"source registry canonical_url must be an absolute http(s) URL: {source.source_id}")
        if source.permission_status not in ALLOWED_PERMISSION_STATUSES:
            raise ValueError(f"unsupported permission_status: {source.permission_status}")
        if source.permitted_use not in ALLOWED_PERMITTED_USE:
            raise ValueError(f"unsupported permitted_use: {source.permitted_use}")
        registry[source.source_id] = source
    return registry


def load_snapshots(path: Path) -> Dict[str, SnapshotManifest]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot manifest must be a JSON object")
    values = payload.get("snapshots")
    if not isinstance(values, list):
        raise ValueError("snapshot manifest must contain a snapshots list")
    snapshots: Dict[str, SnapshotManifest] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise ValueError("snapshot manifest entries must be JSON objects")
        snapshot = SnapshotManifest.from_mapping(raw)
        if not snapshot.snapshot_id:
            raise ValueError("snapshot_id is required")
        if snapshot.snapshot_id in snapshots:
            raise ValueError(f"duplicate snapshot_id: {snapshot.snapshot_id}")
        if not Path(snapshot.content_path).is_absolute():
            snapshot = SnapshotManifest(
                snapshot_id=snapshot.snapshot_id,
                source_id=snapshot.source_id,
                source_url=snapshot.source_url,
                captured_at=snapshot.captured_at,
                content_path=str((path.parent / snapshot.content_path).resolve()),
                content_hash=snapshot.content_hash,
                byte_size=snapshot.byte_size,
                http_status=snapshot.http_status,
                parser_version=snapshot.parser_version,
            )
        snapshots[snapshot.snapshot_id] = snapshot
    return snapshots


def _as_registry(value: Any) -> Dict[str, SourceRegistration]:
    if isinstance(value, Mapping) and "sources" in value:
        values = value["sources"]
        return {
            source.source_id: source
            for source in (SourceRegistration.from_mapping(item) for item in values)
        }
    if isinstance(value, Mapping):
        return {
            key: item if isinstance(item, SourceRegistration) else SourceRegistration.from_mapping(item)
            for key, item in value.items()
        }
    raise TypeError("registry must be a mapping or a {sources: [...]} payload")


def _as_snapshots(value: Any) -> Dict[str, SnapshotManifest]:
    if isinstance(value, Mapping) and "snapshots" in value:
        values = value["snapshots"]
        return {
            snapshot.snapshot_id: snapshot
            for snapshot in (SnapshotManifest.from_mapping(item) for item in values)
        }
    if isinstance(value, Mapping):
        return {
            key: item if isinstance(item, SnapshotManifest) else SnapshotManifest.from_mapping(item)
            for key, item in value.items()
        }
    raise TypeError("snapshots must be a mapping or a {snapshots: [...]} payload")


def _parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _parse_decimal(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _issue(code: str, message: str, row_number: Optional[int] = None, severity: str = "error", **context: Any) -> QualityIssue:
    return QualityIssue(code=code, message=message, row_number=row_number, severity=severity, context=context)


def validate_record(record: Mapping[str, Any], row_number: Optional[int] = None) -> List[QualityIssue]:
    """Validate row-local schema, date, unit, and numeric invariants."""

    issues: List[QualityIssue] = []
    for field_name in STRICT_COLUMNS:
        if field_name not in record or _is_blank(record.get(field_name)):
            issues.append(_issue("provenance_missing" if field_name in {
                "source_id", "source_url", "snapshot_id", "snapshot_hash", "snapshot_captured_at",
                "source_period_from", "source_period_to", "parser_version", "verified_on",
                "rights_confirmed", "amount_unit", "currency",
            } else "schema_missing_field", f"required field is missing: {field_name}", row_number, field=field_name))
    record_date = _parse_date(record.get("record_date"))
    if record_date is None:
        issues.append(_issue("invalid_record_date", "record_date must be YYYY-MM-DD", row_number))
    verified_on = _parse_date(record.get("verified_on"))
    if verified_on is None:
        issues.append(_issue("invalid_verified_on", "verified_on must be YYYY-MM-DD", row_number))
    if _parse_datetime(record.get("snapshot_captured_at")) is None:
        issues.append(_issue("invalid_snapshot_captured_at", "snapshot_captured_at must be ISO-8601 with timezone", row_number))
    period_from = _parse_date(record.get("source_period_from"))
    period_to = _parse_date(record.get("source_period_to"))
    if period_from is None or period_to is None:
        issues.append(_issue("invalid_source_period", "source period must contain valid dates", row_number))
    elif period_to < period_from:
        issues.append(_issue("invalid_source_period", "source_period_to cannot precede source_period_from", row_number))
    area = _parse_decimal(record.get("area_sqm"))
    amount = _parse_decimal(record.get("amount_yen"))
    if area is None or not area.is_finite():
        issues.append(_issue("invalid_area", "area_sqm must be numeric", row_number))
    elif area <= 0:
        issues.append(_issue("impossible_value", "area_sqm must be greater than zero", row_number, field="area_sqm"))
    if amount is None or not amount.is_finite():
        issues.append(_issue("invalid_amount", "amount_yen must be numeric", row_number))
    elif amount <= 0:
        issues.append(_issue("impossible_value", "amount_yen must be greater than zero", row_number, field="amount_yen"))
    if area is not None and area.is_finite() and area > Decimal("1000"):
        issues.append(_issue("suspicious_value", "area_sqm exceeds 1000㎡; manual review required", row_number, severity="warning", field="area_sqm"))
    if amount is not None and amount.is_finite() and amount > Decimal("1000000000000"):
        issues.append(_issue("suspicious_value", "amount_yen exceeds 1 trillion JPY; manual review required", row_number, severity="warning", field="amount_yen"))
    if record.get("market") not in ALLOWED_MARKETS:
        issues.append(_issue("invalid_market", "market must be sale or rental", row_number))
    if record.get("status") not in ALLOWED_STATUSES:
        issues.append(_issue("invalid_status", "status must be listing or closed", row_number))
    if record.get("data_class") not in ALLOWED_DATA_CLASSES:
        issues.append(_issue("invalid_data_class", "data_class is not supported", row_number))
    expected_unit = {"sale": "jpy_total", "rental": "jpy_monthly"}.get(record.get("market"))
    if expected_unit and record.get("amount_unit") != expected_unit:
        issues.append(_issue("unit_market_mismatch", f"{record.get('market')} requires amount_unit={expected_unit}", row_number))
    if record.get("currency") != "JPY":
        issues.append(_issue("invalid_currency", "currency must be JPY", row_number))
    if str(record.get("rights_confirmed", "")).lower() != "yes":
        issues.append(_issue("rights_not_confirmed", "rights_confirmed must be yes", row_number))
    if str(record.get("is_synthetic", "")).lower() not in {"yes", "no"}:
        issues.append(_issue("invalid_synthetic_flag", "is_synthetic must be yes or no", row_number))
    synthetic_flag = str(record.get("is_synthetic", "")).lower()
    data_class = record.get("data_class")
    if (
        (data_class == "synthetic_fixture" and synthetic_flag != "yes")
        or (data_class in {"verified_observation", "scraped_aggregate", "modeled_estimate"} and synthetic_flag != "no")
    ):
        issues.append(_issue("synthetic_flag_mismatch", "is_synthetic must match data_class", row_number))
    if not str(record.get("source_url", "")).startswith(("http://", "https://")):
        issues.append(_issue("invalid_source_url", "source_url must be an absolute http(s) URL", row_number))
    snapshot_hash = str(record.get("snapshot_hash", "")).strip().lower()
    if len(snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in snapshot_hash):
        issues.append(_issue("invalid_snapshot_hash", "snapshot_hash must be a SHA-256 hexadecimal digest", row_number))
    return issues


def _url_scope_matches(record_url: str, canonical_url: str) -> bool:
    record_parsed = urlparse(record_url)
    canonical_parsed = urlparse(canonical_url)
    if not (
        record_parsed.scheme in {"http", "https"}
        and canonical_parsed.scheme in {"http", "https"}
        and record_parsed.netloc == canonical_parsed.netloc
    ):
        return False
    canonical_path = canonical_parsed.path.rstrip("/") or "/"
    record_path = record_parsed.path or "/"
    return canonical_path == "/" or record_path == canonical_path or record_path.startswith(canonical_path + "/")


def _group_key(record: Mapping[str, Any], fields: Sequence[str]) -> Tuple[str, ...]:
    return tuple(str(record.get(field_name, "")) for field_name in fields)


def _group_dict(key: Sequence[str], fields: Sequence[str]) -> Dict[str, str]:
    return {field_name: value for field_name, value in zip(fields, key)}


def _record_fingerprint(record: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(
        str(record.get(field_name, "")).strip()
        for field_name in (
            "record_date",
            "market",
            "status",
            "prefecture",
            "ward",
            "building_name",
            "area_sqm",
            "amount_yen",
            "source_id",
        )
    )


def _valid_row_for_metrics(issues: Iterable[QualityIssue]) -> bool:
    return not any(issue.severity == "error" for issue in issues)


def build_monthly_metrics(records: Iterable[Mapping[str, Any]], policy: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Build separate monthly metric rows; model estimates are excluded."""

    trend = policy["trend"]
    group_fields = tuple(trend.get("group_by") or DEFAULT_GROUP_BY)
    grouped: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("data_class") == "modeled_estimate":
            continue
        grouped[_group_key(record, group_fields) + (str(record.get("record_date", ""))[:7],)].append(record)
    metrics: List[Dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        group_key = key[:-1]
        month = key[-1]
        amounts = [_parse_decimal(row.get("amount_yen")) for row in rows]
        ppsm = []
        for row in rows:
            amount = _parse_decimal(row.get("amount_yen"))
            area = _parse_decimal(row.get("area_sqm"))
            if (
                amount is not None
                and amount.is_finite()
                and area is not None
                and area.is_finite()
                and area > 0
            ):
                ppsm.append(amount / area)
        amounts = [value for value in amounts if value is not None and value.is_finite()]
        if not amounts or not ppsm:
            continue
        period_from = sorted(str(row.get("source_period_from", "")) for row in rows)[0]
        period_to = sorted(str(row.get("source_period_to", "")) for row in rows)[-1]
        source_ids = sorted({str(row.get("source_id", "")) for row in rows if str(row.get("source_id", ""))})
        snapshot_ids = sorted({str(row.get("snapshot_id", "")) for row in rows if str(row.get("snapshot_id", ""))})
        snapshot_hashes = sorted({str(row.get("snapshot_hash", "")).lower() for row in rows if str(row.get("snapshot_hash", ""))})
        captured_at = sorted(str(row.get("snapshot_captured_at", "")) for row in rows if str(row.get("snapshot_captured_at", "")))
        metrics.append({
            **_group_dict(group_key, group_fields),
            "month": month,
            "sample_count": len(rows),
            "period_from": period_from,
            "period_to": period_to,
            "source_ids": ";".join(source_ids),
            "snapshot_ids": ";".join(snapshot_ids),
            "snapshot_hashes": ";".join(snapshot_hashes),
            "snapshot_captured_at_from": captured_at[0] if captured_at else "",
            "snapshot_captured_at_to": captured_at[-1] if captured_at else "",
            "median_amount_yen": int(round(median(amounts))),
            "median_price_per_sqm_yen": int(round(median(ppsm))),
            "aggregation_method": "median",
            "missing_value_policy": "exclude_invalid_rows_and_report_error",
            "limitation": "样本仅反映该 group 的授权/fixture 记录，不代表完整市场。",
        })
    return metrics


def quality_check(
    records: Iterable[Mapping[str, Any]],
    registry: Any,
    snapshots: Any,
    policy: Mapping[str, Any],
) -> QualityReport:
    """Return deterministic quality issues and trend eligibility for rows."""

    registry_map = _as_registry(registry)
    snapshot_map = _as_snapshots(snapshots)
    trend = policy.get("trend", {})
    group_fields = tuple(trend.get("group_by") or DEFAULT_GROUP_BY)
    minimum_periods = int(trend.get("minimum_periods", 3))
    minimum_per_period = int(trend.get("minimum_samples_per_period", 5))
    minimum_total = int(trend.get("minimum_total_samples", 15))
    rows = list(records)
    report = QualityReport()
    if not rows:
        report.errors.append(_issue("dataset_empty", "dataset must contain at least one record"))
        return report
    row_issues: Dict[int, List[QualityIssue]] = {}
    seen_ids: Dict[str, int] = {}
    seen_fingerprints: Dict[Tuple[str, ...], int] = {}

    for index, record in enumerate(rows, start=2):
        issues = validate_record(record, index)
        source_id = str(record.get("source_id", "")).strip()
        source = registry_map.get(source_id)
        if source is None:
            issues.append(_issue("source_missing", f"source_id is not registered: {source_id}", index, source_id=source_id))
        else:
            if not _url_scope_matches(str(record.get("source_url", "")), source.canonical_url):
                issues.append(_issue("source_url_mismatch", "record source_url is outside registered source scope", index, source_id=source_id))
            if record.get("data_class") == "synthetic_fixture":
                if source.source_type != "synthetic_fixture" or str(record.get("is_synthetic", "")).lower() != "yes":
                    issues.append(_issue("fixture_label_missing", "synthetic records require a synthetic_fixture source and is_synthetic=yes", index))
            elif record.get("data_class") in {"verified_observation", "scraped_aggregate"}:
                if (
                    source.permission_status != "confirmed"
                    or source.permitted_use == "none"
                    or not source.rights_evidence
                    or not source.terms_reviewed_on
                    or not source.owner
                ):
                    issues.append(_issue("authorization_missing", "non-fixture source lacks confirmed permission evidence and accountable owner", index, source_id=source_id))
            if not source.parser_version:
                issues.append(_issue("source_parser_version_missing", "registered source must declare parser_version", index, source_id=source_id))
            elif source.parser_version != str(record.get("parser_version", "")):
                issues.append(_issue("parser_version_mismatch", "record and registered source parser_version differ", index))
            if record.get("data_class") == "modeled_estimate":
                issues.append(_issue("modeled_estimate_blocked", "modeled_estimate cannot enter factual metrics or publication", index))

        snapshot_id = str(record.get("snapshot_id", "")).strip()
        snapshot = snapshot_map.get(snapshot_id)
        if snapshot is None:
            issues.append(_issue("snapshot_missing", f"snapshot_id is not registered: {snapshot_id}", index, snapshot_id=snapshot_id))
        else:
            manifest_hash = snapshot.content_hash.lower()
            if (
                not snapshot.source_id
                or not snapshot.source_url
                or not snapshot.captured_at
                or not snapshot.content_path
                or len(manifest_hash) != 64
                or any(char not in "0123456789abcdef" for char in manifest_hash)
                or snapshot.byte_size < 0
                or not snapshot.parser_version
            ):
                issues.append(_issue("snapshot_manifest_missing", "snapshot manifest must include source, capture time, path, SHA-256 hash, byte size, and parser_version", index, snapshot_id=snapshot_id))
            if snapshot.source_id != source_id:
                issues.append(_issue("snapshot_source_mismatch", "snapshot source_id does not match record source_id", index))
            if snapshot.parser_version and snapshot.parser_version != str(record.get("parser_version", "")):
                issues.append(_issue("parser_version_mismatch", "record and snapshot parser_version differ", index))
            record_captured_at = _parse_datetime(record.get("snapshot_captured_at"))
            manifest_captured_at = _parse_datetime(snapshot.captured_at)
            if record_captured_at and manifest_captured_at and record_captured_at != manifest_captured_at:
                issues.append(_issue("snapshot_captured_at_mismatch", "record snapshot_captured_at does not match manifest captured_at", index))
            if snapshot.content_path:
                content_path = Path(snapshot.content_path)
                if not content_path.exists():
                    issues.append(_issue("snapshot_content_missing", "snapshot content_path does not exist locally", index))
                else:
                    try:
                        content = content_path.read_bytes()
                    except OSError:
                        issues.append(_issue("snapshot_content_unreadable", "snapshot content_path cannot be read locally", index, snapshot_id=snapshot_id))
                    else:
                        actual_hash = hashlib.sha256(content).hexdigest()
                        if actual_hash != snapshot.content_hash or len(content) != snapshot.byte_size:
                            issues.append(_issue("snapshot_hash_mismatch", "local snapshot bytes do not match manifest hash/byte_size", index, snapshot_id=snapshot_id))
                        if str(record.get("snapshot_hash", "")).lower() != actual_hash:
                            issues.append(_issue("record_snapshot_mismatch", "record snapshot_hash does not match local snapshot bytes", index, snapshot_id=snapshot_id))
            if snapshot.source_url and str(record.get("source_url", "")).strip() != snapshot.source_url:
                issues.append(_issue("snapshot_url_mismatch", "record source_url does not match snapshot source_url", index))

        record_date = _parse_date(record.get("record_date"))
        period_from = _parse_date(record.get("source_period_from"))
        period_to = _parse_date(record.get("source_period_to"))
        if record_date and period_from and period_to and not (period_from <= record_date <= period_to):
            issues.append(_issue("record_outside_source_period", "record_date falls outside the declared source period", index))
        if record.get("record_id"):
            record_id = str(record["record_id"]).strip()
            if record_id in seen_ids:
                issues.append(_issue("duplicate_record_id", "record_id is duplicated", index, first_row=seen_ids[record_id]))
            else:
                seen_ids[record_id] = index
        fingerprint = _record_fingerprint(record)
        if all(fingerprint):
            if fingerprint in seen_fingerprints:
                issues.append(_issue("duplicate_business_record", "business fingerprint is duplicated", index, first_row=seen_fingerprints[fingerprint]))
            else:
                seen_fingerprints[fingerprint] = index

        row_issues[index] = issues
        report.errors.extend(issue for issue in issues if issue.severity == "error")
        report.warnings.extend(issue for issue in issues if issue.severity == "warning")

    eligible_rows = [row for index, row in zip(range(2, len(rows) + 2), rows) if _valid_row_for_metrics(row_issues[index])]
    metrics = build_monthly_metrics(eligible_rows, policy)
    report.groups = metrics

    trend_groups: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        if row.get("data_class") == "modeled_estimate":
            continue
        trend_groups[_group_key(row, group_fields)].append(row)
    for key, grouped_rows in sorted(trend_groups.items()):
        counts = Counter(str(row.get("record_date", ""))[:7] for row in grouped_rows)
        periods = len(counts)
        total_samples = len(grouped_rows)
        minimum_samples = min(counts.values()) if counts else 0
        if periods < minimum_periods:
            reason = "trend_insufficient_periods"
        elif minimum_samples < minimum_per_period or total_samples < minimum_total:
            reason = "trend_insufficient_sample"
        else:
            reason = "eligible"
        report.trend_eligibility.append(
            TrendEligibility(
                group=_group_dict(key, group_fields),
                periods=periods,
                total_samples=total_samples,
                minimum_samples_in_period=minimum_samples,
                eligible=reason == "eligible",
                reason=reason,
            )
        )

    trend_by_group = {
        tuple(item.group.get(field_name, "") for field_name in group_fields): item
        for item in report.trend_eligibility
    }
    for metric in report.groups:
        item = trend_by_group.get(tuple(str(metric.get(field_name, "")) for field_name in group_fields))
        metric["trend_eligible"] = bool(item and item.eligible)
        metric["trend_reason"] = item.reason if item else "trend_group_missing"

    classes = {str(row.get("data_class", "")) for row in rows}
    report.publishable = not report.errors
    if "modeled_estimate" in classes:
        report.publishable = False
    if "synthetic_fixture" in classes and classes - {"synthetic_fixture"}:
        report.publishable = False
        report.publication_scope = "blocked_mixed_fixture"
    elif classes and classes <= {"synthetic_fixture"}:
        report.publication_scope = "fixture_only" if report.publishable else "blocked_fixture"
    elif report.publishable:
        report.publication_scope = "factual_aggregate"
    else:
        report.publication_scope = "blocked"
    return report


def read_strict_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = set(STRICT_COLUMNS) - columns
        if missing:
            raise ValueError("strict CSV missing required fields: " + ", ".join(sorted(missing)))
        rows = []
        for record in reader:
            rows.append({key: (value or "").strip() for key, value in record.items()})
        return rows


def prepare_records(records: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    for record in records:
        item = dict(record)
        amount = _parse_decimal(item.get("amount_yen"))
        area = _parse_decimal(item.get("area_sqm"))
        item["month"] = str(item.get("record_date", ""))[:7]
        if (
            amount is not None
            and amount.is_finite()
            and area is not None
            and area.is_finite()
            and area > 0
        ):
            item["price_per_sqm_yen"] = str(int(round(amount / area)))
        else:
            item["price_per_sqm_yen"] = ""
        prepared.append(item)
    return prepared


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Optional[Sequence[str]] = None) -> None:
    if not rows and not fieldnames:
        raise ValueError("cannot write an empty CSV")
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames or rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
