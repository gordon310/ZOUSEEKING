#!/usr/bin/env python3
"""Apply the single release version to static asset references in web/*.html."""

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "deploy" / "frontend-version.txt"
ASSET_RE = re.compile(r'((?:src|href)=["\'])([^"\']+)(["\'])')


def read_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError(f"invalid frontend version: {version!r}")
    return version


def is_versioned_asset(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return (
        path.startswith("js/")
        or path.startswith("assets/")
        or path == "config.js"
        or path.endswith(".css")
        or path == "manifest.webmanifest"
    )


def replace_url(url: str, version: str) -> str:
    if not is_versioned_asset(url) or url.startswith(("/", "//", "http:", "https:")):
        return url
    path = url.split("?", 1)[0].split("#", 1)[0]
    return f"{path}?v={version}"


def rewrite(text: str, version: str) -> str:
    return ASSET_RE.sub(lambda match: f"{match.group(1)}{replace_url(match.group(2), version)}{match.group(3)}", text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when HTML is not normalized")
    args = parser.parse_args()

    version = read_version()
    changed: list[Path] = []
    for path in sorted((ROOT / "web").glob("*.html")):
        original = path.read_text(encoding="utf-8")
        updated = rewrite(original, version)
        if updated != original:
            changed.append(path)
            if not args.check:
                path.write_text(updated, encoding="utf-8")

    if args.check and changed:
        print("frontend asset references need normalization:")
        for path in changed:
            print(f"- {path.relative_to(ROOT)}")
        return 1
    print(f"frontend asset version {version}: {len(changed)} HTML file(s) {'would change' if args.check else 'updated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
