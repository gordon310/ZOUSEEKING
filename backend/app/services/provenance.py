"""Source, snapshot, and evidence records used to make reports auditable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlparse


ALLOWED_PERMISSION_STATUSES = {"verified", "user_submitted", "pending", "denied", "unverified"}

# The only authoritative vocabulary and response contract for published
# property statistics. Other modules import this instead of declaring variants.
DATA_CLASSES = frozenset({
    "verified_observation", "scraped_aggregate", "modeled_estimate", "synthetic_fixture",
})
REQUIRED_STATISTIC_FIELDS = (
    "data_class", "source_url", "retrieved_at", "source_period",
    "transformation_version", "rights_status", "rights_confirmed",
    "sample_size", "aggregation_method", "missing_value_policy",
    "limitations", "unit",
)


def assert_statistic_provenance(response: dict[str, object]) -> None:
    """Raise a precise development/test error when a published metric is incomplete."""

    missing = [field for field in REQUIRED_STATISTIC_FIELDS if response.get(field) in (None, "", [], {})]
    if response.get("data_class") not in DATA_CLASSES and "data_class" not in missing:
        raise ValueError(f"provenance contract invalid data_class: {response.get('data_class')!r}")
    if missing:
        raise ValueError("provenance contract missing: " + ", ".join(missing))
    if response["rights_confirmed"] not in {"yes", "no", "not_applicable"}:
        raise ValueError("provenance contract invalid rights_confirmed")


def statistic_provenance(
    *, data_class: str, source_url: str, retrieved_at: object, source_period: str,
    transformation_version: str, rights_status: str, rights_confirmed: str,
    sample_size: int, aggregation_method: str, missing_value_policy: str,
    limitations: str, unit: str,
) -> dict[str, object]:
    """Build and validate the canonical metadata envelope for a metric response."""

    result = {
        "data_class": data_class, "source_url": source_url, "retrieved_at": retrieved_at,
        "source_period": source_period, "transformation_version": transformation_version,
        "rights_status": rights_status, "rights_confirmed": rights_confirmed,
        "sample_size": sample_size, "aggregation_method": aggregation_method,
        "missing_value_policy": missing_value_policy, "limitations": limitations, "unit": unit,
    }
    assert_statistic_provenance(result)
    return result


@dataclass(frozen=True)
class Source:
    name: str
    source_type: str
    url: str
    permission_status: str
    update_frequency: str = "manual"
    parser_version: str = "unparsed"


@dataclass(frozen=True)
class Snapshot:
    source_url: str
    fetched_at: datetime
    content_hash: str
    byte_size: int
    parser_version: str
    http_status: int | None = None


@dataclass(frozen=True)
class Evidence:
    property_id: str
    field_name: str
    source_url: str
    snapshot_hash: str
    locator: str
    extraction_method: str
    observed_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def register_source(
    name: str,
    source_type: str,
    url: str,
    permission_status: str,
    update_frequency: str = "manual",
    parser_version: str = "unparsed",
) -> Source:
    """Validate and create a source record; persistence is handled by the caller."""

    if not name.strip() or not source_type.strip():
        raise ValueError("source name and source type are required")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must be an absolute http(s) URL")
    if permission_status not in ALLOWED_PERMISSION_STATUSES:
        raise ValueError(f"unsupported permission status: {permission_status}")
    return Source(
        name=name.strip(),
        source_type=source_type.strip(),
        url=url.strip(),
        permission_status=permission_status,
        update_frequency=update_frequency.strip() or "manual",
        parser_version=parser_version.strip() or "unparsed",
    )


def save_snapshot(
    source_url: str,
    content: bytes,
    parser_version: str,
    http_status: int | None = None,
    fetched_at: datetime | None = None,
) -> Snapshot:
    """Build an immutable snapshot record from bytes without retaining raw content."""

    if not content:
        raise ValueError("snapshot content must not be empty")
    if not parser_version.strip():
        raise ValueError("parser version is required")
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("snapshot source URL must be an absolute http(s) URL")
    return Snapshot(
        source_url=source_url.strip(),
        fetched_at=fetched_at or _utc_now(),
        content_hash=sha256(content).hexdigest(),
        byte_size=len(content),
        parser_version=parser_version.strip(),
        http_status=http_status,
    )


def attach_evidence(
    property_id: str,
    field_name: str,
    source_url: str,
    snapshot_hash: str,
    locator: str = "",
    extraction_method: str = "manual",
    observed_at: datetime | None = None,
) -> Evidence:
    """Build a field-level evidence record; callers persist it with the property."""

    if not property_id.strip() or not field_name.strip():
        raise ValueError("property id and field name are required")
    if len(snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in snapshot_hash.lower()):
        raise ValueError("snapshot hash must be a SHA-256 hexadecimal digest")
    if not source_url.strip():
        raise ValueError("evidence source URL is required")
    return Evidence(
        property_id=property_id.strip(),
        field_name=field_name.strip(),
        source_url=source_url.strip(),
        snapshot_hash=snapshot_hash.lower(),
        locator=locator.strip(),
        extraction_method=extraction_method.strip() or "manual",
        observed_at=observed_at or _utc_now(),
    )
