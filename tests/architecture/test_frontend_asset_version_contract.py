"""Guard that frontend source and generated asset imports share one release version."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION_RE = re.compile(r"\?v=([A-Za-z0-9._-]+)")


def _referenced_versions(directory: Path) -> set[str]:
    versions: set[str] = set()
    for path in directory.rglob("*.js"):
        versions.update(VERSION_RE.findall(path.read_text(encoding="utf-8")))
    return versions


def test_frontend_source_and_generated_import_versions_match_release_version() -> None:
    """Prevent source/asset version drift that makes check:web-assets fail."""
    expected_version = (ROOT / "deploy" / "frontend-version.txt").read_text(
        encoding="utf-8"
    ).strip()
    source_versions = _referenced_versions(ROOT / "web-source" / "js")
    generated_versions = _referenced_versions(ROOT / "web" / "js")

    assert source_versions, "web-source/js contains no ?v=<version> references"
    assert generated_versions, "web/js contains no ?v=<version> references"
    assert source_versions == generated_versions
    assert source_versions == {expected_version}
    assert generated_versions == {expected_version}
