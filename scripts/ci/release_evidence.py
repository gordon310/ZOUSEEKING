from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_EXECUTED"}
EXTERNAL_CHECKS = {
    "staging_database": "NOT_EXECUTED",
    "production_database": "NOT_EXECUTED",
    "auth": "NOT_EXECUTED",
    "storage": "NOT_EXECUTED",
    "deployment": "NOT_EXECUTED",
    "dns": "NOT_EXECUTED",
    "billing": "NOT_EXECUTED",
}
DEFAULT_REQUIRED = ["python", "node", "browser", "sql-rls", "supply-chain", "policy"]
ROLLBACK_FALLBACK = """# Rollback / forward-fix checklist

- [ ] Record the candidate release tag, commit and artifact SHA-256.
- [ ] Obtain a schema-only backup and name the restore target before any live change.
- [ ] Confirm the migration ID, approver and stop condition.
- [ ] On failure, stop subsequent steps; do not use `git revert` as a database rollback.
- [ ] Apply an audited forward-fix migration only after disposable reset and SQL/RLS assertions pass.
- [ ] Re-run drift and restore verification before requesting a new release approval.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_reason(reason: str) -> str:
    """Keep result reasons useful without persisting command output or credentials."""

    return re.sub(r"(?i)(token|secret|password|key)\s*[=:]\s*[^\s,;]+", r"\1=[redacted]", reason)[:500]


def _safe_command(command: list[str]) -> list[str]:
    """Avoid persisting inline scripts or likely credential-bearing arguments."""

    safe: list[str] = []
    redact_next = False
    for argument in command:
        if redact_next:
            safe.append("[redacted]")
            redact_next = False
            continue
        if argument in {"-c", "--command", "--eval"}:
            safe.append(argument)
            redact_next = True
            continue
        if re.search(r"(?i)(token|secret|password|private[_-]?key|service[_-]?role)", argument):
            safe.append("[redacted]")
            continue
        argument = re.sub(r"(?i)(://[^/\s:@]+:)[^@\s/]+@", r"\1[redacted]@", argument)
        safe.append(argument if len(argument) <= 256 else "[redacted]")
    return safe


def record_command(name: str, command: list[str], output_path: Path) -> int:
    """Run one check and write a machine-readable status without child output."""

    if not command:
        raise ValueError("command must not be empty")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    status = "PASS"
    exit_code: int | None = 0
    reason = ""
    try:
        completed = subprocess.run(command, check=False, shell=False)
        exit_code = completed.returncode
        if exit_code != 0:
            status = "FAIL"
            reason = f"command exited with status {exit_code}"
    except FileNotFoundError:
        status = "BLOCKED"
        exit_code = None
        reason = f"executable not found: {command[0]}"
    except OSError as exc:
        status = "BLOCKED"
        exit_code = None
        reason = f"unable to start command: {exc.strerror or type(exc).__name__}"

    result = {
        "name": name,
        "status": status,
        "command": _safe_command(command),
        "exit_code": exit_code,
        "duration_seconds": round(time.monotonic() - started, 3),
        "reason": _safe_reason(reason),
        "recorded_at": _now(),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


def record_not_executed(name: str, reason: str, output_path: Path) -> int:
    """Record a deliberate external check omission without implying success."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "name": name,
        "status": "NOT_EXECUTED",
        "command": [],
        "exit_code": None,
        "duration_seconds": 0,
        "reason": _safe_reason(reason),
        "recorded_at": _now(),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def derive_release_tag(version: str, ref_name: str, commit: str) -> str:
    """Return a validated release tag or a deterministic CI candidate tag."""

    version = version.strip()
    ref = (ref_name or "").strip()
    if ref.startswith("refs/tags/"):
        ref = ref[len("refs/tags/") :]
    expected = f"v{version}"
    if ref.startswith("v"):
        if ref != expected:
            raise ValueError(f"release ref {ref!r} does not match project version {version!r}")
        return ref
    commit = (commit or "").strip()
    if len(commit) < 12:
        raise ValueError("commit must contain at least 12 characters for a candidate tag")
    return f"{expected}-ci.{commit[:12]}"


