"""Offline privacy, consent, retention, and account-governance contracts.

This module deliberately contains no database or Auth Admin calls.  The
production deletion executor is injected at the route boundary only after the
Supabase migration baseline and operational controls have been approved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


UTC = timezone.utc
PRIVACY_POLICY_VERSION = "privacy-2026-08"
TERMS_VERSION = "terms-2026-08"

ACKNOWLEDGEMENT_SLA = timedelta(hours=24)
ACCESS_RESTRICTION_SLA = timedelta(hours=24)
PRIMARY_DATA_DELETION_SLA = timedelta(days=30)
BACKUP_EXPIRY_SLA = timedelta(days=90)


def _as_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _as_utc(value, field_name="timestamp").isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ConsentRecord:
    """A versioned consent evidence record suitable for Auth metadata."""

    privacy_policy_version: str
    terms_version: str
    accepted_at: datetime
    source: str = "registration"

    def __post_init__(self) -> None:
        if not self.privacy_policy_version.strip() or not self.terms_version.strip():
            raise ValueError("consent policy versions are required")
        if not self.source.strip():
            raise ValueError("consent source is required")
        normalized = _as_utc(self.accepted_at, field_name="accepted_at")
        if normalized > datetime.now(UTC):
            raise ValueError("accepted_at cannot be in the future")
        object.__setattr__(self, "accepted_at", normalized)

    def as_auth_metadata(self) -> dict[str, str]:
        return {
            "consent_version": self.privacy_policy_version,
            "consent_at": _iso(self.accepted_at),
            "terms_version": self.terms_version,
            "consent_source": self.source,
        }


def build_consent_record(
    accepted_at: datetime | None = None,
    source: str = "registration",
) -> ConsentRecord:
    """Build evidence using a server/local UTC clock, never client text."""

    timestamp = accepted_at if accepted_at is not None else datetime.now(UTC)
    return ConsentRecord(PRIVACY_POLICY_VERSION, TERMS_VERSION, timestamp, source)


def build_deletion_plan(requested_at: datetime) -> dict[str, str]:
    """Return internal deletion deadlines without mutating an account."""

    requested = _as_utc(requested_at, field_name="requested_at")
    return {
        "requested_at": _iso(requested),
        "acknowledgement_due": _iso(requested + ACKNOWLEDGEMENT_SLA),
        "access_restriction_due": _iso(requested + ACCESS_RESTRICTION_SLA),
        "primary_data_deletion_due": _iso(requested + PRIMARY_DATA_DELETION_SLA),
        "backup_expiry_due": _iso(requested + BACKUP_EXPIRY_SLA),
    }


def privacy_metadata() -> dict[str, Any]:
    """Describe the public governance contract and current offline status."""

    return {
        "privacy_policy_version": PRIVACY_POLICY_VERSION,
        "terms_version": TERMS_VERSION,
        "consent": {
            "required_for_registration": True,
            "accepted_at": "client_generated_utc_submission",
            "timestamp_authority": "untrusted_until_server_capture",
            "metadata_fields": ["consent_version", "consent_at", "terms_version", "consent_source"],
        },
        "authentication": {
            "provider": "supabase_auth",
            "password_reset_endpoint": "/recover",
            "logout_endpoint": "/logout",
            "all_session_revocation": "not_verified",
        },
        "retention_sla": {
            "acknowledgement_hours": 24,
            "access_restriction_hours": 24,
            "primary_data_deletion_days": 30,
            "backup_expiry_days": 90,
        },
        "account_deletion": {
            "endpoint": "/api/account/deletion-request",
            "status": "unavailable_without_trusted_executor",
            "no_side_effect_on_unavailable": True,
        },
        "support": {
            "url": "/support.html",
            "email": "support@zouseeking.example",
            "status": "placeholder_until_operator_confirms_mailbox",
        },
        "migration_baseline_status": "reconciliation_required",
    }


class DeletionServiceUnavailable(RuntimeError):
    """Raised when a trusted account deletion executor is not configured."""
