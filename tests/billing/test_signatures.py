from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest

from backend.app.billing.signatures import SignatureVerificationError, construct_event


SECRET = "whsec_test_secret"
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def sign(raw_body: bytes, timestamp: int, secret: str = SECRET) -> str:
    signed = str(timestamp).encode("ascii") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def event_body() -> bytes:
    return json.dumps(
        {
            "id": "evt_test_invoice_paid",
            "object": "event",
            "type": "invoice.paid",
            "created": int(NOW.timestamp()),
            "data": {
                "object": {
                    "id": "in_test_123",
                    "object": "invoice",
                    "customer": "cus_test_123",
                    "description": "续费 ✅",
                }
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_construct_event_verifies_exact_raw_utf8_bytes_before_parsing() -> None:
    raw_body = event_body()
    header = sign(raw_body, int(NOW.timestamp()))

    event = construct_event(raw_body, header, SECRET, now=NOW)

    assert event.event_id == "evt_test_invoice_paid"
    assert event.event_type == "invoice.paid"
    assert event.payload["data"]["object"]["description"] == "续费 ✅"


def test_construct_event_rejects_a_one_byte_body_change() -> None:
    raw_body = event_body()
    header = sign(raw_body, int(NOW.timestamp()))

    with pytest.raises(SignatureVerificationError):
        construct_event(raw_body + b" ", header, SECRET, now=NOW)


def test_construct_event_rejects_stale_timestamp_and_malformed_header() -> None:
    raw_body = event_body()
    stale_timestamp = int(NOW.timestamp()) - 301

    with pytest.raises(SignatureVerificationError):
        construct_event(raw_body, sign(raw_body, stale_timestamp), SECRET, now=NOW)
    with pytest.raises(SignatureVerificationError):
        construct_event(raw_body, "v1=not-a-valid-header", SECRET, now=NOW)


def test_construct_event_accepts_one_of_multiple_v1_signatures() -> None:
    raw_body = event_body()
    timestamp = int(NOW.timestamp())
    valid = sign(raw_body, timestamp).split("v1=", 1)[1]

    event = construct_event(
        raw_body,
        f"t={timestamp},v0=ignored,v1=wrong,v1={valid}",
        SECRET,
        now=NOW,
    )

    assert event.event_id == "evt_test_invoice_paid"


def test_construct_event_rejects_signed_invalid_json_without_leaking_payload() -> None:
    raw_body = b"{not-json}"
    header = sign(raw_body, int(NOW.timestamp()))

    with pytest.raises(SignatureVerificationError) as error:
        construct_event(raw_body, header, SECRET, now=NOW)

    assert "not-json" not in str(error.value)
    assert SECRET not in str(error.value)
