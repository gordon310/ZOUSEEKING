from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*"
            r"[A-Za-z0-9+/=\r\n]{32,}"
            r"\s*-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
        ),
    ),
    ("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("stripe", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    ("slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("openai", re.compile(r"\bsk-[A-Za-z0-9]{24,}\b")),
)


def scan_text(text: str, path: str) -> list[dict[str, int | str]]:
    """Return redacted high-confidence findings from one text file."""

    findings: list[dict[str, int | str]] = []
    for kind, pattern in _PATTERNS:
        seen_lines: set[int] = set()
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if line in seen_lines:
                continue
            seen_lines.add(line)
            findings.append({"kind": kind, "path": path, "line": line})
    return sorted(findings, key=lambda item: (str(item["path"]), int(item["line"]), str(item["kind"])))


def _repository_paths(repo: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-c", "-o", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
        shell=False,
    )
    return [repo / item for item in completed.stdout.decode("utf-8").split("\0") if item]


def scan_repository(repo: Path) -> list[dict[str, int | str]]:
    findings: list[dict[str, int | str]] = []
    for path in _repository_paths(repo):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            continue
        findings.extend(scan_text(raw.decode("utf-8", errors="replace"), str(path.relative_to(repo))))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan repository text files for high-confidence secrets.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        findings = scan_repository(args.repo.resolve())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"secret scan blocked: {type(exc).__name__}", file=sys.stderr)
        return 2
    if findings:
        for finding in findings:
            print(
                f"secret finding: {finding['kind']} at {finding['path']}:{finding['line']}",
                file=sys.stderr,
            )
        return 1
    print("secret scan: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
