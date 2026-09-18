from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import generate_xhs_package as generator


def test_generator_resolves_a_checked_in_logo_asset() -> None:
    assert generator.LOGO.is_file()
    assert generator.LOGO in generator.LOGO_CANDIDATES


def test_validate_library_record_requires_structured_location_and_vocab() -> None:
    record = {
        "title": "新潟县新潟市塔楼，租还是买？",
        "prefecture": "新潟县",
        "city": "新潟市",
        "ward": "未細分",
        "asset_type": "塔楼",
    }

    generator.validate_library_record(record)


def test_validate_library_record_rejects_missing_location() -> None:
    record = {
        "title": "新潟县新潟市塔楼，租还是买？",
        "prefecture": "",
        "city": "",
        "ward": "",
        "asset_type": "塔楼",
    }

    try:
        generator.validate_library_record(record)
    except ValueError as exc:
        assert "prefecture/city/ward" in str(exc)
    else:
        raise AssertionError("missing structured location was accepted")
