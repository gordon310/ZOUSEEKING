"""Source, snapshot, and evidence records used to make reports auditable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlparse


ALLOWED_PERMISSION_STATUSES = {"verified", "user_submitted", "pending", "denied", "unverified"}


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
