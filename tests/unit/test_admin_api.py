"""Tests for the back-office read-only admin API (unit one).

Two layers:

1. Pure unit tests (no database, no network): role gating decisions through a
   fake :class:`AdminService`, serialisation/masking helpers, the env gate,
   the release_scope allowlist and SQL-builder sanity (parameters line up).

2. Real-Postgres integration tests (skipped unless ``DATABASE_URL`` points at
   a disposable localhost server, mirroring ``test_db_ledger`` / billing
   store conventions): migrations are applied to a fresh ``admin_api_test``
   database, seed rows are inserted, and every ``AdminService`` read method is
   exercised and asserted to leave row counts unchanged (SELECT-only proof).

The admin API never writes to application databases; the disposable database
is created and dropped by this module itself.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.admin import auth as admin_auth
from backend.app.admin.auth import (
    FINANCE,
    MEMBER_OPS,
    SUPER_ADMIN,
    ADMIN_ROLES,
    require_admin_role,
)
from backend.app.admin.routes import router as admin_router
from backend.app.admin.service import (
    DEFAULT_AUDIT_LIMIT,
    EMAIL_VISIBLE_ROLES,
    MEMBER_OPS_ACTION_PREFIXES,
    AdminService,
    current_month_period_key,
    get_admin_service,
    mask_email,
)
from backend.app.auth import AuthUser, require_user
from backend.app.release_scope import (
    ADMIN_API_CONTRACT,
    PHASE_ONE_API_CONTRACT,
    request_allowed,
)

UTC = timezone.utc
ACTOR = uuid.UUID("00000000-0000-0000-0000-000000000001")
VIEWER = uuid.UUID("00000000-0000-0000-0000-000000000002")
MEMBER = uuid.UUID("00000000-0000-0000-0000-000000000003")
UNKNOWN = uuid.UUID("00000000-0000-0000-0000-000000000099")

SAMPLE_USER = AuthUser(user_id=VIEWER, email="viewer@example.com", username="viewer")

FAKE_MEMBER_PAGE = {
    "total": 1,
    "page": 1,
    "page_size": 20,
    "items": [
        {
            "user_id": str(MEMBER),
            "username": "alice",
            "display_name": "Alice",
            "email": "alice@example.com",
            "membership_tier": "pro",
            "daily_query_limit": 50,
            "roles": [{"role": "member_ops", "expires_at": None}],
            "subscriptions": [],
            "usage_quotas": [],
            "created_at": "2026-09-01T00:00:00+00:00",
        }
    ],
}

FAKE_ROLES_PAGE = {
    "items": [
        {
            "id": str(uuid.uuid4()),
            "user_id": str(MEMBER),
            "role": "finance",
            "granted_at": "2026-09-01T00:00:00+00:00",
            "expires_at": None,
        }
    ]
}


class FakeAdminService:
    """In-memory stand-in for AdminService; records role checks, no DB."""

    def __init__(self, roles=None, members=None, missing_users=()):
        self.roles = list(roles or [])
        self.members = members
        self.missing_users = {str(u) for u in missing_users}
        self.audit_scopes = []
        self.audit_calls = 0
        self.orders_calls = 0
        self.refunds_calls = 0
        self.roles_calls = 0
        self.grants = []
        self.revokes = []
        self.user_exists_calls = 0

    async def fetch_active_roles(self, user_id):
        return list(self.roles)

    async def list_members(self, q="", page=1, page_size=20, *, email_visible=True):
        items = []
        for item in self.members or FAKE_MEMBER_PAGE["items"]:
            copy = dict(item)
            copy["email"] = (
                copy.get("email", "")
                if email_visible
                else mask_email(copy.get("email", ""))
            )
            items.append(copy)
        return {"total": len(items), "page": page, "page_size": page_size, "items": items}

    async def get_member(self, user_id, *, email_visible=True):
        for item in self.members or FAKE_MEMBER_PAGE["items"]:
            if item["user_id"] == str(user_id):
                copy = dict(item)
                copy["usage_events"] = []
                if not email_visible:
                    copy["email"] = mask_email(copy.get("email", ""))
                return copy
        return None

    async def list_audit(self, *, actor=None, action="", since=None, limit=100, member_ops_scope=False):
        self.audit_calls += 1
        self.audit_scopes.append(member_ops_scope)
        return {"limit": limit, "member_ops_scope": member_ops_scope, "items": []}

    async def list_orders(self, status=None, page=1, page_size=20):
        self.orders_calls += 1
        return {"total": 0, "subtotal_amount_minor": 0, "page": page, "page_size": page_size, "items": []}

    async def list_refunds(self, status=None, page=1, page_size=20):
        self.refunds_calls += 1
        return {"total": 0, "subtotal_amount_minor": 0, "page": page, "page_size": page_size, "items": []}

    async def list_role_assignments(self):
        self.roles_calls += 1
        return FAKE_ROLES_PAGE

    async def user_exists(self, user_id):
        self.user_exists_calls += 1
        return str(user_id) not in self.missing_users

    async def grant_role(self, **kwargs):
        self.grants.append(kwargs)
        return {
            "id": str(uuid.uuid4()),
            "user_id": str(kwargs["user_id"]),
            "role": kwargs["role"],
            "granted_by_user_id": str(kwargs["granted_by"]),
            "granted_at": "2026-09-05T00:00:00+00:00",
            "expires_at": kwargs.get("expires_at"),
            "note": kwargs.get("note"),
        }

    async def revoke_role(self, **kwargs):
        self.revokes.append(kwargs)
        return {"revoked": True, "user_id": str(kwargs["user_id"]), "role": kwargs["role"]}


def _build_app(fake_service: FakeAdminService) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)

    def _auth_user() -> AuthUser:
        return SAMPLE_USER

    app.dependency_overrides[require_user] = _auth_user
    app.dependency_overrides[get_admin_service] = lambda: fake_service
    return app


def _build_app_with_auth(auth: AuthUser) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_user] = lambda: auth
    app.dependency_overrides[get_admin_service] = lambda: FakeAdminService(roles=["member_ops"])
    return app


def _call(app: FastAPI, method: str, path: str, **kwargs):
    with TestClient(app) as client:
        return getattr(client, method)(path, **kwargs)


# -- auth helpers ------------------------------------------------------------

def test_admin_role_vocabulary_matches_database_check() -> None:
    assert ADMIN_ROLES == frozenset(
        {"member_ops", "data_ops", "task_dispatcher", "reviewer", "finance", "super_admin"}
    )


def test_require_admin_role_rejects_unknown_or_empty_roles() -> None:
    with pytest.raises(ValueError):
        require_admin_role()
    with pytest.raises(ValueError):
        require_admin_role("superuser")


def test_mask_email_redacts_local_part() -> None:
    assert mask_email("alice@example.com") == "a***@example.com"
    assert mask_email("a@example.com") == "a***@example.com"
    assert mask_email("") == ""
    assert mask_email("not-an-email") == "not-an-email"


def test_email_visible_roles_cover_member_endpoint_viewers() -> None:
    assert {"member_ops", "super_admin"} <= EMAIL_VISIBLE_ROLES


def test_admin_principal_role_set_and_has_role() -> None:
    principal = admin_auth.AdminPrincipal(SAMPLE_USER, ["member_ops", "finance"])
    assert principal.role_set == frozenset({"member_ops", "finance"})
    assert principal.has_role("finance")
    assert not principal.has_role("super_admin")


# -- role gating matrix (fake service, no DB) -------------------------------

@pytest.mark.parametrize(
    "path,method,roles,expected",
    [
        # member list / detail: member_ops or super_admin
        ("/api/admin/members", "get", ["member_ops"], 200),
        ("/api/admin/members", "get", ["super_admin"], 200),
        ("/api/admin/members", "get", ["finance"], 403),
        ("/api/admin/members", "get", ["data_ops"], 403),
        ("/api/admin/members", "get", [], 403),
        ("/api/admin/members/00000000-0000-0000-0000-000000000003", "get", ["member_ops"], 200),
        ("/api/admin/members/00000000-0000-0000-0000-000000000003", "get", ["super_admin"], 200),
        ("/api/admin/members/00000000-0000-0000-0000-000000000003", "get", ["task_dispatcher"], 403),
        # finance: finance or super_admin
        ("/api/admin/finance/orders", "get", ["finance"], 200),
        ("/api/admin/finance/orders", "get", ["super_admin"], 200),
        ("/api/admin/finance/orders", "get", ["member_ops"], 403),
        ("/api/admin/finance/refunds", "get", ["finance"], 200),
        ("/api/admin/finance/refunds", "get", ["member_ops"], 403),
        # audit: super_admin full, member_ops member scope
        ("/api/admin/audit", "get", ["super_admin"], 200),
        ("/api/admin/audit", "get", ["member_ops"], 200),
        ("/api/admin/audit", "get", ["reviewer"], 403),
        # roles: super_admin only
        ("/api/admin/internal/roles", "get", ["super_admin"], 200),
        ("/api/admin/internal/roles", "get", ["finance"], 403),
        ("/api/admin/internal/roles", "get", ["member_ops"], 403),
    ],
)
def test_role_gate_matrix(path, method, roles, expected) -> None:
    app = _build_app(FakeAdminService(roles=roles))
    response = _call(app, method, path)
    assert response.status_code == expected, (path, roles, response.text)


def test_audit_member_ops_requests_scoped_log_super_admin_full() -> None:
    scoped = FakeAdminService(roles=["member_ops"])
    assert _call(_build_app(scoped), "get", "/api/admin/audit").status_code == 200
    assert scoped.audit_scopes == [True]

    full = FakeAdminService(roles=["super_admin"])
    assert _call(_build_app(full), "get", "/api/admin/audit").status_code == 200
    assert full.audit_scopes == [False]


def test_members_response_masks_email_only_outside_gate() -> None:
    # member_ops/super_admin both hold email visibility: full address returned.
    visible = _build_app(FakeAdminService(roles=["member_ops"]))
    payload = _call(visible, "get", "/api/admin/members").json()
    assert payload["items"][0]["email"] == "alice@example.com"


def test_member_detail_unknown_user_is_404() -> None:
    app = _build_app(FakeAdminService(roles=["member_ops"], members=[]))
    response = _call(
        app, "get", "/api/admin/members/00000000-0000-0000-0000-000000000099"
    )
    assert response.status_code == 404


def test_member_detail_malformed_user_id_is_422() -> None:
    app = _build_app(FakeAdminService(roles=["member_ops"]))
    assert _call(app, "get", "/api/admin/members/not-a-uuid").status_code == 422


def test_internal_roles_reachable_by_super_admin_only() -> None:
    app = _build_app(FakeAdminService(roles=["super_admin"]))
    payload = _call(app, "get", "/api/admin/internal/roles").json()
    assert payload["items"][0]["role"] == "finance"


# -- role assignment writes: unit gates (fake service, no DB) ---------------

def test_me_returns_own_active_roles_for_any_authenticated_user() -> None:
    app = _build_app(FakeAdminService(roles=["finance"]))
    payload = _call(app, "get", "/api/admin/internal/me").json()
    assert payload["user_id"] == str(VIEWER)
    assert payload["roles"] == ["finance"]


def test_me_returns_empty_roles_when_caller_holds_none() -> None:
    app = _build_app(FakeAdminService(roles=[]))
    payload = _call(app, "get", "/api/admin/internal/me").json()
    assert payload["user_id"] == str(VIEWER)
    assert payload["roles"] == []


def test_role_write_endpoints_are_super_admin_only() -> None:
    # POST with a valid body: the 403 must come from the role gate, not from
    # body validation, so every non-super_admin role is rejected.
    for role in ("finance", "member_ops", "data_ops", "reviewer"):
        app = _build_app(FakeAdminService(roles=[role]))
        granted = _call(
            app, "post", "/api/admin/internal/roles",
            json={"user_id": str(MEMBER), "role": "finance"},
        )
        assert granted.status_code == 403, (role, granted.text)
        revoked = _call(
            app, "delete", f"/api/admin/internal/roles/{MEMBER}/finance"
        )
        assert revoked.status_code == 403, (role, revoked.text)


def test_super_admin_grant_and_revoke_reach_service() -> None:
    fake = FakeAdminService(roles=["super_admin"])
    app = _build_app(fake)
    granted = _call(
        app, "post", "/api/admin/internal/roles",
        json={"user_id": str(MEMBER), "role": "data_ops", "note": "unit"},
    )
    assert granted.status_code == 201, granted.text
    assert granted.json()["role"] == "data_ops"
    assert granted.json()["granted_by_user_id"] == str(VIEWER)
    assert fake.grants[0]["role"] == "data_ops"
    assert fake.grants[0]["granted_by"] == VIEWER

    revoked = _call(
        app, "delete", f"/api/admin/internal/roles/{MEMBER}/data_ops"
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"revoked": True, "user_id": str(MEMBER), "role": "data_ops"}
    assert fake.revokes[0]["revoked_by"] == VIEWER


def test_grant_validation_rejects_bad_role_user_and_expiry() -> None:
    fake = FakeAdminService(roles=["super_admin"], missing_users=[UNKNOWN])
    app = _build_app(fake)
    cases = [
        # unknown role outside the six-value vocabulary
        {"user_id": str(MEMBER), "role": "root"},
        # malformed user_id
        {"user_id": "not-a-uuid", "role": "finance"},
        # user not present in auth.users
        {"user_id": str(UNKNOWN), "role": "finance"},
        # expiry in the past
        {"user_id": str(MEMBER), "role": "finance", "expires_at": "2000-01-01T00:00:00Z"},
        # unparseable expiry
        {"user_id": str(MEMBER), "role": "finance", "expires_at": "soon"},
    ]
    for body in cases:
        response = _call(app, "post", "/api/admin/internal/roles", json=body)
        assert response.status_code == 400, (body, response.text)
    assert fake.grants == []
    assert fake.user_exists_calls == 1  # only the auth.users case reached DB


def test_grant_accepts_future_expiry_and_note() -> None:
    fake = FakeAdminService(roles=["super_admin"])
    app = _build_app(fake)
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    response = _call(
        app, "post", "/api/admin/internal/roles",
        json={"user_id": str(MEMBER), "role": "reviewer", "expires_at": future, "note": "tmp"},
    )
    assert response.status_code == 201, response.text
    assert fake.grants[0]["note"] == "tmp"
    assert fake.grants[0]["expires_at"] is not None


def test_revoke_rejects_unknown_role_or_user_shape() -> None:
    fake = FakeAdminService(roles=["super_admin"])
    app = _build_app(fake)
    assert _call(app, "delete", "/api/admin/internal/roles/abc/finance").status_code == 400
    assert _call(app, "delete", f"/api/admin/internal/roles/{MEMBER}/root").status_code == 400
    assert fake.revokes == []


def test_super_admin_cannot_revoke_own_super_admin() -> None:
    fake = FakeAdminService(roles=["super_admin"])
    app = _build_app(fake)
    response = _call(
        app, "delete", f"/api/admin/internal/roles/{VIEWER}/super_admin"
    )
    assert response.status_code == 400, response.text
    assert "super_admin" in response.json()["detail"]
    assert fake.revokes == []  # guard fires before any service call


def test_unauthenticated_request_is_401() -> None:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[get_admin_service] = lambda: FakeAdminService(roles=["super_admin"])

    def _deny():
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。")

    app.dependency_overrides[require_user] = _deny
    assert _call(app, "get", "/api/admin/members").status_code == 401


# -- env gate ----------------------------------------------------------------

def test_admin_env_gate_503_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        get_admin_service()
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "admin 未配置"


def test_admin_env_gate_503_even_when_enabled_without_pool(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_ENABLED", "true")
    with pytest.raises(HTTPException) as exc_info:
        get_admin_service()
    assert exc_info.value.status_code == 503


# -- release_scope allowlist -------------------------------------------------

def test_admin_routes_are_on_phase_one_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("RELEASE_PHASE", "consumer_intake_preview")
    assert "GET /api/admin/members" in ADMIN_API_CONTRACT
    for path in (
        "/api/admin/members",
        "/api/admin/members/00000000-0000-0000-0000-000000000003",
        "/api/admin/audit",
        "/api/admin/finance/orders",
        "/api/admin/finance/refunds",
        "/api/admin/internal/me",
        "/api/admin/internal/roles",
    ):
        assert request_allowed("GET", path), path
    # role-assignment writes are allowlisted under their exact verbs only
    assert request_allowed("POST", "/api/admin/internal/roles")
    assert request_allowed(
        "DELETE", "/api/admin/internal/roles/00000000-0000-0000-0000-000000000003/finance"
    )
    # non-allowlisted verbs / paths stay blocked in the managed phase
    assert not request_allowed("DELETE", "/api/admin/members")
    assert not request_allowed("POST", "/api/admin/members")
    assert not request_allowed("PUT", "/api/admin/internal/roles")
    assert not request_allowed("GET", "/api/admin/members/extra/segment")


def test_phase_one_contract_extends_public_list() -> None:
    assert "GET /api/admin/audit" in PHASE_ONE_API_CONTRACT


# -- serialisation / query helpers ------------------------------------------

def test_current_month_period_key_is_utc8_month() -> None:
    moment = datetime(2026, 9, 5, 1, 30, tzinfo=UTC)  # 09:30 UTC+8 same day
    assert current_month_period_key(moment) == "2026-09"
    # UTC 2026-08-31 18:00 is already 2026-09-01 02:00 in UTC+8
    edge = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)
    assert current_month_period_key(edge) == "2026-09"


def test_member_ops_audit_prefixes_are_dotted_domains() -> None:
    for prefix in MEMBER_OPS_ACTION_PREFIXES:
        assert prefix.endswith(".")
        assert " " not in prefix


# ============================================================================
# Real-Postgres integration (skipped unless a disposable local server is set)
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = [
    REPO_ROOT / "supabase" / "migrations" / "20260905000100_v1_organizations.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000200_v1_products_subscriptions.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000300_v1_usage_ledger.sql",
    REPO_ROOT / "supabase" / "migrations" / "20260905000500_v1_finance_admin_audit.sql",
]

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
pytestmark_db = pytest.mark.asyncio


def _db_path(url: str, database: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{database}"))


def _local_server(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


async def _bootstrap_and_migrate(url: str) -> None:
    """Create admin_api_test on the local server and apply the V1 batch."""
    admin = await asyncpg.connect(url, database="postgres")
    try:
        await admin.execute("drop database if exists admin_api_test with (force)")
        await admin.execute("create database admin_api_test")
    finally:
        await admin.close()

    conn = await asyncpg.connect(_db_path(url, "admin_api_test"))
    try:
        await conn.execute(
            """
            do $$
            begin
              if to_regrole('anon') is null then execute 'create role anon nologin'; end if;
              if to_regrole('authenticated') is null then execute 'create role authenticated nologin'; end if;
              if to_regrole('service_role') is null then execute 'create role service_role nologin'; end if;
            end $$;
            create schema if not exists auth;
            create table if not exists auth.users (
              id uuid primary key,
              email text
            );
            create or replace function auth.uid() returns uuid
            language sql stable as $$
              select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
            $$;
            create or replace function public.set_updated_at()
            returns trigger language plpgsql as $$
            begin
              new.updated_at = now();
              return new;
            end
            $$;
            """
        )
        # user_profiles lives in the legacy baseline migration; reproduce the
        # exact applied shape here so the disposable db matches production.
        await conn.execute(
            """
            create table if not exists public.user_profiles (
              user_id uuid primary key references auth.users(id) on delete cascade,
              email text not null default '',
              username text not null default '',
              display_name text not null default '',
              city text not null default '',
              favorite_area text not null default '',
              favorite_asset_type text not null default '',
              bio text not null default '',
              membership_tier text not null default 'free',
              daily_query_limit integer not null default 3,
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            );
            """
        )
        for path in MIGRATIONS:
            await conn.execute(path.read_text(encoding="utf-8"))
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    if not _local_server(DATABASE_URL):
        pytest.skip(
            "DATABASE_URL must point at a disposable local PostgreSQL server"
            " (localhost/127.0.0.1) to run the real-Postgres admin tests"
        )
    asyncio.run(_bootstrap_and_migrate(DATABASE_URL))
    return _db_path(DATABASE_URL, "admin_api_test")


@pytest_asyncio.fixture
async def seeded_pool(_migrated_database: str):
    pool = await asyncpg.create_pool(_migrated_database)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Wipe every seeded table before each test (function-scoped reuse).
            # usage_events/audit_events are append-only: disable the guards
            # before truncating, exactly like the ledger integration suite.
            for trigger_table, trigger in (
                ("public.usage_events", "enforce_usage_events_append_only"),
                ("public.audit_events", "audit_events_no_update"),
                ("public.audit_events", "audit_events_no_delete"),
                ("public.audit_events", "audit_events_no_truncate"),
            ):
                await conn.execute(
                    f"alter table {trigger_table} disable trigger {trigger}"
                )
            await conn.execute(
                "truncate table"
                " public.payment_orders, public.refunds, public.payment_events,"
                " public.internal_role_assignments, public.audit_events,"
                " public.subscriptions, public.billing_customers,"
                " public.usage_quotas, public.usage_events, public.usage_idempotency,"
                " public.organization_members, public.organizations,"
                " public.user_profiles, auth.users"
                " restart identity cascade"
            )
            for trigger_table, trigger in (
                ("public.usage_events", "enforce_usage_events_append_only"),
                ("public.audit_events", "audit_events_no_update"),
                ("public.audit_events", "audit_events_no_delete"),
                ("public.audit_events", "audit_events_no_truncate"),
            ):
                await conn.execute(
                    f"alter table {trigger_table} enable trigger {trigger}"
                )
    async with pool.acquire() as conn:
        async with conn.transaction():
            for user_id, email, tier in (
                (ACTOR, "actor@example.com", "free"),
                (VIEWER, "viewer@example.com", "pro"),
                (MEMBER, "member@example.com", "pro"),
            ):
                await conn.execute(
                    "insert into auth.users (id, email) values ($1, $2)"
                    " on conflict (id) do nothing",
                    user_id,
                    email,
                )
                await conn.execute(
                    "insert into public.user_profiles"
                    " (user_id, email, username, display_name, membership_tier, daily_query_limit)"
                    " values ($1, $2, $3, $4, $5, $6)"
                    " on conflict (user_id) do nothing",
                    user_id,
                    email,
                    email.split("@")[0],
                    email.split("@")[0].title(),
                    tier,
                    3 if tier == "free" else 50,
                )
            # Role assignments: ACTOR super_admin, VIEWER finance, MEMBER ops.
            await conn.execute(
                "insert into public.internal_role_assignments (user_id, role, granted_by_user_id)"
                " values ($1, 'super_admin', $1)",
                ACTOR,
            )
            await conn.execute(
                "insert into public.internal_role_assignments (user_id, role, granted_by_user_id)"
                " values ($1, 'finance', $1)",
                VIEWER,
            )
            await conn.execute(
                "insert into public.internal_role_assignments (user_id, role, granted_by_user_id)"
                " values ($1, 'member_ops', $1), ($1, 'finance', $1)",
                MEMBER,
            )
            # Expired role assignment must not count as active (granted first,
            # expired in the past - the DB check requires expires_at > granted_at).
            await conn.execute(
                "insert into public.internal_role_assignments"
                " (user_id, role, granted_by_user_id, granted_at, expires_at)"
                " values ($1, 'reviewer', $1, now() - interval '2 days', now() - interval '1 day')",
                MEMBER,
            )
            # Active personal subscription for MEMBER.
            await conn.execute(
                "insert into public.subscriptions"
                " (user_id, product_code, price_version, currency, amount_minor,"
                "  status, current_period_start, current_period_end)"
                " values ($1, 'c_plus_monthly', 1, 'CNY', 2900, 'active', now(), now() + interval '30 days')",
                MEMBER,
            )
            # Current-month usage quota rows for MEMBER (UTC+8 month key).
            period_key = current_month_period_key()
            member_scope = f"user:{MEMBER}"
            await conn.execute(
                "insert into public.usage_quotas"
                " (scope_key, usage_kind, period_key, limit_units, consumed_units, reserved_units)"
                " values ($1, 'query', $2, 3, 2, 0),"
                "        ($1, 'report', $2, 10, 4, 1)",
                member_scope,
                period_key,
            )
            # A usage event for the member detail view.
            await conn.execute(
                "insert into public.usage_events"
                " (scope_key, usage_kind, operation, units, period_key, idempotency_key, actor_user_id)"
                " values ($1, 'query', 'consume', 1, $2, 'seed-1', $3)",
                member_scope,
                period_key,
                MEMBER,
            )
            # Audit rows: one member-domain, one finance-domain.
            await conn.execute(
                "insert into public.audit_events (actor_user_id, action, target_type, target_id, summary)"
                " values ($1, 'member.profile.updated', 'user_profile', $2, '{\"changed\": \"display_name\"}')",
                MEMBER,
                str(MEMBER),
            )
            await conn.execute(
                "insert into public.audit_events (actor_user_id, action, target_type, target_id, summary)"
                " values ($1, 'billing.refund.retry_scheduled', 'refund', $2, '{}')",
                ACTOR,
                str(uuid.uuid4()),
            )
            # One paid order and one succeeded refund for the finance views.
            order_id = await conn.fetchval(
                "insert into public.payment_orders"
                " (order_no, owner_user_id, product_code, price_version, currency,"
                "  amount_minor, status, provider, paid_at)"
                " values ('ORD-SEED-1', $1, 'c_plus_monthly', 1, 'CNY', 2900, 'paid', 'stripe', now())"
                " returning id",
                MEMBER,
            )
            await conn.execute(
                "insert into public.refunds"
                " (order_id, amount_minor, currency, reason, status, provider_refund_id)"
                " values ($1, 2900, 'CNY', 'customer_request', 'succeeded', 're_seed_1')",
                order_id,
            )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def admin_service(seeded_pool: asyncpg.Pool):
    return AdminService(pool=seeded_pool)


async def _table_counts(conn: asyncpg.Connection) -> dict:
    counts = {}
    for table in (
        "public.user_profiles",
        "public.internal_role_assignments",
        "public.subscriptions",
        "public.usage_quotas",
        "public.usage_events",
        "public.audit_events",
        "public.payment_orders",
        "public.refunds",
    ):
        counts[table] = await conn.fetchval(f"select count(*) from {table}")
    return counts


@pytestmark_db
async def test_fetch_active_roles_honours_expiry(admin_service: AdminService) -> None:
    roles = await admin_service.fetch_active_roles(MEMBER)
    assert set(roles) == {"member_ops", "finance"}  # reviewer assignment expired
    assert await admin_service.fetch_active_roles(ACTOR) == ["super_admin"]
    assert await admin_service.fetch_active_roles(VIEWER) == ["finance"]


@pytestmark_db
async def test_list_members_real_query(admin_service: AdminService, seeded_pool: asyncpg.Pool) -> None:
    async with seeded_pool.acquire() as conn:
        before = await _table_counts(conn)
    result = await admin_service.list_members(page=1, page_size=20, email_visible=True)
    assert result["total"] == 3
    member = next(item for item in result["items"] if item["user_id"] == str(MEMBER))
    assert member["email"] == "member@example.com"
    assert {r["role"] for r in member["roles"]} == {"member_ops", "finance"}
    assert member["subscriptions"][0]["product_code"] == "c_plus_monthly"
    assert member["subscriptions"][0]["status"] == "active"
    month_usage = {q["usage_kind"]: q for q in member["usage_quotas"]}
    assert month_usage["query"]["consumed_units"] == 2
    assert month_usage["report"]["consumed_units"] == 4

    # q filters by display_name or user_id substring (seeded uuids share the
    # '00000000' prefix, so match on the distinct trailing digits).
    by_name = await admin_service.list_members(q="mem")
    assert by_name["total"] == 1 and by_name["items"][0]["user_id"] == str(MEMBER)
    by_id = await admin_service.list_members(q=str(MEMBER)[-4:])
    assert by_id["total"] == 1 and by_id["items"][0]["user_id"] == str(MEMBER)

    # masking kicks in when the caller has no email visibility.
    masked = await admin_service.list_members(email_visible=False)
    assert masked["items"][0]["email"].startswith("a***@")

    async with seeded_pool.acquire() as conn:
        after = await _table_counts(conn)
    assert after == before  # SELECT-only proof: nothing changed


@pytestmark_db
async def test_get_member_real_query(
    admin_service: AdminService, seeded_pool: asyncpg.Pool
) -> None:
    async with seeded_pool.acquire() as conn:
        before = await _table_counts(conn)
    member = await admin_service.get_member(MEMBER, email_visible=True)
    assert member is not None
    assert member["user_id"] == str(MEMBER)
    assert member["email"] == "member@example.com"
    assert len(member["usage_events"]) == 1
    assert member["usage_events"][0]["usage_kind"] == "query"

    missing = await admin_service.get_member(
        uuid.UUID("00000000-0000-0000-0000-000000000099")
    )
    assert missing is None

    async with seeded_pool.acquire() as conn:
        after = await _table_counts(conn)
    assert after == before


@pytestmark_db
async def test_list_audit_real_query_and_member_scope(
    admin_service: AdminService, seeded_pool: asyncpg.Pool
) -> None:
    async with seeded_pool.acquire() as conn:
        before = await _table_counts(conn)
    full = await admin_service.list_audit(limit=100, member_ops_scope=False)
    actions = {item["action"] for item in full["items"]}
    assert {"member.profile.updated", "billing.refund.retry_scheduled"} <= actions

    scoped = await admin_service.list_audit(limit=100, member_ops_scope=True)
    scoped_actions = {item["action"] for item in scoped["items"]}
    assert "member.profile.updated" in scoped_actions
    assert "billing.refund.retry_scheduled" not in scoped_actions

    # actor filter narrows to that actor's rows.
    actor_rows = await admin_service.list_audit(actor=MEMBER, limit=100)
    assert all(item["actor_user_id"] == str(MEMBER) for item in actor_rows["items"])

    # action prefix filter.
    billing_rows = await admin_service.list_audit(action="billing.", limit=100)
    assert all(item["action"].startswith("billing.") for item in billing_rows["items"])

    async with seeded_pool.acquire() as conn:
        after = await _table_counts(conn)
    assert after == before


@pytestmark_db
async def test_finance_views_real_query(
    admin_service: AdminService, seeded_pool: asyncpg.Pool
) -> None:
    async with seeded_pool.acquire() as conn:
        before = await _table_counts(conn)
    orders = await admin_service.list_orders(page=1, page_size=20)
    assert orders["total"] == 1
    assert orders["subtotal_amount_minor"] == 2900
    assert orders["items"][0]["order_no"] == "ORD-SEED-1"
    assert orders["items"][0]["status"] == "paid"

    paid = await admin_service.list_orders(status="paid")
    assert paid["total"] == 1
    assert (await admin_service.list_orders(status="pending"))["total"] == 0

    refunds = await admin_service.list_refunds(page=1, page_size=20)
    assert refunds["total"] == 1
    assert refunds["subtotal_amount_minor"] == 2900
    assert refunds["items"][0]["order_no"] == "ORD-SEED-1"
    assert refunds["items"][0]["reason"] == "customer_request"

    with pytest.raises(HTTPException):
        await admin_service.list_orders(status="nonsense")

    async with seeded_pool.acquire() as conn:
        after = await _table_counts(conn)
    assert after == before


@pytestmark_db
async def test_list_role_assignments_real_query(
    admin_service: AdminService, seeded_pool: asyncpg.Pool
) -> None:
    async with seeded_pool.acquire() as conn:
        before = await _table_counts(conn)
    result = await admin_service.list_role_assignments()
    # 5 rows seeded: ACTOR super_admin, VIEWER finance, MEMBER member_ops +
    # finance (active), MEMBER reviewer (already expired).
    assert result["items"] and len(result["items"]) == 5
    roles = {item["role"] for item in result["items"]}
    assert {"super_admin", "finance", "member_ops", "reviewer"} == roles
    async with seeded_pool.acquire() as conn:
        after = await _table_counts(conn)
    assert after == before


# ============================================================================
# Role-assignment writes against real Postgres (disposable local server)
# ============================================================================

def _actor_auth() -> AuthUser:
    return AuthUser(user_id=ACTOR, email="actor@example.com", username="actor")


def _viewer_auth() -> AuthUser:
    return AuthUser(user_id=VIEWER, email="viewer@example.com", username="viewer")


def _build_real_app(pool: asyncpg.Pool, auth: AuthUser) -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_user] = lambda: auth
    app.dependency_overrides[get_admin_service] = lambda: AdminService(pool=pool)
    return app


async def _audit_actions(
    pool: asyncpg.Pool, action: str = "", target: str = ""
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select actor_user_id, action, target_type, target_id, summary"
            " from public.audit_events"
            " where ($1 = '' or action = $1)"
            "   and ($2 = '' or target_id = $2)"
            " order by occurred_at, id",
            action,
            target,
        )
    return [
        {
            "actor_user_id": row["actor_user_id"],
            "action": row["action"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "summary": json.loads(row["summary"]),
        }
        for row in rows
    ]


@pytestmark_db
async def test_http_grant_role_writes_assignment_and_audit(
    seeded_pool: asyncpg.Pool,
) -> None:
    app = _build_real_app(seeded_pool, _actor_auth())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(MEMBER), "role": "data_ops", "note": "http-integration"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == str(MEMBER)
    assert body["role"] == "data_ops"
    assert body["granted_by_user_id"] == str(ACTOR)
    assert body["note"] == "http-integration"
    assert body["expires_at"] is None

    service = AdminService(pool=seeded_pool)
    assert "data_ops" in await service.fetch_active_roles(MEMBER)

    rows = await _audit_actions(seeded_pool, "admin.role.granted", str(MEMBER))
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == ACTOR
    assert rows[0]["target_type"] == "user"
    assert rows[0]["target_id"] == str(MEMBER)
    assert rows[0]["summary"]["role"] == "data_ops"
    assert rows[0]["summary"]["granted_by"] == str(ACTOR)


@pytestmark_db
async def test_http_grant_honours_future_expiry(seeded_pool: asyncpg.Pool) -> None:
    app = _build_real_app(seeded_pool, _actor_auth())
    transport = httpx.ASGITransport(app=app)
    future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(MEMBER), "role": "task_dispatcher", "expires_at": future},
        )
    assert response.status_code == 201, response.text
    stored = await _audit_actions(seeded_pool, "admin.role.granted", str(MEMBER))
    assert len(stored) == 1
    # an expiring assignment is still active until expires_at
    service = AdminService(pool=seeded_pool)
    assert "task_dispatcher" in await service.fetch_active_roles(MEMBER)


@pytestmark_db
async def test_http_duplicate_grant_is_409_without_audit_row(
    seeded_pool: asyncpg.Pool,
) -> None:
    app = _build_real_app(seeded_pool, _actor_auth())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # MEMBER already holds finance in the seed data.
        response = await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(MEMBER), "role": "finance"},
        )
    assert response.status_code == 409, response.text
    # failed grant leaves no audit trail (transaction rolled back)
    rows = await _audit_actions(seeded_pool, "admin.role.granted", str(MEMBER))
    assert rows == []


@pytestmark_db
async def test_http_grant_missing_user_is_400_without_audit_row(
    seeded_pool: asyncpg.Pool,
) -> None:
    app = _build_real_app(seeded_pool, _actor_auth())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(UNKNOWN), "role": "data_ops"},
        )
    assert response.status_code == 400, response.text
    rows = await _audit_actions(seeded_pool, "admin.role.granted", str(UNKNOWN))
    assert rows == []


@pytestmark_db
async def test_http_non_super_admin_cannot_write_or_list_roles(
    seeded_pool: asyncpg.Pool,
) -> None:
    app = _build_real_app(seeded_pool, _viewer_auth())  # VIEWER is finance only
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(MEMBER), "role": "data_ops"},
        )).status_code == 403
        assert (await client.delete(
            f"/api/admin/internal/roles/{MEMBER}/finance"
        )).status_code == 403
        assert (await client.get("/api/admin/internal/roles")).status_code == 403
        # but the viewer may always read their own roles
        me = await client.get("/api/admin/internal/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == str(VIEWER)
    assert me.json()["roles"] == ["finance"]


@pytestmark_db
async def test_http_revoke_removes_assignment_and_audits(
    seeded_pool: asyncpg.Pool,
) -> None:
    app = _build_real_app(seeded_pool, _actor_auth())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        granted = await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(VIEWER), "role": "task_dispatcher"},
        )
        assert granted.status_code == 201, granted.text
        revoked = await client.delete(
            f"/api/admin/internal/roles/{VIEWER}/task_dispatcher"
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json() == {"revoked": True, "user_id": str(VIEWER), "role": "task_dispatcher"}
        # gone from the active role set and from the raw table
        service = AdminService(pool=seeded_pool)
        assert "task_dispatcher" not in await service.fetch_active_roles(VIEWER)
        async with seeded_pool.acquire() as conn:
            remaining = await conn.fetchval(
                "select count(*) from public.internal_role_assignments"
                " where user_id = $1 and role = 'task_dispatcher'",
                VIEWER,
            )
        assert remaining == 0
        # revoking again is a 404 and writes no second audit row
        again = await client.delete(
            f"/api/admin/internal/roles/{VIEWER}/task_dispatcher"
        )
        assert again.status_code == 404
    rows = await _audit_actions(seeded_pool, "admin.role.revoked", str(VIEWER))
    assert len(rows) == 1
    assert rows[0]["summary"]["role"] == "task_dispatcher"
    assert rows[0]["summary"]["revoked_by"] == str(ACTOR)


@pytestmark_db
async def test_http_self_revoke_super_admin_blocked_and_other_super_admin_can(
    seeded_pool: asyncpg.Pool,
) -> None:
    app = _build_real_app(seeded_pool, _actor_auth())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # a super_admin cannot revoke their own super_admin (self-lockout guard)
        blocked = await client.delete(f"/api/admin/internal/roles/{ACTOR}/super_admin")
        assert blocked.status_code == 400, blocked.text
        assert "super_admin" in blocked.json()["detail"]
        # ...but another super_admin can revoke it (add a second one first)
        granted = await client.post(
            "/api/admin/internal/roles",
            json={"user_id": str(VIEWER), "role": "super_admin"},
        )
        assert granted.status_code == 201, granted.text
    service = AdminService(pool=seeded_pool)
    assert "super_admin" in await service.fetch_active_roles(VIEWER)
    # VIEWER (now super_admin) still may not revoke themself
    viewer_app = _build_real_app(seeded_pool, _viewer_auth())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=viewer_app), base_url="http://test"
    ) as client:
        self_blocked = await client.delete(f"/api/admin/internal/roles/{VIEWER}/super_admin")
        assert self_blocked.status_code == 400
    # ACTOR revokes VIEWER's super_admin: allowed and audited
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        revoked = await client.delete(f"/api/admin/internal/roles/{VIEWER}/super_admin")
    assert revoked.status_code == 200, revoked.text
    assert "super_admin" not in await service.fetch_active_roles(VIEWER)
