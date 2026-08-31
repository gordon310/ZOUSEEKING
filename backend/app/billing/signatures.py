"""Raw-body verification for Stripe-compatible webhook signatures."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, List

from .ports import ProviderEvent


class SignatureVerificationError(ValueError):
    """The provider signature or event envelope is invalid."""


def _invalid() -> SignatureVerificationError:
    # Keep provider payloads, secrets and parser details out of public errors.
    return SignatureVerificationError("invalid webhook signature or payload")


def _parse_header(signature_header: str) -> tuple[int, List[str]]:
    timestamp: int | None = None
    signatures: List[str] = []
    if not signature_header:
        raise _invalid()

    for item in signature_header.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator or not key or not value:
            raise _invalid()
        if key == "t":
            if timestamp is not None:
                raise _invalid()
            try:
                timestamp = int(value)
            except ValueError as exc:
                raise _invalid() from exc
        elif key == "v1":
            signatures.append(value)

    if timestamp is None or timestamp <= 0 or not signatures:
        raise _invalid()
    return timestamp, signatures


def construct_event(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    now: datetime,
    tolerance_seconds: int = 300,
) -> ProviderEvent:
    """Verify raw bytes and return the minimum trusted provider event envelope."""

    if not isinstance(payload, bytes) or not secret or tolerance_seconds < 0:
        raise _invalid()
    if now.tzinfo is None:
        raise _invalid()

    timestamp, signatures = _parse_header(signature_header)
    signed_payload = str(timestamp).encode("ascii") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise _invalid()

    now_utc = now.astimezone(timezone.utc)
    if abs(now_utc.timestamp() - timestamp) > tolerance_seconds:
        raise _invalid()

    try:
        decoded: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid() from exc
    if not isinstance(decoded, dict):
        raise _invalid()
    event_id = decoded.get("id")
    event_type = decoded.get("type")
    event_data = decoded.get("data")
    if not isinstance(event_id, str) or not event_id or not isinstance(event_type, str) or not event_type:
        raise _invalid()
    if not isinstance(event_data, dict):
        raise _invalid()

    # Copy the decoded object so callers cannot mutate a shared parser buffer.
    return ProviderEvent(
        event_id=event_id,
        event_type=event_type,
        payload=dict(decoded),
        received_at=now_utc,
    )
