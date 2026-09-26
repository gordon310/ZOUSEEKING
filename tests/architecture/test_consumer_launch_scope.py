from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app import release_scope


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "docs/architecture/consumer-launch-boundaries.json"
ADMIN_SOURCE_FILES = (
    ROOT / "web-source/js/admin-api-client.js",
    ROOT / "web-source/js/admin.js",
    ROOT / "web-source/js/admin-views.js",
)


# Derived from docs/architecture/consumer-launch-page-api-dependency.md table 2.
C_REACHABLE_API_CONTRACT = (
    "POST /api/intake/sessions",
    "POST /api/intake/sessions/{session_id}/inputs",
    "POST /api/intake/sessions/{session_id}/files",
    "PUT /api/intake/sessions/{session_id}/location",
    "PUT /api/intake/sessions/{session_id}/fields/{field_name}",
    "POST /api/intake/sessions/{session_id}/preview",
    "POST /api/intake/sessions/{session_id}/convert",
    "POST /api/recognition",
    "GET /api/my/queries",
    "POST /api/account/deletion-request",
    "POST /api/query",
    "GET /api/jobs/{job_id}",
    "GET /api/reports/{query_key}",
    "GET /api/reports/{query_key}/download",
    "GET /api/billing/prices",
    "POST /api/billing/checkout",
    "POST /api/auth/invite-register",
    "GET /api/me",
)


@pytest.fixture(autouse=True)
def consumer_launch_phase(monkeypatch):
    monkeypatch.setenv("RELEASE_PHASE", release_scope.CONSUMER_LAUNCH)


def test_consumer_launch_manifest_matches_runtime_allowlist() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    assert policy["decision_id"] == "ADR-0002"
    assert policy["status"] == "accepted"
    assert policy["release_phase"] == release_scope.CONSUMER_LAUNCH
    assert policy["api_allowlist"] == list(release_scope.CONSUMER_LAUNCH_API_CONTRACT)


def test_every_consumer_reachable_api_is_in_consumer_launch_contract() -> None:
    for endpoint in C_REACHABLE_API_CONTRACT:
        assert endpoint in release_scope.CONSUMER_LAUNCH_API_CONTRACT


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)([A-Z])", r"_\1", value).lower()


def _admin_api_calls_from_source() -> set[str]:
    calls: set[str] = set()
    request_pattern = re.compile(
        r'request\(\s*(?:"(?P<quoted>/api/[^"]+)"|`(?P<template>/api/[^`]+)`)'
        r"(?P<options>.*?)\)\s*;",
        re.DOTALL,
    )
    placeholder_pattern = re.compile(r"\$\{encodeURIComponent\((?P<name>[A-Za-z_][A-Za-z0-9_]*)\)\}")

    for source_path in ADMIN_SOURCE_FILES:
        source = source_path.read_text(encoding="utf-8")
        for match in request_pattern.finditer(source):
            path = match.group("quoted") or match.group("template")
            path = placeholder_pattern.sub(
                lambda placeholder: "{" + _camel_to_snake(placeholder.group("name")) + "}",
                path,
            )
            method_match = re.search(
                r'method\s*:\s*["\'](?P<method>[A-Z]+)["\']',
                match.group("options"),
            )
            method = method_match.group("method") if method_match else "GET"
            calls.add(f"{method} {path}")
    return calls


def test_every_admin_source_api_is_in_consumer_launch_contract() -> None:
    assert _admin_api_calls_from_source() <= set(release_scope.CONSUMER_LAUNCH_API_CONTRACT)


def test_every_legacy_admin_baseline_api_is_in_consumer_launch_contract() -> None:
    baseline_admin_apis = {
        endpoint
        for endpoint in release_scope.ADMIN_API_CONTRACT
        if endpoint.split(" ", 1)[1].startswith("/api/admin/")
    }
    assert baseline_admin_apis <= set(release_scope.CONSUMER_LAUNCH_API_CONTRACT)


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/admin/overview"),
        ("GET", "/api/admin/pricing"),
        ("GET", "/api/admin/invite-codes"),
        ("POST", "/api/admin/members/user-123/audience"),
        ("GET", "/api/admin/service/tasks"),
    ),
)
def test_consumer_launch_allows_admin_key_path(method: str, path: str) -> None:
    assert release_scope.request_allowed(method, path)


def test_consumer_launch_blocks_region_stats() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/region-stats")


def test_consumer_launch_blocks_region_stats_trend() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/region-stats/trend")


def test_consumer_launch_blocks_organization_me() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/me")


def test_consumer_launch_blocks_organization_usage() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/usage")


def test_consumer_launch_blocks_organization_billing() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/billing")


def test_consumer_launch_blocks_organization_members() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/members")


def test_consumer_launch_blocks_organization_exports_list() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/exports")


def test_consumer_launch_blocks_organization_exports_create() -> None:
    assert not release_scope.request_allowed("POST", "/api/org/exports")


def test_consumer_launch_blocks_organization_exports_download() -> None:
    assert not release_scope.request_allowed("GET", "/api/org/exports/export-123")


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/api/analysis"),
        ("POST", "/api/jobs/query-123/run"),
        ("POST", "/api/org/invitations"),
        ("GET", "/api/org/invitations"),
        ("POST", "/api/org/invitations/invitation-123/revoke"),
        ("POST", "/api/org/invitations/accept"),
        ("GET", "/api/org/service-tasks"),
        ("POST", "/api/org/service-tasks/task-123/apply"),
        ("POST", "/api/org/service-tasks/task-123/withdraw"),
        ("POST", "/api/org/service-tasks/task-123/consent"),
        ("POST", "/api/org/service-tasks/task-123/complete"),
        ("GET", "/api/service/tasks"),
        ("POST", "/api/service/tasks/task-123/consent"),
        ("POST", "/api/service/tasks/task-123/confirm-completion"),
        ("GET", "/api/exports"),
        ("POST", "/api/exports"),
        ("GET", "/api/exports/export-123"),
    ),
)
def test_consumer_launch_blocks_each_remaining_pure_business_api(method: str, path: str) -> None:
    assert not release_scope.request_allowed(method, path)


def test_consumer_launch_allows_registration() -> None:
    assert release_scope.request_allowed("POST", "/api/auth/invite-register")


def test_consumer_launch_allows_query() -> None:
    assert release_scope.request_allowed("POST", "/api/query")


def test_consumer_launch_allows_my_queries() -> None:
    assert release_scope.request_allowed("GET", "/api/my/queries")


def test_consumer_launch_allows_report() -> None:
    assert release_scope.request_allowed("GET", "/api/reports/query-123")


def test_consumer_launch_allows_report_download() -> None:
    assert release_scope.request_allowed("GET", "/api/reports/query-123/download")


def test_consumer_launch_allows_billing_checkout() -> None:
    assert release_scope.request_allowed("POST", "/api/billing/checkout")


def test_consumer_launch_allows_billing_webhook() -> None:
    assert release_scope.request_allowed("POST", "/api/billing/webhook")


def test_consumer_launch_allows_me() -> None:
    assert release_scope.request_allowed("GET", "/api/me")


def test_consumer_intake_preview_sample_is_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("RELEASE_PHASE", release_scope.PHASE_ONE)

    assert release_scope.request_allowed("POST", "/api/intake/sessions")
    assert not release_scope.request_allowed("POST", "/api/query")


def test_consumer_active_sample_is_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("RELEASE_PHASE", release_scope.CONSUMER_ACTIVE)

    assert release_scope.request_allowed("GET", "/api/org/region-stats")
    assert release_scope.request_allowed("POST", "/api/query")
