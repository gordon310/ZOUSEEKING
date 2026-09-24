"""Staging-only synthetic smoke carrier for the phase-one release candidate.

The default ``--plan`` mode is deliberately local-only: it reads the checked
out commit and frontend-version file but never constructs a HTTP client or a
socket.  ``--execute`` is deliberately gated because it creates and then
removes small synthetic intake records in the exact staging allowlist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

import httpx


STAGING_PROJECT_REF = "fnogxuytbabxmqousifh"
ALLOWED_HOSTS = frozenset(
    {
        "zouseeking-api-staging.onrender.com",
        "zouseeking-web-staging.onrender.com",
        "fnogxuytbabxmqousifh.supabase.co",
    }
)
PRODUCTION_HOSTS = frozenset(
    {
        "zoubeacon.app",
        "www.zoubeacon.app",
        "zoubeacon.com",
        "www.zoubeacon.com",
        "platform.zoubeacon.com",
        "api.zoubeacon.com",
    }
)
DEFAULT_API_URL = "https://zouseeking-api-staging.onrender.com"
DEFAULT_WEB_URL = "https://zouseeking-web-staging.onrender.com"
CASE_IDS = (
    "text_input",
    "url_input",
    "pdf_upload",
    "jpg_upload",
    "png_upload",
    "location_denied",
    "geocoder_failure",
    "expiry_cleanup",
    "cross_user_denied",
    "idempotent_preview",
)
SENSITIVE_KEYS = frozenset(
    {
        "access_token", "refresh_token", "token", "apikey", "api_key",
        "authorization", "cookie", "password", "secret", "service_role", "anon",
    }
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}")
HEX_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class Config:
    project_ref: str
    api_url: str
    web_url: str
    candidate_commit: str
    frontend_version: str
    evidence_out: Path | None
    browser_evidence: Path | None = None


class Transport(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> "Response": ...

    def cleanup(self, session_id: str, object_paths: list[str]) -> dict[str, Any]: ...


@dataclass
class Response:
    status_code: int
    payload: Any = None
    text: str = ""


class HttpxTransport:
    """The only live transport; it is instantiated only after execute gating."""

    def __init__(self, api_url: str, anon_key: str, owner_token: str, other_token: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.anon_key = anon_key
        self.owner_token = owner_token
        self.other_token = other_token

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        identity = kwargs.pop("identity", "owner")
        bearer = self.owner_token if identity == "owner" else self.other_token
        headers = dict(kwargs.pop("headers", {}))
        headers.update({"apikey": self.anon_key, "Authorization": f"Bearer {bearer}"})
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            result = client.request(method, url, headers=headers, **kwargs)
        try:
            payload = result.json()
        except ValueError:
            payload = {}
        return Response(result.status_code, payload, result.text)

    def cleanup(self, session_id: str, object_paths: list[str]) -> dict[str, Any]:
        # The current API may not expose these staging cleanup routes.  Every
        # object/session is nevertheless addressed explicitly, then read back;
        # unsupported routes therefore become honest failed verification rather
        # than a claim that staging data was removed.
        object_responses = [
            self.request("DELETE", f"{self.api_url}/api/intake/sessions/{session_id}/files/{path}")
            for path in object_paths
        ]
        self.request("DELETE", f"{self.api_url}/api/intake/sessions/{session_id}")
        session_readback = self.request("GET", f"{self.api_url}/api/intake/sessions/{session_id}")
        objects_remaining = sum(response.status_code != 404 for response in object_responses)
        sessions_remaining = 0 if session_readback.status_code == 404 else 1
        return {
            "attempted": True,
            "objects_remaining": objects_remaining,
            "sessions_remaining": sessions_remaining,
            "verified": objects_remaining == 0 and sessions_remaining == 0,
        }


class FakeTransport:
    """A deterministic, zero-socket transport for self-check and unit tests."""

    def __init__(self, frontend_version: str = "", *, fail_case: str | None = None, objects_remaining: int = 0) -> None:
        self.frontend_version = frontend_version
        self.fail_case = fail_case
        self.objects_remaining = objects_remaining
        self.cleanup_called = False
        self.preview_count = 0

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        marker = str(kwargs.get("json", {}).get("case", "") or kwargs.get("headers", {}).get("X-Synthetic-Case", ""))
        if url.endswith("/index.html"):
            return Response(200, {}, f'<script src="/app.js?v={self.frontend_version}"></script>')
        if marker == self.fail_case:
            return Response(500, {"error": "synthetic failure"})
        if url.endswith("/sessions") and method == "POST":
            return Response(201, {"session_id": "synthetic-session"})
        if url.endswith("/preview"):
            self.preview_count += 1
            return Response(200, {
                "completeness": {"identity": {"status": "insufficient_data"}},
                "acquisition_costs": {"status": "insufficient_input"},
                "risk_summary": {},
                "comparable_status": "not_checked",
                "comparable": {"status": "not_checked", "note": "", "reference": []},
                "calculation_version": "free-preview-v1",
                "preview_id": "same-preview",
            })
        if marker == "cross_user_denied":
            return Response(403, {"detail": "denied"})
        return Response(201 if method == "POST" else 200, {"ok": True})

    def cleanup(self, session_id: str, object_paths: list[str]) -> dict[str, Any]:
        self.cleanup_called = True
        return {
            "attempted": True,
            "objects_remaining": self.objects_remaining,
            "sessions_remaining": 0,
            "verified": self.objects_remaining == 0,
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _head_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_repo_root(), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError("unable to determine candidate commit from repository HEAD")
    return result.stdout.strip()


def _validate_commit(commit: str) -> str:
    if not HEX_COMMIT_RE.fullmatch(commit):
        raise ValueError("candidate commit must be a 40-character hexadecimal SHA")
    result = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=_repo_root(), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError("candidate commit does not name a local commit")
    return commit.lower()


def _validate_url(label: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{label} must be an https URL")
    host = parsed.hostname.lower()
    if host in PRODUCTION_HOSTS:
        raise ValueError(f"{label} production host is explicitly forbidden")
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"{label} host is not in the staging allowlist")
    return value.rstrip("/")


def default_config() -> Config:
    return Config(
        project_ref=STAGING_PROJECT_REF,
        api_url=DEFAULT_API_URL,
        web_url=DEFAULT_WEB_URL,
        candidate_commit=_validate_commit(_head_commit()),
        frontend_version=(_repo_root() / "deploy" / "frontend-version.txt").read_text(encoding="utf-8").strip(),
        evidence_out=_repo_root() / "docs" / "release" / "phase-one-staging-evidence.json",
    )


def validate_config(config: Config) -> Config:
    if config.project_ref != STAGING_PROJECT_REF:
        raise ValueError("only the exact staging project-ref is allowed")
    return Config(
        project_ref=config.project_ref,
        api_url=_validate_url("api-url", config.api_url),
        web_url=_validate_url("web-url", config.web_url),
        candidate_commit=_validate_commit(config.candidate_commit),
        frontend_version=config.frontend_version.strip(),
        evidence_out=config.evidence_out,
        browser_evidence=config.browser_evidence,
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fixtures() -> dict[str, bytes]:
    return {
        "pdf_upload": b"%PDF-1.4\n% synthetic fixture\n%%EOF\n",
        "jpg_upload": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9",
        "png_upload": b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x00IEND\xaeB`\x82",
    }


def _case(case_id: str, description: str, expected: str, observed: str, status: str, http_status: int | None, payload: bytes) -> dict[str, Any]:
    return {"id": case_id, "description": description, "status": status, "expected": expected, "observed": observed, "http_status": http_status, "payload_sha256": _sha256(payload)}


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            "<redacted_key>" if str(item_key).lower() in SENSITIVE_KEYS else str(item_key): _redact(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str) and ("sb_" in value or JWT_RE.search(value) or EMAIL_RE.search(value) or any(secret in value.lower() for secret in SENSITIVE_KEYS)):
        return "<redacted>"
    return value


def _browser_audit(path: Path | None) -> dict[str, Any]:
    commands = [
        "npx playwright test tests/web/release-scope.spec.js",
        "npx playwright test tests/web/property-intake.spec.js",
        "npx playwright test tests/web/pwa-shell.spec.js",
    ]
    if path is None:
        return {"status": "not_executed", "reason": "browser audit is external to this script", "commands": commands}
    return _redact(json.loads(path.read_text(encoding="utf-8")))


def _preview_is_safe(payload: Any) -> bool:
    return _preview_safety_observed(payload)[0]


def _preview_safety_observed(payload: Any) -> tuple[bool, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return False, {"payload_is_mapping": False}

    data_class_paths: list[str] = []

    def find_data_classes(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                item_path = f"{path}.{key}" if path else str(key)
                if key == "data_class":
                    data_class_paths.append(item_path)
                find_data_classes(item, item_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                find_data_classes(item, f"{path}[{index}]")

    find_data_classes(payload)
    text = json.dumps(payload, ensure_ascii=False).lower()
    completeness = payload.get("completeness")
    completeness_statuses = sorted(
        str(value.get("status"))
        for value in completeness.values()
        if isinstance(completeness, Mapping) and isinstance(value, Mapping) and "status" in value
    ) if isinstance(completeness, Mapping) else []
    acquisition_costs = payload.get("acquisition_costs")
    acquisition_status = acquisition_costs.get("status") if isinstance(acquisition_costs, Mapping) else None
    insufficient_signals = {
        "completeness_statuses": completeness_statuses,
        "acquisition_costs_status": acquisition_status,
        "top_level_status_fields": sorted(
            key for key in ("insufficient_data_status", "data_sufficiency_status") if key in payload
        ),
    }
    has_insufficient_signal = (
        any(status in {"insufficient_data", "partial", "empty"} for status in completeness_statuses)
        or acquisition_status == "insufficient_input"
        or bool(insufficient_signals["top_level_status_fields"])
    )
    comparable_status = payload.get("comparable_status")
    comparable = payload.get("comparable")
    references = comparable.get("reference") if isinstance(comparable, Mapping) else None
    references_are_empty = isinstance(references, list) and not references
    sufficient_references_have_data_class = (
        isinstance(references, list)
        and all(isinstance(reference, Mapping) and bool(reference.get("data_class")) for reference in references)
    )
    forbidden_fields = [field for field in ("tax_total", "full_report", "report_conclusion") if field in text]
    data_class_absent_reason = (
        "preview carries no market reference rows" if not data_class_paths and references_are_empty and "tax_total" not in text else None
    )
    comparable_status_valid = comparable_status in {"not_checked", "insufficient", "sufficient"}
    safe = (
        has_insufficient_signal
        and comparable_status_valid
        and not forbidden_fields
        and (bool(data_class_paths) or data_class_absent_reason is not None)
        and (comparable_status != "sufficient" or sufficient_references_have_data_class)
    )
    return safe, {
        "data_class_paths": data_class_paths,
        "data_class_absent_reason": data_class_absent_reason,
        "insufficient_signals": insufficient_signals,
        "comparable_status": comparable_status,
        "comparable_reference_count": len(references) if isinstance(references, list) else None,
        "sufficient_references_have_data_class": sufficient_references_have_data_class if comparable_status == "sufficient" else None,
        "forbidden_fields": forbidden_fields,
    }


def _deployed_frontend_version(transport: Transport, config: Config) -> bool:
    response = transport.request("GET", f"{config.web_url}/index.html", identity="owner")
    match = re.search(r"[?&]v=([^\"'&\s>]+)", response.text)
    return response.status_code == 200 and match is not None and match.group(1) == config.frontend_version


def run_smoke(config: Config, *, transport: Transport, environment: str) -> dict[str, Any]:
    fixtures = _fixtures()
    cases: list[dict[str, Any]] = []
    object_paths = [f"synthetic-smoke/{name}" for name in fixtures]
    session_id = "not-created"
    cleanup = {"attempted": False, "objects_remaining": None, "sessions_remaining": None, "verified": False}
    limitations: list[str] = []
    frontend_version_match: bool | None = None
    try:
        frontend_version_match = _deployed_frontend_version(transport, config)
        if not frontend_version_match:
            limitations.append("deployed frontend version does not match the candidate frontend version")
        created = transport.request("POST", f"{config.api_url}/api/intake/sessions", json={"purpose": "self_use", "consent_version": "synthetic-v1"})
        session_id = str(created.payload.get("session_id", "not-created")) if isinstance(created.payload, Mapping) else "not-created"
        if created.status_code not in {200, 201}:
            raise RuntimeError("unable to create synthetic session")
        for case_id in CASE_IDS:
            if case_id in fixtures:
                extension = case_id.split("_", 1)[0]
                content_type = {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png"}[extension]
                response = transport.request("POST", f"{config.api_url}/api/intake/sessions/{session_id}/files", headers={"X-Synthetic-Case": case_id}, files={"file": (f"synthetic.{extension}", fixtures[case_id], content_type)})
                cases.append(_case(case_id, "upload a minimal synthetic file", "201", f"HTTP {response.status_code}", "pass" if response.status_code == 201 else "fail", response.status_code, fixtures[case_id]))
            elif case_id in {"text_input", "url_input"}:
                payload = ({"case": case_id, "input_type": "text", "raw_text": "synthetic smoke text only"} if case_id == "text_input" else {"case": case_id, "input_type": "url", "source_url": "https://synthetic-smoke.invalid/value"})
                response = transport.request("POST", f"{config.api_url}/api/intake/sessions/{session_id}/inputs", json=payload)
                cases.append(_case(case_id, "store only synthetic .invalid input", "201", f"HTTP {response.status_code}", "pass" if response.status_code == 201 else "fail", response.status_code, json.dumps(payload).encode()))
            elif case_id == "location_denied":
                payload = {"case": case_id, "input_type": "text", "raw_text": "location permission denied"}
                response = transport.request("POST", f"{config.api_url}/api/intake/sessions/{session_id}/inputs", json=payload)
                cases.append(_case(case_id, "client records denied location without coordinates", "201", f"HTTP {response.status_code}", "pass" if response.status_code == 201 else "fail", response.status_code, json.dumps(payload).encode()))
            elif case_id == "geocoder_failure":
                payload = {"case": case_id, "latitude": 0, "longitude": 0, "accuracy_m": 50, "captured_at": "2026-01-01T00:00:00Z", "consent_version": "synthetic-v1", "source": "device_geolocation"}
                response = transport.request("PUT", f"{config.api_url}/api/intake/sessions/{session_id}/location", json=payload)
                cases.append(_case(case_id, "geocoder failure remains a non-address result", "200", f"HTTP {response.status_code}", "pass" if response.status_code == 200 else "fail", response.status_code, json.dumps(payload).encode()))
            elif case_id == "expiry_cleanup":
                response = transport.request("POST", f"{config.api_url}/api/intake/sessions/{session_id}/inputs", json={"case": case_id, "input_type": "text", "raw_text": "expiry cleanup synthetic marker"})
                cases.append(_case(case_id, "expired synthetic session is eligible for cleanup", "201", f"HTTP {response.status_code}", "pass" if response.status_code == 201 else "fail", response.status_code, case_id.encode()))
            elif case_id == "cross_user_denied":
                response = transport.request("GET", f"{config.api_url}/api/intake/sessions/{session_id}", identity="other", json={"case": case_id})
                cases.append(_case(case_id, "other synthetic user receives 403 or 404", "403 or 404", f"HTTP {response.status_code}", "pass" if response.status_code in {403, 404} else "fail", response.status_code, case_id.encode()))
            else:
                first = transport.request("POST", f"{config.api_url}/api/intake/sessions/{session_id}/preview", json={"case": case_id})
                second = transport.request("POST", f"{config.api_url}/api/intake/sessions/{session_id}/preview", json={"case": case_id})
                first_safe, first_observed = _preview_safety_observed(first.payload)
                second_safe, second_observed = _preview_safety_observed(second.payload)
                safe = first_safe and second_safe
                same = isinstance(first.payload, Mapping) and isinstance(second.payload, Mapping) and first.payload.get("preview_id") == second.payload.get("preview_id")
                observed = json.dumps({"http_statuses": [first.status_code, second.status_code], "first_preview": first_observed, "second_preview": second_observed, "same_preview_id": same}, ensure_ascii=False, sort_keys=True)
                cases.append(_case(case_id, "two previews are safe and idempotent", "same preview without duplicate record", observed, "pass" if safe and same else "fail", second.status_code, case_id.encode()))
    except Exception as exc:
        limitations.append(f"run error: {type(exc).__name__}")
    finally:
        cleanup = transport.cleanup(session_id, object_paths)
        if not cleanup.get("verified"):
            limitations.append("synthetic cleanup verification found residual objects or sessions")
    status = "pass" if frontend_version_match and len(cases) == len(CASE_IDS) and all(case["status"] == "pass" for case in cases) and cleanup.get("verified") else "fail"
    evidence = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": environment,
        "status": status,
        "candidate": {"commit": config.candidate_commit, "frontend_version": config.frontend_version, "frontend_version_match": frontend_version_match},
        "target": {"project_ref": config.project_ref, "api_url": config.api_url, "web_url": config.web_url},
        "cases": cases,
        "storage_cleanup": cleanup,
        "browser_audit": _browser_audit(config.browser_evidence),
        "limitations": limitations,
    }
    return _redact(evidence)


def _print_plan(config: Config) -> None:
    fixtures = _fixtures()
    print("offline synthetic smoke plan")
    print(json.dumps({"target_allowlist": sorted(ALLOWED_HOSTS), "candidate_commit": config.candidate_commit, "frontend_version": config.frontend_version, "synthetic_fields": {"text": "synthetic smoke text only", "url": "https://synthetic-smoke.invalid/value", "email": "synthetic-smoke-0123456789ab@example.invalid", "location_denied": "no coordinates are sent"}, "fixtures": {key: {"bytes": len(value), "sha256": _sha256(value)} for key, value in fixtures.items()}, "endpoints": ["POST /api/intake/sessions", "POST /api/intake/sessions/{id}/inputs", "POST /api/intake/sessions/{id}/files", "PUT /api/intake/sessions/{id}/location", "POST /api/intake/sessions/{id}/preview", "GET /api/intake/sessions/{id}"], "cleanup": ["attempt delete all created synthetic objects", "attempt delete session and dependent rows", "read back remaining object and session counts"], "case_ids": list(CASE_IDS)}, indent=2, ensure_ascii=False))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--self-check", action="store_true")
    parser.add_argument("--allow-staging", action="store_true")
    parser.add_argument("--authorized-writes", action="store_true")
    parser.add_argument("--project-ref", default=STAGING_PROJECT_REF)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--web-url", default=DEFAULT_WEB_URL)
    parser.add_argument("--candidate-commit")
    parser.add_argument("--frontend-version")
    parser.add_argument("--evidence-out")
    parser.add_argument("--browser-evidence")
    return parser


def _write_evidence(path: Path | None, evidence: Mapping[str, Any], *, environment: str) -> None:
    if path is None:
        return
    canonical_path = (_repo_root() / "docs" / "release" / "phase-one-staging-evidence.json").resolve()
    if path.resolve() == canonical_path and environment != "authorized_staging":
        raise ValueError("canonical 证据文件只允许真实 staging 运行写入")
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        defaults = default_config()
        config = validate_config(Config(args.project_ref, args.api_url, args.web_url, args.candidate_commit or defaults.candidate_commit, args.frontend_version or defaults.frontend_version, Path(args.evidence_out) if args.evidence_out else defaults.evidence_out, Path(args.browser_evidence) if args.browser_evidence else None))
        if args.execute:
            if not args.allow_staging:
                raise ValueError("--execute requires --allow-staging; real staging runs require user authorization")
            if not args.authorized_writes:
                raise ValueError("--execute requires --authorized-writes; real staging writes require user authorization")
            required = ("SMOKE_ANON_KEY", "SMOKE_OWNER_TOKEN", "SMOKE_OTHER_TOKEN")
            missing = [name for name in required if not os.environ.get(name)]
            if missing:
                raise ValueError("--execute requires environment variables: " + ", ".join(missing))
            evidence = run_smoke(config, transport=HttpxTransport(config.api_url, os.environ["SMOKE_ANON_KEY"], os.environ["SMOKE_OWNER_TOKEN"], os.environ["SMOKE_OTHER_TOKEN"]), environment="authorized_staging")
            _write_evidence(config.evidence_out, evidence, environment="authorized_staging")
            print(f"execute: {evidence['status']}")
            return 0 if evidence["status"] == "pass" else 1
        if args.self_check:
            evidence = run_smoke(config, transport=FakeTransport(config.frontend_version), environment="offline_self_check")
            if args.evidence_out:
                _write_evidence(config.evidence_out, evidence, environment="offline_self_check")
            print(f"self-check: {evidence['status']}\n" + json.dumps(evidence, indent=2, ensure_ascii=False))
            return 0 if evidence["status"] == "pass" else 1
        _print_plan(config)
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
