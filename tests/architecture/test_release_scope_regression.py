from __future__ import annotations

from pathlib import Path

from backend.app import release_scope


def test_consumer_intake_preview_allows_only_its_contract(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RELEASE_PHASE", "consumer_intake_preview")

    for method, path in (
        ("GET", "/health"),
        ("POST", "/api/intake/sessions"),
        ("GET", "/api/admin/members"),
    ):
        assert release_scope.request_allowed(method, path)

    for method, path in (
        ("POST", "/api/auth/invite-register"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/query"),
        ("GET", "/api/my/queries"),
        ("GET", "/api/reports/report-key"),
        ("POST", "/api/billing/checkout"),
        ("GET", "/api/org/region-stats"),
        ("POST", "/api/intake/sessions/session-id/convert"),
        ("POST", "/api/jobs/job-id/run"),
        ("GET", "/api/projects/project-id"),
    ):
        assert not release_scope.request_allowed(method, path)


def test_unknown_phase_fails_closed_except_health_and_diagnostics(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RELEASE_PHASE", "whatever")

    assert release_scope.request_allowed("GET", "/health")
    assert release_scope.request_allowed("GET", "/internal/provenance/diagnostics")
    assert not release_scope.request_allowed("POST", "/api/intake/sessions")
    assert not release_scope.request_allowed("GET", "/api/admin/members")


def test_development_and_consumer_active_allow_business_routes(monkeypatch) -> None:
    for phase in ("development", "consumer_active"):
        monkeypatch.setenv("RELEASE_PHASE", phase)
        assert release_scope.request_allowed("POST", "/api/auth/login")
        assert release_scope.request_allowed("POST", "/api/query")
        assert release_scope.request_allowed("GET", "/api/org/region-stats")


def test_unconfigured_managed_environments_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("RELEASE_PHASE", raising=False)

    for environment in ("staging", "production"):
        monkeypatch.setenv("ENVIRONMENT", environment)
        assert release_scope.request_allowed("GET", "/health")
        assert release_scope.request_allowed("GET", "/internal/provenance/diagnostics")
        assert not release_scope.request_allowed("POST", "/api/intake/sessions")
        assert not release_scope.request_allowed("GET", "/api/admin/members")


def test_consumer_active_comment_describes_production_service_layer_boundary() -> None:
    source = Path(release_scope.__file__).read_text(encoding="utf-8")
    consumer_active_prefix = source.split("CONSUMER_ACTIVE", 1)[0]
    nearby_comment = consumer_active_prefix[-500:].lower()

    assert "never use in production" not in nearby_comment
    assert "production" in nearby_comment
    assert "service" in nearby_comment
