from datetime import datetime, timezone

import pytest

from backend.app.services.provenance import attach_evidence, register_source, save_snapshot


def test_same_content_has_stable_hash():
    first = save_snapshot("https://example.com/a", b"same", "parser-1")
    second = save_snapshot("https://example.com/a", b"same", "parser-1")
    assert first.content_hash == second.content_hash
    assert first.byte_size == 4


def test_source_requires_http_url_and_permission_status():
    with pytest.raises(ValueError, match="absolute http"):
        register_source("Example", "public", "not-a-url", "verified")
    with pytest.raises(ValueError, match="unsupported permission"):
        register_source("Example", "public", "https://example.com", "allowed")


def test_evidence_requires_sha256_hash_and_field():
    observed_at = datetime(2026, 8, 25, tzinfo=timezone.utc)
    evidence = attach_evidence(
        "property-1",
        "asking_price",
        "https://example.com/a",
        "a" * 64,
        locator="page 2",
        observed_at=observed_at,
    )
    assert evidence.field_name == "asking_price"
    assert evidence.observed_at == observed_at
    with pytest.raises(ValueError, match="SHA-256"):
        attach_evidence("property-1", "asking_price", "https://example.com/a", "bad")
