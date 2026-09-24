"""Consumer registration boundary with an optional invite source."""

from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app import invites
from backend.app.invites import InviteCodeError, InviteRegistration, normalize_invite_code
from backend.app.rate_limit import abuse_subject_hash
from backend.app.routes import invites as invite_routes


def test_normalize_invite_code_is_case_insensitive_and_trimmed() -> None:
    assert normalize_invite_code("  Zou-Launch-01 ") == "zou-launch-01"


@pytest.mark.parametrize("value", ["", " ", "x" * 129])
def test_normalize_invite_code_rejects_empty_or_oversized_values(value: str) -> None:
    with pytest.raises(InviteCodeError) as error:
        normalize_invite_code(value)
    assert error.value.code == "invite_code_invalid"


def test_invite_error_is_safe_for_client_i18n() -> None:
    error = InviteCodeError("invite_code_exhausted", 409)
    assert error.code == "invite_code_exhausted"
    assert error.status_code == 409
    assert str(error) == "invite_code_exhausted"


def test_existing_account_path_is_not_an_invite_gate() -> None:
    # Login keeps using Supabase Auth; it must never require an invite code.
    from backend.app.invites import INVITE_REQUIRED_OPERATIONS

    assert "login" not in INVITE_REQUIRED_OPERATIONS
    assert "existing_account" not in INVITE_REQUIRED_OPERATIONS


def test_registration_abuse_subject_uses_a_salted_non_reversible_hash(monkeypatch) -> None:
    monkeypatch.setenv("ABUSE_HASH_SALT", "test-secret")
    digest = abuse_subject_hash("registration", "203.0.113.7")
    assert digest != "203.0.113.7"
    assert len(digest) == 64


def test_registration_request_accepts_missing_invite_code_and_keeps_route_contract() -> None:
    body = invite_routes.InviteRegisterRequest(
        email="member@example.com", password="password", username="member"
    )

    route = next(route for route in invite_routes.router.routes if route.path == "/api/auth/invite-register")
    assert body.invite_code == ""
    assert route.status_code == 201


class _InviteConnection:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.redemption_id = UUID("00000000-0000-0000-0000-000000000001")

    async def fetchrow(self, query: str, *args):
        self.calls.append("reserve")
        return {"redemption_id": self.redemption_id, "state": "reserved"}

    async def fetchval(self, query: str, *args):
        self.calls.append("complete")
        return True

    async def execute(self, query: str, *args):
        self.calls.append("release")


async def _run_admin_creation(function, payload):
    return function(payload)


@pytest.mark.asyncio
async def test_registration_with_invite_reserves_then_completes_and_records_invite_source(monkeypatch) -> None:
    connection = _InviteConnection()
    payloads: list[dict] = []

    def create_user(payload):
        payloads.append(payload)
        return {"id": "00000000-0000-0000-0000-000000000002"}

    monkeypatch.setattr(invites, "_admin_create_user", create_user)
    monkeypatch.setattr(invites.asyncio, "to_thread", _run_admin_creation)

    result = await invites.register_invited_user(
        connection,
        InviteRegistration("member@example.com", "password", "member", "ZOU-1"),
    )

    assert result == {"user_id": "00000000-0000-0000-0000-000000000002", "email": "member@example.com"}
    assert connection.calls == ["reserve", "complete"]
    assert payloads[0]["user_metadata"]["consent_source"] == "invite_registration"


@pytest.mark.asyncio
async def test_registration_without_invite_creates_user_without_invite_database_calls(monkeypatch) -> None:
    connection = _InviteConnection()
    payloads: list[dict] = []

    def create_user(payload):
        payloads.append(payload)
        return {"id": "00000000-0000-0000-0000-000000000003"}

    monkeypatch.setattr(invites, "_admin_create_user", create_user)
    monkeypatch.setattr(invites.asyncio, "to_thread", _run_admin_creation)

    result = await invites.register_invited_user(
        connection,
        InviteRegistration("member@example.com", "password", "member", ""),
    )

    assert result == {"user_id": "00000000-0000-0000-0000-000000000003", "email": "member@example.com"}
    assert connection.calls == []
    assert payloads[0]["user_metadata"]["consent_source"] == "consumer_registration"


@pytest.mark.asyncio
async def test_registration_without_invite_propagates_admin_failure_without_release(monkeypatch) -> None:
    connection = _InviteConnection()

    def create_user(payload):
        raise InviteCodeError("invite_service_unavailable", 503)

    monkeypatch.setattr(invites, "_admin_create_user", create_user)
    monkeypatch.setattr(invites.asyncio, "to_thread", _run_admin_creation)

    with pytest.raises(InviteCodeError, match="invite_service_unavailable"):
        await invites.register_invited_user(
            connection,
            InviteRegistration("member@example.com", "password", "member", ""),
        )

    assert connection.calls == []


class _RouteConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _RoutePool:
    def acquire(self):
        return _RouteConnection()


@pytest.mark.asyncio
@pytest.mark.parametrize("invite_code", ["", "ZOU-1"])
async def test_registration_rate_limit_precedes_account_creation_for_both_sources(monkeypatch, invite_code) -> None:
    events: list[str] = []

    async def consume_rate_limit(*args):
        events.append("rate_limit")
        return 1

    async def register_user(connection, registration):
        events.append("register")
        return {"user_id": "example", "email": registration.email}

    monkeypatch.setattr(invite_routes, "get_pool", lambda: _RoutePool())
    monkeypatch.setattr(invite_routes, "abuse_subject_hash", lambda *args: "hash")
    monkeypatch.setattr(invite_routes, "configured_limit", lambda *args: 5)
    monkeypatch.setattr(invite_routes, "consume_shared_rate_limit", consume_rate_limit)
    monkeypatch.setattr(invite_routes, "register_invited_user", register_user)

    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.7"))
    body = invite_routes.InviteRegisterRequest(
        email="member@example.com", password="password", username="member", invite_code=invite_code
    )
    await invite_routes.invite_register(body, request)

    assert events == ["rate_limit", "register"]
