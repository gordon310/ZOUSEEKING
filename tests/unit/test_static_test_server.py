from __future__ import annotations

import json
from pathlib import Path

from scripts.ci.static_test_server import load_content_library


ROOT = Path(__file__).resolve().parents[2]


def test_load_content_library_reads_canonical_fixture_without_writing_web_output() -> None:
    canonical = ROOT / "data/content_library.json"
    web_library = ROOT / "web/content-library.json"
    before = web_library.read_bytes()

    payload = load_content_library(canonical)

    assert isinstance(json.loads(payload), list)
    assert web_library.read_bytes() == before


def test_load_content_library_rejects_non_array_payload(tmp_path: Path) -> None:
    fixture = tmp_path / "invalid.json"
    fixture.write_text("{}", encoding="utf-8")

    try:
        load_content_library(fixture)
    except ValueError as exc:
        assert "array" in str(exc)
    else:
        raise AssertionError("invalid content-library payload was accepted")
