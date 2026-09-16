#!/usr/bin/env python3
"""Run MB1.5 against only the local disposable Supabase Postgres/API stack."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from uuid import UUID, uuid4

import asyncpg
from fastapi.testclient import TestClient

from backend.app.auth import AuthUser, require_user
from backend.app.main import app

DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
OWNER = AuthUser(UUID("00000000-0000-0000-0000-000000000201"), "owner@local.test", "Owner")
INVITEE = AuthUser(UUID("00000000-0000-0000-0000-000000000202"), "invitee@local.test", "Invitee")
MISMATCH = AuthUser(UUID("00000000-0000-0000-0000-000000000203"), "wrong@local.test", "Wrong")
ADMIN = AuthUser(UUID("00000000-0000-0000-0000-000000000204"), "ops@local.test", "Ops")
REVOKED = AuthUser(UUID("00000000-0000-0000-0000-000000000205"), "revoked@local.test", "Revoked")


def safe_payload(response, *, redact_token=True):
    payload = response.json()
    if redact_token and isinstance(payload, dict):
        if "invite_token" in payload:
            payload = {**payload, "invite_token": "<redacted-one-time-token>"}
        payload = {key: safe_value(value) for key, value in payload.items()}
    return payload


def safe_value(value):
    if isinstance(value, dict):
        return {key: ("<redacted-one-time-token>" if key == "invite_token" else safe_value(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_value(item) for item in value]
    return value


async def db_exec(sql, *args, fetch=False):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await (conn.fetch(sql, *args) if fetch else conn.execute(sql, *args))
    finally:
        await conn.close()


@contextmanager
def identity(user):
    app.dependency_overrides[require_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_user, None)


async def seed():
    conn = await asyncpg.connect(DB_URL)
    try:
        for user in (OWNER, INVITEE, MISMATCH, ADMIN, REVOKED):
            await conn.execute("insert into auth.users(id,email) values($1,$2)", user.user_id, user.email)
        await conn.execute("insert into public.internal_role_assignments(user_id,role) values($1,'member_ops')", ADMIN.user_id)
    finally:
        await conn.close()


async def readback(label):
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch("select organization_id,email,role,accepted_at,revoked_at from public.organization_invitations order by created_at")
        members = await conn.fetch("select organization_id,user_id,role,status from public.organization_members order by created_at")
        audits = await conn.fetch("select action,target_type,target_id,summary from public.audit_events where action='admin.organization.created'")
        print(f"PSQL READBACK {label} invitations={json.dumps([dict(r) for r in rows], default=str)}")
        print(f"PSQL READBACK {label} members={json.dumps([dict(r) for r in members], default=str)}")
        print(f"PSQL READBACK {label} audit_events={json.dumps([dict(r) for r in audits], default=str)}")
    finally:
        await conn.close()


def call(client, user, method, path, **kwargs):
    with identity(user):
        response = getattr(client, method)(path, **kwargs)
    print(f"HTTP {method.upper()} {path} -> {response.status_code} {json.dumps(safe_payload(response), ensure_ascii=False, sort_keys=True)}")
    return response


async def main():
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ADMIN_ENABLED", "true")
    await seed()
    try:
        with TestClient(app) as client:
            created = call(client, ADMIN, "post", "/api/admin/organizations", json={"name": "本地一次性机构", "owner_email": OWNER.email})
            owner_token = created.json()["owner_invitation"]["invite_token"]
            accepted_owner = call(client, OWNER, "post", "/api/org/invitations/accept", json={"token": owner_token})
            invite = call(client, OWNER, "post", "/api/org/invitations", json={"email": INVITEE.email, "role": "member"})
            member_token = invite.json()["invite_token"]
            call(client, OWNER, "get", "/api/org/invitations")
            call(client, MISMATCH, "post", "/api/org/invitations/accept", json={"token": member_token})
            accepted = call(client, INVITEE, "post", "/api/org/invitations/accept", json={"token": member_token})
            call(client, INVITEE, "post", "/api/org/invitations/accept", json={"token": member_token})
            call(client, INVITEE, "post", "/api/org/invitations", json={"email": "member-cannot@local.test", "role": "member"})
            call(client, MISMATCH, "get", "/api/org/invitations")
            invite2 = call(client, OWNER, "post", "/api/org/invitations", json={"email": "revoked@local.test", "role": "member"})
            revoked_list = call(client, OWNER, "get", "/api/org/invitations").json()["invitations"]
            revoke_id = next(item["id"] for item in revoked_list if item["email"] == "revoked@local.test")
            call(client, OWNER, "post", f"/api/org/invitations/{revoke_id}/revoke")
            call(client, REVOKED, "post", "/api/org/invitations/accept", json={"token": invite2.json()["invite_token"]})
            expired = call(client, OWNER, "post", "/api/org/invitations", json={"email": INVITEE.email, "role": "member"})
            await db_exec("update public.organization_invitations set created_at=now()-interval '2 days', expires_at=now()-interval '1 minute' where email='invitee@local.test' and accepted_at is null")
            call(client, INVITEE, "post", "/api/org/invitations/accept", json={"token": expired.json()["invite_token"]})
            conn = await asyncpg.connect(DB_URL)
            try:
                org_id = await conn.fetchval("select organization_id from public.organization_members where user_id=$1", OWNER.user_id)
                for _ in range(3):
                    uid = uuid4(); await conn.execute("insert into auth.users(id,email) values($1,$2)", uid, f"seat-{uid}@local.test")
                    await conn.execute("insert into public.organization_members(organization_id,user_id,role) values($1,$2,'member')", org_id, uid)
            finally:
                await conn.close()
            call(client, OWNER, "post", "/api/org/invitations", json={"email": "full@local.test", "role": "member"})
            await readback("final")
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    asyncio.run(main())
