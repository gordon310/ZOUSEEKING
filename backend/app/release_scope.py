from __future__ import annotations

import os
import re


PHASE_ONE = "consumer_intake_preview"
MANAGED_ENVIRONMENTS = {"staging", "production"}

PHASE_ONE_API_CONTRACT = (
    "GET /health",
    "GET /health/live",
    "GET /health/ready",
    "GET /internal/provenance/diagnostics",
    "POST /api/intake/sessions",
    "POST /api/intake/sessions/{session_id}/inputs",
    "POST /api/intake/sessions/{session_id}/files",
    "PUT /api/intake/sessions/{session_id}/location",
    "PUT /api/intake/sessions/{session_id}/fields/{field_name}",
    "POST /api/intake/sessions/{session_id}/preview",
)

# Back-office surface (ADMIN_ENABLED gate still applies at the service layer;
# the allowlist only decides whether a route is reachable).  Members/audit/
# finance/collection reads are read-only; the mutators are the two
# role-assignment writes (grant / revoke, super_admin), the member-status
# write (POST /api/admin/members/{user_id}/status, member_ops/super_admin) and
# the collection-run enqueue (POST /api/admin/collection/runs,
# data_ops/super_admin), each with an audit_events row on every success.
ADMIN_API_CONTRACT = (
    "GET /api/admin/members",
    "GET /api/admin/members/{user_id}",
    "POST /api/admin/members/{user_id}/status",
    "GET /api/admin/audit",
    "GET /api/admin/finance/orders",
    "GET /api/admin/finance/refunds",
    "GET /api/admin/collection/runs",
    "POST /api/admin/collection/runs",
    "GET /api/admin/internal/me",
    "GET /api/admin/internal/roles",
    "POST /api/admin/internal/roles",
    "DELETE /api/admin/internal/roles/{user_id}/{role}",
)

PHASE_ONE_API_CONTRACT = PHASE_ONE_API_CONTRACT + ADMIN_API_CONTRACT
_ALWAYS_ALLOWED = PHASE_ONE_API_CONTRACT[:4]


def _compile_rule(contract: str) -> tuple[str, re.Pattern[str]]:
    method, path = contract.split(" ", 1)
    pattern = re.escape(path)
    # Turn every URL placeholder ({session_id}, {user_id}, ...) into a
    # non-slash path segment matcher.
    pattern = re.sub(r"\\\{[a-zA-Z_][a-zA-Z0-9_]*\\\}", r"[^/]+", pattern)
    return method, re.compile(f"^{pattern}$")


_PHASE_ONE_RULES = tuple(_compile_rule(contract) for contract in PHASE_ONE_API_CONTRACT)
_ALWAYS_ALLOWED_RULES = tuple(_compile_rule(contract) for contract in _ALWAYS_ALLOWED)


def current_release_phase() -> str:
    configured = os.getenv("RELEASE_PHASE", "").strip().lower()
    if configured:
        return configured
    environment = os.getenv("ENVIRONMENT", "").strip().lower()
    return "unconfigured_managed" if environment in MANAGED_ENVIRONMENTS else "development"


def request_allowed(method: str, path: str) -> bool:
    phase = current_release_phase()
    normalized_method = method.upper()
    if normalized_method == "OPTIONS":
        return True
    if any(
        normalized_method == allowed_method and pattern.fullmatch(path)
        for allowed_method, pattern in _ALWAYS_ALLOWED_RULES
    ):
        return True
    if phase == "development":
        return True
    if phase != PHASE_ONE:
        return False
    return any(
        normalized_method == allowed_method and pattern.fullmatch(path)
        for allowed_method, pattern in _PHASE_ONE_RULES
    )
