from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app
from backend.app.routes import privacy
from backend.app import auth
from fastapi import HTTPException
from starlette.requests import Request
import asyncio
import pytest


USER = AuthUser(UUID("00000000-0000-0000-0000-000000000030"), "test@invalid.test", "test")


class Store:
    def __init__(self):
        self.accepted = []

    async def status(self, user_id):
        return bool(self.accepted)

    async def accept(self, user_id):
        self.accepted.append(user_id)
        return {"accepted": True, "privacy_policy_version": "privacy-2026-10", "terms_version": "terms-2026-08"}


def test_current_policy_acceptance_is_authenticated_versioned_and_server_owned():
    store = Store()
    client = TestClient(app)
    assert client.get("/api/account/consent").status_code == 401
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[privacy.get_consent_store] = lambda: store
    try:
        assert client.get("/api/account/consent").json()["accepted"] is False
        stale = client.post("/api/account/consent", json={"privacy_policy_version": "privacy-2026-08", "terms_version": "terms-2026-08"})
        assert stale.status_code == 409
        assert store.accepted == []
        response = client.post("/api/account/consent", json={"privacy_policy_version": "privacy-2026-10", "terms_version": "terms-2026-08", "user_id": "another-user", "accepted_at": "2000-01-01"})
        assert response.status_code == 200
        assert store.accepted == [USER.user_id]
        assert client.get("/api/account/consent").json()["accepted"] is True
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(privacy.get_consent_store, None)


def test_consumer_business_requests_require_trusted_ledger_consent(monkeypatch):
    monkeypatch.setenv("RELEASE_PHASE", "consumer_launch")
    monkeypatch.setattr(auth, "_fetch_supabase_user", lambda token: {"id": str(USER.user_id), "user_metadata": {"consent_version": "privacy-2026-10"}})
    from backend.app.services.policy_consent import PolicyConsentStore
    async def not_accepted(self, user_id):
        return False
    monkeypatch.setattr(PolicyConsentStore, "status", not_accepted)
    request = Request({"type": "http", "method": "POST", "path": "/api/intake/sessions", "headers": []})
    with pytest.raises(HTTPException) as error:
        asyncio.run(auth.require_user("Bearer fixture", request=request))
    assert error.value.status_code == 428
    request = Request({"type": "http", "method": "GET", "path": "/api/reports/fixture", "headers": []})
    with pytest.raises(HTTPException) as error:
        asyncio.run(auth.optional_user("Bearer fixture", request=request))
    assert error.value.status_code == 428
    request = Request({"type": "http", "method": "POST", "path": "/api/account/consent", "headers": []})
    assert asyncio.run(auth.require_user("Bearer fixture", request=request)).user_id == USER.user_id


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_consent_store_failure_is_fail_closed_and_redacted(method):
    class Unavailable:
        async def status(self, user_id):
            raise RuntimeError('private database details must not escape')
        async def accept(self, user_id):
            raise RuntimeError('private database details must not escape')
    app.dependency_overrides[require_user] = lambda: USER
    app.dependency_overrides[privacy.get_consent_store] = lambda: Unavailable()
    try:
        client = TestClient(app)
        response = client.request(method, '/api/account/consent', **({'json': {'privacy_policy_version': 'privacy-2026-10', 'terms_version': 'terms-2026-08'}} if method == 'POST' else {}))
        assert response.status_code == 503
        assert 'private database' not in response.text
    finally:
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(privacy.get_consent_store, None)


@pytest.mark.parametrize('path,payload', [
    ('/api/account/consent', {'privacy_policy_version': ['fixture-private-token'], 'terms_version': 'terms-2026-08'}),
    ('/api/account/deletion-request', {'privacy_policy_version': 'privacy-2026-10', 'terms_version': 'terms-2026-08', 'confirmation': 'fixture-private-token'}),
])
def test_invalid_privacy_fields_do_not_echo_input(path, payload):
    app.dependency_overrides[require_user] = lambda: USER
    try:
        response = TestClient(app).post(path, json=payload)
        assert response.status_code == 422
        assert 'fixture-private-token' not in response.text
    finally:
        app.dependency_overrides.pop(require_user, None)