def _read_results(results_dir: Path, required: Iterable[str]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for path in sorted(results_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            payload = {
                "name": path.stem,
                "status": "BLOCKED",
                "command": [],
                "exit_code": None,
                "duration_seconds": 0,
                "reason": f"invalid result file: {type(exc).__name__}",
                "recorded_at": _now(),
            }
        name = str(payload.get("name") or path.stem)
        status = str(payload.get("status") or "BLOCKED").upper()
        if status not in STATUSES:
            status = "BLOCKED"
            payload["reason"] = "unknown check status"
        payload["name"] = name
        payload["status"] = status
        payload["reason"] = _safe_reason(str(payload.get("reason") or ""))
        results[name] = payload
    for name in required:
        if name not in results:
            results[name] = {
                "name": name,
                "status": "BLOCKED",
                "command": [],
                "exit_code": None,
                "duration_seconds": 0,
                "reason": "missing result file",
                "recorded_at": _now(),
            }
    return dict(sorted(results.items()))


def required_checks_pass(results_dir: Path, required: Iterable[str]) -> bool:
    """Return true only when every named result exists and is exactly PASS."""

    results = _read_results(results_dir, required)
    return all(results[name]["status"] == "PASS" for name in required)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            shell=False,
        )
        return Path(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return Path(__file__).resolve().parents[2]


def _write_tarball(output_path: Path, files: list[tuple[Path, str]]) -> None:
    with tarfile.open(output_path, mode="w:gz") as archive:
        for source, arcname in files:
            archive.add(source, arcname=arcname, recursive=False)


def _create_source_archive(output_dir: Path, tag: str, commit: str) -> Path | None:
    safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "-", tag)
    archive_path = output_dir / f"jp-property-publisher-{safe_tag}-{commit[:12]}.tar.gz"
    try:
        subprocess.run(
            [
                "git",
                "archive",
                "--format=tar.gz",
                f"--prefix=JPPropDIs-{safe_tag}/",
                "--output",
                str(archive_path),
                "HEAD",
            ],
            check=True,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        archive_path.unlink(missing_ok=True)
        return None
    return archive_path


def build_evidence(
    results_dir: Path,
    output_dir: Path,
    version: str,
    ref_name: str,
    commit: str,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build evidence files and a candidate archive from recorded check results."""

    required = required or DEFAULT_REQUIRED
    output_dir.mkdir(parents=True, exist_ok=True)
    checks = _read_results(results_dir, required)
    tag = derive_release_tag(version, ref_name, commit)
    offline_gate_passed = all(checks[name]["status"] == "PASS" for name in required)
    artifacts: dict[str, str] = {}
    artifact_sha256: dict[str, str] = {}

    checklist_source = _repo_root() / "docs" / "release" / "rollback-checklist.md"
    checklist_path = output_dir / "rollback-checklist.md"
    if checklist_source.is_file():
        checklist_path.write_text(checklist_source.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        checklist_path.write_text(ROLLBACK_FALLBACK, encoding="utf-8")

    candidate_source = None
    if offline_gate_passed:
        candidate_source = _create_source_archive(output_dir, tag, commit)
        if candidate_source is not None:
            artifacts["candidate_source"] = candidate_source.name
            artifact_sha256["candidate_source"] = _sha256(candidate_source)

    evidence_path = output_dir / f"jp-property-publisher-evidence-{re.sub(r'[^A-Za-z0-9_.-]+', '-', tag)}.tar.gz"
    artifacts["evidence_bundle"] = evidence_path.name

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "version": version,
        "release_tag": tag,
        "commit": commit,
        "recorded_at": _now(),
        "checks": checks,
        "required_checks": required,
        "offline_gate_passed": offline_gate_passed,
        "external_checks": dict(EXTERNAL_CHECKS),
        "release_ready": False,
        "artifacts": artifacts,
        "artifact_sha256": artifact_sha256,
    }
    manifest_path = output_dir / "manifest.json"
    tag_path = output_dir / "release-tag.txt"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tag_path.write_text(f"{tag}\n", encoding="utf-8")

    _write_tarball(
        evidence_path,
        [
            (manifest_path, "manifest.json"),
            (tag_path, "release-tag.txt"),
            (checklist_path, "rollback-checklist.md"),
        ],
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record release checks and build release evidence.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    record = subparsers.add_parser("record", help="run one check and write a JSON result")
    record.add_argument("--name", required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("command", nargs=argparse.REMAINDER)

    not_executed = subparsers.add_parser("not-executed", help="record an explicitly omitted check")
    not_executed.add_argument("--name", required=True)
    not_executed.add_argument("--reason", required=True)
    not_executed.add_argument("--output", type=Path, required=True)

    evidence = subparsers.add_parser("evidence", help="build manifest and release evidence bundle")
    evidence.add_argument("--results-dir", type=Path, required=True)
    evidence.add_argument("--output-dir", type=Path, required=True)
    evidence.add_argument("--version", required=True)
    evidence.add_argument("--ref-name", default=os.getenv("GITHUB_REF_NAME", ""))
    evidence.add_argument("--commit", default=os.getenv("GITHUB_SHA", ""))
    evidence.add_argument("--required", default=",".join(DEFAULT_REQUIRED))

    validate = subparsers.add_parser("validate", help="fail unless every named result is PASS")
    validate.add_argument("--results-dir", type=Path, required=True)
    validate.add_argument("--required", default=",".join(DEFAULT_REQUIRED))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "record":
        command = list(args.command)
        if command and command[0] == "--":
            command = command[1:]
        return record_command(args.name, command, args.output)
    if args.action == "not-executed":
        return record_not_executed(args.name, args.reason, args.output)
    required = [item.strip() for item in args.required.split(",") if item.strip()]
    if args.action == "validate":
        return 0 if required_checks_pass(args.results_dir, required) else 1
    manifest = build_evidence(args.results_dir, args.output_dir, args.version, args.ref_name, args.commit, required)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["offline_gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
