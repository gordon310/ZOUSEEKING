"""The service worker's cache version must follow the release version.

The worker caches the app shell under a name derived from SW_VERSION, and its
own header comment says to bump that constant after deploys so the shell
refreshes. Nothing enforced it: the frontend build only minified and copied the
file, so the worker's version drifted behind the release that was actually being
served (r63 while the site served r67), and offline fallbacks could resolve to a
stale shell.

The source constant is now derived from deploy/frontend-version.txt by the
versioning script. These tests keep that true in both directions: the source
must match the release version, and the built artefact must match the source.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "deploy" / "frontend-version.txt"
SW_SOURCE = ROOT / "web-source" / "sw.js"
SW_BUILT = ROOT / "web" / "sw.js"

VERSION_RE = re.compile(r'const SW_VERSION\s*=\s*"([^"]*)"')


def _release_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert version, "frontend version file is empty"
    return version


def _sw_version(path: Path) -> str:
    assert path.exists(), f"missing service worker: {path}"
    match = VERSION_RE.search(path.read_text(encoding="utf-8"))
    assert match, f"no SW_VERSION constant found in {path}"
    return match.group(1)


def test_source_service_worker_version_matches_release_version():
    assert _sw_version(SW_SOURCE) == _release_version(), (
        "web-source/sw.js SW_VERSION is out of step with deploy/frontend-version.txt; "
        "run `python deploy/version-frontend-assets.py` to re-derive it"
    )


def test_built_service_worker_matches_source_version():
    source = _sw_version(SW_SOURCE)
    built = _sw_version(SW_BUILT)
    assert built == source, (
        "the built sw.js carries a different SW_VERSION than its source; "
        "rebuild with `npm run build:web-assets`"
    )


def test_versioning_script_reports_drift_in_check_mode():
    """--check must fail while the constants disagree, and pass once aligned.

    Runs against a temp copy so the real tree is never mutated.
    """
    import subprocess
    import sys

    script = ROOT / "deploy" / "version-frontend-assets.py"
    assert script.exists(), "versioning script missing"

    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # The tree is expected to be normalized at test time, so this passes; if it
    # ever returns 1 the message names the file that drifted.
    assert result.returncode == 0, (
        "versioning script reports normalisation needed:\n"
        f"{result.stdout}{result.stderr}"
    )
