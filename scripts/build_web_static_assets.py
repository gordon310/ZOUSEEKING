#!/usr/bin/env python3
"""Build minified web assets from readable sources without changing their URLs.

Readable JavaScript and CSS live in ``web-source/``. This script writes the
matching production assets below ``web/`` using the exact npm dev dependencies
declared in package.json. Run ``npm ci && python3 scripts/build_web_static_assets.py``.
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "web-source"
WEB_ROOT = ROOT / "web"


def build_commands(*, source: Path, output: Path, kind: str) -> tuple[str, ...]:
    """Return the pinned local-tool command for one readable asset."""

    if kind == "js":
        source_text = source.read_text(encoding="utf-8")
        module_flag = ("--module",) if "import " in source_text or "export " in source_text else ()
        return (
            "npx",
            "--no-install",
            "terser",
            str(source),
            "--compress",
            "--mangle",
            "--format",
            "comments=false",
            *module_flag,
            "--output",
            str(output),
        )
    if kind == "css":
        return (
            "npx",
            "--no-install",
            "lightningcss",
            "--minify",
            str(source),
            "--output-file",
            str(output),
        )
    raise ValueError(f"unsupported asset kind: {kind}")


def asset_pairs() -> list[tuple[Path, Path, str]]:
    pairs: list[tuple[Path, Path, str]] = []
    for source in sorted((SOURCE_ROOT / "js").glob("*.js")):
        pairs.append((source, WEB_ROOT / "js" / source.name, "js"))
    for source in sorted((SOURCE_ROOT / "css").glob("*.css")):
        pairs.append((source, WEB_ROOT / source.name, "css"))
    for name in ("app.js", "sw.js"):
        source = SOURCE_ROOT / name
        if source.exists():
            pairs.append((source, WEB_ROOT / name, "js"))
    return pairs


def build(*, check: bool) -> int:
    pairs = asset_pairs()
    if not pairs:
        raise RuntimeError(f"no readable sources found below {SOURCE_ROOT}")
    stale: list[Path] = []
    for source, output, kind in pairs:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / output.name
            subprocess.run(build_commands(source=source, output=candidate, kind=kind), cwd=ROOT, check=True)
            generated = candidate.read_bytes()
        if not output.exists() or output.read_bytes() != generated:
            stale.append(output)
            if not check:
                output.write_bytes(generated)
    if stale:
        label = "would be updated" if check else "updated"
        print(f"static assets {label}:")
        for output in stale:
            print(f"- {output.relative_to(ROOT)}")
    return 1 if check and stale else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated web assets are stale")
    return build(check=parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
