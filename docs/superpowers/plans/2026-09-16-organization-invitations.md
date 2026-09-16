# Organization Invitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add audited organization creation and one-time, hashed member invitations across the trusted API, database RLS, browser pages, and local end-to-end evidence.

**Architecture:** Keep the existing FastAPI/service-role organization boundary. Add one additive Supabase migration for the invitation table, admin/member role compatibility, and invitation RLS; resolve organization scope only from the authenticated user and perform invite state transitions in database transactions. The browser uses the existing auth/API adapters and relative invite links.

**Tech Stack:** FastAPI, Pydantic, asyncpg, PostgreSQL/Supabase SQL migrations, vanilla HTML/CSS/JavaScript, Playwright, pytest.

**Spec:** `/tmp/zouseeking-mb15-task.md`

## Global Constraints

- Store only SHA-256 token hashes; return plaintext token only from successful creation response.
- Never accept a client-supplied organization ownership boundary or organization_id for member operations.
- Use a configurable testable seven-day invitation lifetime and constant-time token comparison.
- Use only additive forward migrations; do not edit or remove existing columns.
- Use `backend/.venv/bin/python -m pytest`; use only a local disposable database for live E2E.
- Do not commit, push, deploy, SSH, or contact production/online environments.

### Task 1: Database contract and migration

**Files:**
- Create: `supabase/migrations/20260916000300_organization_invitations.sql`
- Create: `tests/sql/test_org_invitations_contract.sql`
- Modify: `.github/workflows/release-gate.yml`

- [ ] Add the additive table, constraints, indexes, updated-at trigger, service-role grants, and owner/admin-only authenticated SELECT policy.
- [ ] Add a forward-compatible role constraint allowing `admin` while retaining owner/member values.
- [ ] Add SQL assertions and transaction rollback probes for columns, FKs, RLS, privileges, and invitation visibility.
- [ ] Add the new SQL check to both workflow required-check lists and validate YAML locally.

### Task 2: Trusted invitation and organization service

**Files:**
- Modify: `backend/app/org/routes.py`
- Modify: `backend/app/admin/routes.py`
- Modify: `backend/app/admin/service.py`
- Create: `tests/api/test_org_invitation_routes.py`
- Create: `tests/api/test_admin_organization_routes.py`

- [ ] Add validated request models, status serialization, token hashing, configurable lifetime, and transactional create/list/revoke/accept operations.
- [ ] Enforce owner/admin/member/non-member boundaries, email matching, expiry/revocation, idempotent acceptance, pending duplicate policy, and seat accounting.
- [ ] Add audited admin organization creation with optional owner invitation and no client organization_id.
- [ ] Write focused failing tests first, run them red, then implement and run them green.

### Task 3: Local disposable end-to-end evidence

**Files:**
- Create: `scripts/local_mb15_e2e.py`
- Modify: `tests/support/pg_bootstrap.py` only if required for disposable setup

- [ ] Apply the canonical local migration history plus MB15 migration to a disposable local Postgres/Supabase database.
- [ ] Exercise real HTTP API calls for owner creation, matching acceptance, repeated acceptance, mismatch, expiry, revocation, and seat-full rejection.
- [ ] Print raw HTTP responses and psql read-back without tokens or secrets in logs; capture output into the required details report.

### Task 4: Frontend organization and invite flow

**Files:**
- Modify: `web/organization.html`
- Create: `web/invite.html`
- Modify: `web/js/business-api.js`
- Modify: `web/js/business-pages.js`
- Modify: `web/js/i18n.js`
- Modify: `web/business-pages.css`
- Create: `tests/web/organization-invitations.spec.js`

- [ ] Add owner/admin invite form, one-time link display/copy, pending list/revoke, seat state, and member read-only behavior.
- [ ] Add invite token landing page with login/register guidance and dedicated localized success/invalid/expired/used/mismatch/full-seat copy.
- [ ] Build links from the current origin/relative path and avoid internal IDs, hashes, domains, or dead buttons in user-visible text.
- [ ] Add Playwright coverage for display-once, copy, revoke, member button absence, acceptance, and failure states.

### Task 5: Full verification and report

**Files:**
- Create: `/tmp/zouseeking-mb15-details.md`

- [ ] Run focused backend tests, SQL contract, browser tests, full pytest, `npm run test:web -- --workers=1`, compile/syntax checks, and workflow YAML validation.
- [ ] Record exact command output, counts, migration/column/security design, CI locations, local HTTP/psql evidence, and unexecuted items.
- [ ] Inspect `git diff --check` and report all remaining gaps without claiming online or production verification.
