from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import generate_xhs_package as generator


def test_generator_resolves_a_checked_in_logo_asset() -> None:
    assert generator.LOGO.is_file()
    assert generator.LOGO in generator.LOGO_CANDIDATES
