# Osaka Property Intake and Free Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable product slice for anonymous Osaka second-hand apartment intake, private file submission, field confirmation, completeness scoring, free preview, and account conversion.

**Architecture:** Add a new FastAPI-only intake boundary backed by Supabase PostgreSQL and a private Supabase Storage bucket. Anonymous access uses a random bearer secret stored only as a SHA-256 hash; registration atomically binds the session and resulting property to `auth.uid()`. The new frontend is a separate page and ES module bundle so the existing regional-data flow in `web/app.js` remains unchanged.

**Tech Stack:** Python 3.12, FastAPI 0.116, Pydantic 2.11, asyncpg 0.30, Supabase Auth/PostgreSQL/Storage, vanilla HTML/CSS/ES modules, pytest, HTTPX.

**Spec:** `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md`

## Global Constraints

- Phase 1 supports only Osaka second-hand apartments and towers; reject unsupported prefectures and project types.
- The user chooses `self_use` or `rental_investment`; the selected purpose is immutable after the first preview.
- Anonymous sessions expire exactly 24 hours after creation.
- Anonymous files remain private and are deleted after expiry unless the project is converted to an authenticated account.
- All user-owned records are written through FastAPI; browser code cannot set `owner_user_id`, membership, entitlement, or job state.
- Keep JPY values numeric and store their units separately.
- Every field keeps source, locator, extraction method, confidence, and user-confirmation state.
- Missing evidence produces `insufficient_data`; it never produces a legal violation or a fabricated estimate.
- Do not add payment, OCR, model calls, market-price estimation, tax-rate calculations, legal conclusions, or a background-worker service in this plan.
- Do not modify the formal Supabase project `ZOUSEEKING`; database work targets only `zoubeacon-staging` until separate production approval.
- Do not add paid Render or Supabase resources.
- Before the first commit, restore the repository's existing Git metadata from `gordon310/ZOUSEEKING`; do not run `git init` in the current non-Git directory and do not overwrite uncommitted workspace files.

## Delivery Sequence

This specification spans five independently testable subsystems. Implement them as separate plans:

1. **This plan:** intake, evidence-ready fields, free preview, and account conversion.
2. Extraction adapters: permitted URL retrieval, PDF/image parsing, OCR, AI extraction, and conflict review.
3. Osaka analytics: comparable selection, acquisition-cost rules, self-use analysis, and three investment scenarios.
4. Legal and report engine: official policy versions, important-matters checklist, risk triggers, and 11-section report.
5. Commercial controls: test entitlements, report versions, 30-day update, deletion, audit, and later payment integration.

Each plan must leave the staging application runnable. Phase 1 displays uploaded inputs as “等待自动提取” and lets the user confirm fields manually; it does not pretend AI extraction has occurred.

## File Structure

### New backend files

- `backend/app/intake/__init__.py` — package marker only.
- `backend/app/intake/models.py` — Pydantic request/response contracts and field-name allowlist.
- `backend/app/intake/tokens.py` — anonymous token creation, hashing, and constant-time verification.
- `backend/app/intake/repository.py` — all SQL for sessions, candidate evidence, confirmed fields, previews, conversion, and expiry.
- `backend/app/intake/storage.py` — private Supabase Storage upload/delete adapter.
- `backend/app/intake/completeness.py` — pure completeness and free-preview calculation.
- `backend/app/routes/intake.py` — HTTP endpoints; no calculation or raw SQL.

### New database and test files

- `supabase/migrations/20260825000400_property_intake.sql` — forward-only schema, constraints, indexes, and RLS.
- `tests/sql/test_property_intake_schema.sql` — schema and RLS assertions.
- `scripts/run_sql_file.py` — execute plain SQL verification files through asyncpg without requiring Docker or `psql`.
- `tests/unit/test_intake_tokens.py` — token security tests.
- `tests/unit/test_intake_models.py` — validation tests.
- `tests/unit/test_completeness.py` — deterministic scoring tests.
- `tests/unit/test_intake_repository.py` — repository transaction tests with a fake connection.
- `tests/unit/test_intake_storage.py` — Storage request and error-redaction tests.
- `tests/api/test_intake_routes.py` — route ownership, expiry, upload, preview, and conversion tests.
- `backend/requirements-dev.txt` — pytest and HTTPX test dependencies.

### New frontend files

- `web/property-analysis.html` — accessible five-step intake page.
- `web/property-analysis.css` — page-specific responsive styles.
- `web/js/api-client.js` — API requests and Supabase access-token lookup.
- `web/js/property-intake.js` — state machine, form submission, rendering, and conversion.
- `tests/web/property-intake.spec.js` — Playwright happy path and error-state tests.

### Modified files

- `backend/app/main.py` — include the intake router only.
- `backend/requirements.txt` — add multipart parsing.
- `web/index.html` — add the primary “分析一个日本房产” entry link.
- `web/styles.css` — add only the shared primary-entry component.
- `docs/data-dictionary.md` — document the new tables and ownership rules.
- `docs/supabase-setup.md` — document the private bucket and staging secrets.

---

### Task 1: Add the Forward-Only Intake Schema

**Files:**
- Create: `supabase/migrations/20260825000400_property_intake.sql`
- Create: `tests/sql/test_property_intake_schema.sql`
- Create: `scripts/run_sql_file.py`
- Modify: `docs/data-dictionary.md`

**Interfaces:**
- Consumes: existing `auth.users`, `public.properties`, and `public.residential_details`.
- Produces: tables `analysis_sessions`, `project_inputs`, `project_field_evidence`, `project_fields`, `free_previews`, and `intake_rate_limits`; function `public.prevent_intake_identity_change()`.

- [ ] **Step 1: Write the failing SQL assertions**

```sql
-- tests/sql/test_property_intake_schema.sql
do $$
declare
  required_table text;
begin
  foreach required_table in array array[
    'analysis_sessions', 'project_inputs', 'project_field_evidence', 'project_fields', 'free_previews',
    'intake_rate_limits'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing intake table: %', required_table;
    end if;
    if not exists (
      select 1 from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = required_table and c.relrowsecurity
    ) then
      raise exception 'RLS disabled for intake table: %', required_table;
    end if;
  end loop;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('analysis_sessions', 'project_inputs', 'project_field_evidence', 'project_fields', 'free_previews')
      and roles::text like '%anon%'
  ) then
    raise exception 'anonymous REST policy exists on private intake data';
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'analysis_sessions_expires_after_creation'
  ) then
    raise exception '24-hour expiry constraint is missing';
  end if;
end $$;
```

- [ ] **Step 2: Verify the assertion fails on a disposable Supabase database**

First create the SQL runner:

```python
# scripts/run_sql_file.py
import argparse
import asyncio
import os
from pathlib import Path

import asyncpg


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--database-url-env", default="TEST_DATABASE_URL")
    parser.add_argument("--rollback-after", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get(args.database_url_env, "")
    if not database_url:
        raise SystemExit(f"missing environment variable: {args.database_url_env}")
    connection = await asyncpg.connect(database_url)
    transaction = connection.transaction()
    await transaction.start()
    try:
        for filename in args.files:
            await connection.execute(Path(filename).read_text(encoding="utf-8"))
        if args.rollback_after:
            await transaction.rollback()
        else:
            await transaction.commit()
    except BaseException:
        await transaction.rollback()
        raise
    finally:
        await connection.close()


asyncio.run(main())
```

Run the assertion against `zoubeacon-staging` inside a transaction:

```bash
backend/.venv/bin/python scripts/run_sql_file.py \
  --database-url-env STAGING_DATABASE_URL \
  --rollback-after \
  tests/sql/test_property_intake_schema.sql
```

Expected: failure containing `missing intake table: analysis_sessions`.

- [ ] **Step 3: Write the migration**

Create these exact table contracts:

```sql
create table public.analysis_sessions (
  id uuid primary key default gen_random_uuid(),
  token_hash char(64) not null unique,
  owner_user_id uuid references auth.users(id) on delete cascade,
  property_id uuid references public.properties(id) on delete set null,
  purpose text not null check (purpose in ('self_use', 'rental_investment')),
  consent_version text not null,
  status text not null default 'draft'
    check (status in ('draft', 'preview_ready', 'converted', 'expired')),
  purpose_locked_at timestamptz,
  expires_at timestamptz not null,
  converted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint analysis_sessions_expires_after_creation
    check (expires_at > created_at and expires_at <= created_at + interval '24 hours 5 minutes')
);

create table public.project_inputs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.analysis_sessions(id) on delete cascade,
  input_type text not null check (input_type in ('text', 'url', 'pdf', 'image')),
  source_url text,
  storage_path text,
  original_name text,
  media_type text,
  size_bytes bigint check (size_bytes is null or size_bytes between 1 and 20971520),
  content_hash char(64),
  raw_text text,
  processing_status text not null default 'pending'
    check (processing_status in ('pending', 'manual_review', 'ready', 'failed')),
  created_at timestamptz not null default now(),
  check (source_url is not null or storage_path is not null or raw_text is not null)
);

create table public.project_field_evidence (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.analysis_sessions(id) on delete cascade,
  source_input_id uuid references public.project_inputs(id) on delete set null,
  field_name text not null,
  raw_value jsonb not null default 'null'::jsonb,
  normalized_value jsonb not null default 'null'::jsonb,
  unit text,
  locator text not null default '',
  extraction_method text not null check (extraction_method in ('manual', 'parser', 'ocr', 'ai')),
  confidence text not null check (confidence in ('high', 'medium', 'low', 'unreviewed')),
  created_at timestamptz not null default now(),
  unique (session_id, source_input_id, field_name, locator, normalized_value)
);

create table public.project_fields (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.analysis_sessions(id) on delete cascade,
  field_name text not null,
  selected_evidence_id uuid references public.project_field_evidence(id) on delete set null,
  confirmed_value jsonb,
  unit text,
  confirmation_status text not null default 'unreviewed'
    check (confirmation_status in ('unreviewed', 'confirmed', 'corrected', 'unknown', 'conflict')),
  confirmed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (session_id, field_name)
);

create table public.free_previews (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null unique references public.analysis_sessions(id) on delete cascade,
  completeness jsonb not null,
  acquisition_costs jsonb not null,
  risk_summary jsonb not null,
  comparable_status text not null check (comparable_status in ('not_checked', 'sufficient', 'insufficient')),
  calculation_version text not null,
  created_at timestamptz not null default now()
);

create table public.intake_rate_limits (
  abuse_key_hash char(64) not null,
  action text not null,
  window_started_at timestamptz not null,
  request_count integer not null default 1 check (request_count > 0),
  expires_at timestamptz not null,
  primary key (abuse_key_hash, action, window_started_at)
);

create index idx_analysis_sessions_owner on public.analysis_sessions(owner_user_id, created_at desc);
create index idx_analysis_sessions_expiry on public.analysis_sessions(expires_at) where status <> 'converted';
create index idx_project_inputs_session on public.project_inputs(session_id, created_at);
create index idx_project_field_evidence_session on public.project_field_evidence(session_id, field_name);
create index idx_project_fields_session on public.project_fields(session_id, field_name);
create index idx_intake_rate_limits_expiry on public.intake_rate_limits(expires_at);

alter table public.analysis_sessions enable row level security;
alter table public.project_inputs enable row level security;
alter table public.project_field_evidence enable row level security;
alter table public.project_fields enable row level security;
alter table public.free_previews enable row level security;
alter table public.intake_rate_limits enable row level security;

revoke all on public.analysis_sessions, public.project_inputs, public.project_field_evidence, public.project_fields, public.free_previews, public.intake_rate_limits
from anon, authenticated;
```

Add this trigger guard. Direct FastAPI connections use the PostgreSQL `postgres` role; browser JWT roles do not.

```sql
create or replace function public.prevent_intake_identity_change()
returns trigger
language plpgsql
as $$
begin
  if current_user not in ('postgres', 'service_role', 'supabase_admin')
     and not public.is_service_role()
     and (
       new.owner_user_id is distinct from old.owner_user_id
       or new.property_id is distinct from old.property_id
       or new.token_hash is distinct from old.token_hash
       or new.expires_at is distinct from old.expires_at
       or new.converted_at is distinct from old.converted_at
     ) then
    raise exception 'intake identity is server-managed';
  end if;
  if old.purpose_locked_at is not null and new.purpose is distinct from old.purpose then
    raise exception 'analysis purpose is locked';
  end if;
  return new;
end;
$$;

create trigger protect_intake_identity
before update on public.analysis_sessions
for each row execute function public.prevent_intake_identity_change();
```

- [ ] **Step 4: Apply and verify on the disposable database**

Run:

```bash
backend/.venv/bin/python scripts/run_sql_file.py \
  --database-url-env STAGING_DATABASE_URL \
  --rollback-after \
  supabase/migrations/20260825000400_property_intake.sql \
  tests/sql/test_property_intake_schema.sql
```

Expected: exit 0; the transaction rolls back, so staging is unchanged.

- [ ] **Step 5: Update the data dictionary and commit**

Document table ownership, retention, allowed statuses, units, and why browser REST access is revoked.

```bash
git add supabase/migrations/20260825000400_property_intake.sql tests/sql/test_property_intake_schema.sql scripts/run_sql_file.py docs/data-dictionary.md
git commit -m "feat: add private property intake schema"
```

---

### Task 2: Define Intake Contracts and Anonymous Tokens

**Files:**
- Create: `backend/app/intake/__init__.py`
- Create: `backend/app/intake/models.py`
- Create: `backend/app/intake/tokens.py`
- Create: `tests/unit/test_intake_models.py`
- Create: `tests/unit/test_intake_tokens.py`

**Interfaces:**
- Produces: `CreateSessionRequest`, `CreateSessionResponse`, `CreateInputRequest`, `ConfirmFieldRequest`, `FieldView`, `FreePreviewResponse`, `SessionToken`, `new_session_token()`, `hash_session_token()`, and `verify_session_token()`.

- [ ] **Step 1: Write failing model tests**

```python
from pydantic import ValidationError
import pytest

from backend.app.intake.models import CreateInputRequest, CreateSessionRequest, ConfirmFieldRequest


def test_session_accepts_only_two_purposes():
    assert CreateSessionRequest(purpose="self_use", consent_version="privacy-2026-08").purpose == "self_use"
    with pytest.raises(ValidationError):
        CreateSessionRequest(purpose="flip", consent_version="privacy-2026-08")


def test_url_input_requires_https_and_manual_field_is_allowlisted():
    with pytest.raises(ValidationError):
        CreateInputRequest(input_type="url", source_url="javascript:alert(1)")
    field = ConfirmFieldRequest(field_name="asking_price_jpy", value=35000000, confirmation_status="confirmed")
    assert field.unit == "JPY"
    with pytest.raises(ValidationError):
        ConfirmFieldRequest(field_name="owner_user_id", value="attacker", confirmation_status="confirmed")
```

- [ ] **Step 2: Write failing token tests**

```python
from backend.app.intake.tokens import hash_session_token, new_session_token, verify_session_token


def test_session_token_is_random_and_only_hash_is_compared():
    first = new_session_token()
    second = new_session_token()
    assert first.raw != second.raw
    assert len(first.digest) == 64
    assert first.digest == hash_session_token(first.raw)
    assert verify_session_token(first.raw, first.digest)
    assert not verify_session_token(second.raw, first.digest)
```

- [ ] **Step 3: Run tests and verify import failures**

Run:

```bash
pytest tests/unit/test_intake_models.py tests/unit/test_intake_tokens.py -q
```

Expected: failure because `backend.app.intake` does not exist.

- [ ] **Step 4: Implement the token contract**

```python
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe


@dataclass(frozen=True)
class SessionToken:
    raw: str
    digest: str


def hash_session_token(raw: str) -> str:
    return sha256(raw.encode("utf-8")).hexdigest()


def new_session_token() -> SessionToken:
    raw = token_urlsafe(32)
    return SessionToken(raw=raw, digest=hash_session_token(raw))


def verify_session_token(raw: str, expected_digest: str) -> bool:
    return compare_digest(hash_session_token(raw), expected_digest)
```

- [ ] **Step 5: Implement Pydantic contracts**

Use these exact literals and field names:

```python
Purpose = Literal["self_use", "rental_investment"]
InputType = Literal["text", "url"]
ConfirmationStatus = Literal["confirmed", "corrected", "unknown"]

FIELD_UNITS = {
    "building_name": None,
    "address": None,
    "ward": None,
    "station": None,
    "walk_minutes": "minutes",
    "building_year": "year",
    "total_units": "units",
    "floor": "floor",
    "orientation": None,
    "area_sqm": "sqm",
    "balcony_area_sqm": "sqm",
    "land_right": None,
    "land_share": None,
    "asking_price_jpy": "JPY",
    "management_fee_jpy": "JPY/month",
    "repair_reserve_jpy": "JPY/month",
    "monthly_rent_jpy": "JPY/month",
}
```

`CreateInputRequest` must reject text longer than 20,000 characters, non-HTTPS URLs, credentials embedded in URLs, and hosts without a dot. `ConfirmFieldRequest` derives `unit` from `FIELD_UNITS`; it never accepts a client-provided unit.

`ConfirmFieldRequest` also accepts optional `source_input_id: UUID | None` and `locator: str` with a 200-character limit. The server always stores `extraction_method="manual"`; when no source input is selected it stores `locator="用户手动填写"` and `confidence="unreviewed"`.

- [ ] **Step 6: Run tests and commit**

```bash
pytest tests/unit/test_intake_models.py tests/unit/test_intake_tokens.py -q
git add backend/app/intake tests/unit/test_intake_models.py tests/unit/test_intake_tokens.py
git commit -m "feat: define property intake contracts"
```

Expected: all tests pass.

---

### Task 3: Implement Deterministic Completeness and Free Preview

**Files:**
- Create: `backend/app/intake/completeness.py`
- Create: `tests/unit/test_completeness.py`

**Interfaces:**
- Consumes: `Mapping[str, FieldValue]` where `FieldValue.value`, `confirmation_status`, `confidence`, and `has_evidence` are explicit.
- Produces: `calculate_completeness(fields) -> dict[str, dict[str, object]]` and `build_free_preview(fields) -> dict[str, object]`.

- [ ] **Step 1: Write the failing completeness tests**

```python
from backend.app.intake.completeness import FieldValue, build_free_preview, calculate_completeness


def test_missing_critical_rights_field_cannot_be_hidden_by_other_fields():
    fields = {
        "building_name": FieldValue("Grand Osaka", "confirmed", "high", True),
        "address": FieldValue("大阪市北区", "confirmed", "high", True),
        "asking_price_jpy": FieldValue(35000000, "confirmed", "high", True),
        "area_sqm": FieldValue(45.2, "confirmed", "high", True),
    }
    result = calculate_completeness(fields)
    assert result["legal_transaction"]["status"] == "insufficient_data"
    assert "land_right" in result["legal_transaction"]["missing_critical"]


def test_preview_lists_cost_items_without_inventing_tax_amounts():
    preview = build_free_preview({"asking_price_jpy": FieldValue(35000000, "confirmed", "high", True)})
    assert preview["acquisition_costs"]["status"] == "rules_not_loaded"
    assert preview["acquisition_costs"]["estimated_total_jpy"] is None
    assert "不动产取得税" in preview["acquisition_costs"]["items"]
    assert preview["comparable_status"] == "not_checked"
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/unit/test_completeness.py -q
```

Expected: import failure for `completeness`.

- [ ] **Step 3: Implement the six dimensions**

Define immutable requirement sets:

```python
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldValue:
    value: Any
    confirmation_status: str
    confidence: str
    has_evidence: bool


DIMENSIONS = {
    "identity": ({"building_name", "address", "area_sqm", "building_year"}, {"address", "area_sqm"}),
    "price_cost": ({"asking_price_jpy", "management_fee_jpy", "repair_reserve_jpy"}, {"asking_price_jpy"}),
    "yield": ({"monthly_rent_jpy", "management_fee_jpy", "repair_reserve_jpy"}, set()),
    "building_management": ({"total_units", "management_fee_jpy", "repair_reserve_jpy"}, set()),
    "legal_transaction": ({"land_right", "land_share"}, {"land_right"}),
    "source_trust": ({"building_name", "address", "asking_price_jpy", "area_sqm"}, set()),
}
```

For each dimension return `confirmed`, `total`, `percent`, `status`, `missing`, `missing_critical`, and `conflicts`. Any critical missing field sets `status="insufficient_data"`. Otherwise use `complete` at 100, `partial` from 1 to 99, and `empty` at 0. Source trust counts only values with evidence and confidence `high` or `medium`.

`build_free_preview()` returns the six dimensions, a cost item list with no amounts until the versioned cost rules exist, basic risk counts derived only from conflicts/missing critical fields, `comparable_status="not_checked"`, and `calculation_version="free-preview-v1"`.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/unit/test_completeness.py -q
git add backend/app/intake/completeness.py tests/unit/test_completeness.py
git commit -m "feat: calculate evidence-aware free previews"
```

---

### Task 4: Implement the Intake Repository and Atomic Account Conversion

**Files:**
- Create: `backend/app/intake/repository.py`
- Create: `tests/unit/test_intake_repository.py`

**Interfaces:**
- Consumes: asyncpg pool, hashed session token, validated request models, authenticated UUID.
- Produces: `IntakeRepository.create_session()`, `require_session()`, `add_input()`, `upsert_field()`, `save_preview()`, `convert_to_user()`, `consume_rate_limit()`, and `expire_sessions()`.

Define `SessionNotFound(Exception)` with no user data in its message and:

```python
@dataclass(frozen=True)
class ConvertedProject:
    owner_user_id: UUID
    property_id: UUID
```

- [ ] **Step 1: Write failing transaction tests with a recording fake connection**

```python
@pytest.mark.asyncio
async def test_conversion_locks_session_and_sets_owner_server_side():
    connection = RecordingConnection(session={"status": "preview_ready", "owner_user_id": None})
    repository = IntakeRepository(FakePool(connection))
    result = await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID)
    assert "for update" in connection.queries[0].lower()
    assert USER_ID in connection.arguments
    assert result.owner_user_id == USER_ID
    assert connection.transaction_committed


@pytest.mark.asyncio
async def test_expired_or_already_owned_session_cannot_be_claimed():
    repository = IntakeRepository(FakePool(RecordingConnection(session=None)))
    with pytest.raises(SessionNotFound):
        await repository.convert_to_user(SESSION_ID, TOKEN_HASH, USER_ID)
```

- [ ] **Step 2: Run and verify failure**

```bash
pytest tests/unit/test_intake_repository.py -q
```

Expected: import failure for `IntakeRepository`.

- [ ] **Step 3: Implement repository methods with parameterized SQL**

`require_session()` must query by both `id` and `token_hash`, require `expires_at > now()` unless converted, and return the same `SessionNotFound` for wrong token, wrong ID, and expired session.

`convert_to_user()` must use one transaction and this order:

```sql
select * from public.analysis_sessions
where id=$1 and token_hash=$2 and owner_user_id is null and expires_at > now()
for update;

insert into public.properties
  (owner_user_id, project_type, prefecture, city, ward, building_name,
   building_year, area_sqm, asking_price, price_currency, data_class, confidence)
values ($3, 'residential', '大阪府', '大阪市', $4, $5, $6, $7, $8, 'JPY', 'user_submitted', 'unreviewed')
returning id;

insert into public.residential_details
  (property_id, management_fee_jpy, repair_reserve_jpy, monthly_rent_jpy, details)
values ($9, $10, $11, $12, $13::jsonb);

update public.analysis_sessions
set owner_user_id=$3, property_id=$9, status='converted', converted_at=now(), updated_at=now()
where id=$1;
```

Build values only from allowlisted `project_fields`; never accept owner or property IDs from the client. If the session has already been converted to the same user, return the existing conversion without creating a second property. A different user receives `SessionNotFound`.

- [ ] **Step 4: Implement expiry selection**

`expire_sessions(limit=100)` uses `for update skip locked`, changes eligible rows to `expired`, and returns their storage paths so the caller can delete files after commit. It must never select `status='converted'`.

`consume_rate_limit(abuse_key_hash, action, window_started_at, limit)` uses one `insert ... on conflict ... do update` statement with `where intake_rate_limits.request_count < $limit returning request_count`. No returned row means the limit is exhausted. Delete expired rate-limit rows in the same bounded cleanup pass.

- [ ] **Step 5: Run tests and commit**

```bash
pytest tests/unit/test_intake_repository.py -q
git add backend/app/intake/repository.py tests/unit/test_intake_repository.py
git commit -m "feat: persist and convert anonymous property intake"
```

---

### Task 5: Add Private File Storage

**Files:**
- Create: `backend/app/intake/storage.py`
- Create: `tests/unit/test_intake_storage.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`
- Modify: `docs/supabase-setup.md`

**Interfaces:**
- Produces: `StorageObject`, `validate_upload()`, `upload_private_file()`, and `delete_private_file()`.
- Environment: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `INTAKE_BUCKET=property-intake`.

- [ ] **Step 1: Add dependencies**

```text
# backend/requirements.txt
python-multipart==0.0.20

# backend/requirements-dev.txt
-r requirements.txt
pytest==8.4.1
pytest-asyncio==1.1.0
httpx==0.28.1
```

- [ ] **Step 2: Write failing validation and redaction tests**

```python
def test_upload_rejects_extension_content_type_mismatch():
    with pytest.raises(UnsupportedUpload):
        validate_upload("contract.pdf", "image/png", b"\x89PNG\r\n\x1a\n")


def test_storage_error_never_contains_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-value")
    with pytest.raises(StorageUnavailable) as error:
        upload_private_file("session-1", "a.pdf", "application/pdf", b"%PDF-broken")
    assert "secret-value" not in str(error.value)
```

- [ ] **Step 3: Implement file validation**

Allow only:

```python
ALLOWED_UPLOADS = {
    "application/pdf": (".pdf", b"%PDF-"),
    "image/jpeg": ((".jpg", ".jpeg"), b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
```

Reject empty files, names containing path separators, size over 20 MiB, wrong magic bytes, and mismatched extensions. Generate the storage object path server-side as `{session_id}/{uuid4()}{normalized_extension}`.

- [ ] **Step 4: Implement private Storage REST calls**

Use `urllib.request` with an 8-second timeout. Upload to `/storage/v1/object/{bucket}/{path}` with `Authorization: Bearer <service role>`, `apikey`, `Content-Type`, and `x-upsert: false`. Delete only exact paths returned from the database. Translate remote details to `StorageUnavailable("文件服务暂时不可用，请稍后重试。")`; never expose response bodies or secrets.

- [ ] **Step 5: Run tests and commit**

```bash
pytest tests/unit/test_intake_storage.py -q
git add backend/app/intake/storage.py tests/unit/test_intake_storage.py backend/requirements.txt backend/requirements-dev.txt docs/supabase-setup.md
git commit -m "feat: store intake files in private Supabase storage"
```

---

### Task 6: Add Intake API Routes

**Files:**
- Create: `backend/app/routes/intake.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_intake_routes.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Produces endpoints:
  - `POST /api/intake/sessions`
  - `POST /api/intake/sessions/{session_id}/inputs`
  - `POST /api/intake/sessions/{session_id}/files`
  - `PUT /api/intake/sessions/{session_id}/fields/{field_name}`
  - `POST /api/intake/sessions/{session_id}/preview`
  - `POST /api/intake/sessions/{session_id}/convert`
  - `GET /api/intake/projects/{property_id}`
- Anonymous header: `X-Analysis-Session: <raw token>`.
- Authenticated header: existing `Authorization: Bearer <Supabase access token>`.

- [ ] **Step 1: Write failing API tests**

In `tests/api/conftest.py`, construct `TestClient(app)` with dependency overrides for `IntakeRepository`, Storage, and `require_user`. The fake repository must keep sessions in a dictionary keyed by UUID, store only token digests, expose `created_properties`, and use a fixed UTC clock of `2026-08-25T00:00:00Z`. The `auth_header` override returns `AuthUser(UUID(TEST_USER_ID), "test@example.com", "测试用户")`; a separate `other_auth_header` returns a second UUID. No test contacts Supabase or Render.

```python
def test_create_session_returns_raw_token_once(client):
    response = client.post("/api/intake/sessions", json={
        "purpose": "self_use", "consent_version": "privacy-2026-08"
    })
    assert response.status_code == 201
    assert response.json()["expires_in_seconds"] == 86400
    assert response.json()["session_token"]


def test_wrong_session_token_is_uniform_404(client, session):
    response = client.post(
        f"/api/intake/sessions/{session.id}/preview",
        headers={"X-Analysis-Session": "wrong"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "分析项目不存在或已过期。"}


def test_convert_uses_authenticated_user_not_request_body(client, session, auth_header):
    response = client.post(
        f"/api/intake/sessions/{session.id}/convert",
        headers={**auth_header, "X-Analysis-Session": session.raw_token},
        json={},
    )
    assert response.status_code == 200
    assert response.json()["owner_user_id"] == TEST_USER_ID
```

- [ ] **Step 2: Run and verify route failures**

```bash
pytest tests/api/test_intake_routes.py -q
```

Expected: 404 because the router is not registered.

- [ ] **Step 3: Implement session and input endpoints**

Return status 201 for session/input creation. Store only a token hash. For URL input, store metadata with `processing_status='manual_review'`; do not fetch the site in this phase. For text input, store the validated text with `processing_status='manual_review'`.

Hash the trusted request source with `HMAC-SHA256(ABUSE_HASH_SALT, request.client.host)` before persistence; never store the raw address. Enforce 10 session creations/hour/source, 30 text-or-URL inputs/hour/source, 10 file uploads/hour/source, and 20 preview generations/hour/session. Return HTTP 429 with `Retry-After` and the uniform message `操作太频繁，请稍后再试。`. Refuse to start if `ABUSE_HASH_SALT` is missing outside the test environment.

- [ ] **Step 4: Implement file and field endpoints**

Read upload bytes with a hard 20 MiB + 1 byte cap, validate before Storage upload, and insert metadata only after a successful upload. If database insertion fails, delete the just-uploaded object.

Field confirmation derives the unit server-side. It first inserts an immutable row in `project_field_evidence`, then upserts the canonical `project_fields` row with `selected_evidence_id`. Existing evidence rows are never overwritten, so later parser/OCR/AI candidates can disagree without losing provenance. Use `confirmation_status='corrected'` if the chosen value differs from an extracted candidate, `confirmed` for an unchanged/manual value, `conflict` while two unconfirmed candidates disagree, and `unknown` with JSON null.

- [ ] **Step 5: Implement preview and conversion endpoints**

Lock `purpose` on the first preview, calculate and persist `free-preview-v1`, and return a stable JSON contract. Conversion requires both the anonymous session token and authenticated Supabase user. `GET /projects/{property_id}` requires authentication and selects by `owner_user_id=user.user_id`.

- [ ] **Step 6: Add bounded opportunistic retention cleanup**

On application startup and after each successful session creation, schedule one cleanup pass capped at 100 sessions. The pass calls `expire_sessions()`, then deletes only the returned Storage paths. Expired sessions become inaccessible immediately from the SQL predicate even if the Free Render service is asleep; physical deletion occurs automatically on the next API wake. Document this staging limitation explicitly: a continuously scheduled cleanup mechanism is required before public launch if deletion must occur within a strict wall-clock SLA.

- [ ] **Step 7: Register the router and run tests**

```python
# backend/app/main.py
from .routes.intake import router as intake_router

app.include_router(intake_router)
```

Run:

```bash
pytest tests/api/test_intake_routes.py tests/unit/test_intake_*.py tests/unit/test_completeness.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/app/routes/intake.py tests/api/conftest.py tests/api/test_intake_routes.py
git commit -m "feat: expose anonymous property intake API"
```

---

### Task 7: Build the Mobile-First Intake Page

**Files:**
- Create: `web/property-analysis.html`
- Create: `web/property-analysis.css`
- Create: `web/js/api-client.js`
- Create: `web/js/property-intake.js`
- Create: `tests/web/property-intake.spec.js`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `web/index.html:55-65`
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: Task 6 endpoint contracts.
- Produces: `createSession()`, `addTextOrUrlInput()`, `uploadFiles()`, `confirmField()`, `generatePreview()`, and `convertSession()` in `api-client.js`; UI states `purpose`, `submit`, `confirm`, `preview`, `register`, and `error`.

- [ ] **Step 1: Write failing Playwright tests**

Add `@playwright/test` as a dev dependency and a `test:web` script that runs `playwright test tests/web --project=chromium`. Configure the test to use a local static server and mocked `/api/intake/*` responses; it must not contact staging.

```javascript
test("anonymous user reaches free preview on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/property-analysis.html");
  await page.getByLabel("投资出租").check();
  await page.getByLabel("房源链接或说明").fill("大阪市北区，售价3500万日元，45.2平方米");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByLabel("专有面积（平方米）").fill("45.2");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.getByRole("heading", { name: "免费项目预览" })).toBeVisible();
  await expect(page.getByText("法律与交易资料")).toBeVisible();
});

test("upload error keeps entered fields and focuses message", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.setInputFiles("#propertyFiles", {
    name: "bad.exe", mimeType: "application/octet-stream", buffer: Buffer.from("bad")
  });
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await expect(page.getByRole("alert")).toContainText("仅支持 PDF、JPG、PNG");
});
```

- [ ] **Step 2: Run tests and verify page failure**

```bash
npx playwright test tests/web/property-intake.spec.js --project=chromium
```

Expected: navigation returns 404 or heading is missing.

- [ ] **Step 3: Build semantic five-step HTML**

Use one visible `<h1>`, a `<fieldset>` with labeled purpose radios, labeled URL/text and file inputs, an `<ol>` progress indicator, a `<dl>` for source evidence, `<meter>` plus text for completeness, and `role="alert"`/`aria-live="polite"` status regions. All form controls need visible labels; the primary action must remain visible at `390x844` without showing the account form first.

- [ ] **Step 4: Implement API and state modules**

Store only `{sessionId, rawToken, expiresAt}` in `sessionStorage`, never `localStorage`. Send the raw token only through `X-Analysis-Session`. Render user or source text with `textContent`, not `innerHTML`. On registration, obtain the existing Supabase access token, call `convertSession()`, then remove the anonymous token from `sessionStorage`.

- [ ] **Step 5: Implement responsive and accessible states**

Use existing color variables where available. Ensure 44px primary controls, visible `:focus-visible`, reduced-motion support, no horizontal scroll at 390px, a text summary beside every completeness meter, and keyboard return focus after dialogs. Preserve entered fields on retryable errors.

- [ ] **Step 6: Add the home-page entry and run browser tests**

Add a primary link under the existing hero copy:

```html
<a class="primary-product-link" href="property-analysis.html">分析一个日本房产</a>
```

Run:

```bash
npx playwright test tests/web/property-intake.spec.js --project=chromium
node --check web/js/api-client.js
node --check web/js/property-intake.js
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add web/property-analysis.html web/property-analysis.css web/js tests/web/property-intake.spec.js web/index.html web/styles.css
git commit -m "feat: add mobile property analysis intake"
```

---

### Task 8: Verify Staging Security, Retention, and Deployment

**Files:**
- Create: `tests/smoke/test_intake_contract.py`
- Modify: `docs/supabase-setup.md`
- Modify: `docs/data-warehouse-architecture.md`

**Interfaces:**
- Consumes: all Phase 1 components.
- Produces: verified `zoubeacon-staging` migration, private bucket, Render secrets, live API, and static page.

- [ ] **Step 1: Add offline contract checks**

```python
def test_frontend_never_contains_service_role_or_owner_assignment():
    content = "\n".join(path.read_text(encoding="utf-8") for path in WEB.rglob("*.js"))
    assert "SUPABASE_SERVICE_ROLE_KEY" not in content
    assert 'owner_user_id' not in content


def test_intake_page_uses_session_storage_not_local_storage():
    content = (WEB / "js" / "property-intake.js").read_text(encoding="utf-8")
    assert "sessionStorage" in content
    assert "localStorage" not in content
```

- [ ] **Step 2: Run the complete offline suite**

```bash
pytest tests/unit tests/api tests/smoke -q
PYTHONPYCACHEPREFIX=/tmp/zoubeacon-pycache python3 -m compileall -q backend
node --check web/app.js
node --check web/js/api-client.js
node --check web/js/property-intake.js
```

Expected: every command exits 0. Do not claim SQL or browser verification from these commands.

- [ ] **Step 3: Apply only migration 004 to `zoubeacon-staging`**

Before applying, verify:

```bash
cat supabase/.temp/project-ref
```

Expected: exactly `fnogxuytbabxmqousifh`.

Then run:

```bash
npx supabase db push --linked --include-all
```

Verify with:

```bash
backend/.venv/bin/python scripts/run_sql_file.py \
  --database-url-env STAGING_DATABASE_URL \
  tests/sql/test_property_intake_schema.sql
```

Expected: exit 0. Stop if the project ref differs or if the CLI proposes destructive SQL.

- [ ] **Step 4: Create and verify the private Storage bucket**

Create `property-intake` in `zoubeacon-staging` with public access disabled and a 20 MiB file-size limit. Do not add anonymous Storage policies. Verify an anonymous request cannot list or download objects.

- [ ] **Step 5: Configure existing Render staging API**

Add `SUPABASE_SERVICE_ROLE_KEY`, `INTAKE_BUCKET=property-intake`, and a newly generated `ABUSE_HASH_SALT` to `zouseeking-api-staging`. Keep the service on the Free plan and trigger one deploy. Never add these secrets to `render.yaml`, `web/config.js`, logs, screenshots, or Git.

- [ ] **Step 6: Run live smoke tests without real user documents**

Use a synthetic fixture marked `synthetic_fixture` to verify:

1. anonymous session creation;
2. text input creation;
3. valid synthetic PDF upload;
4. manual field confirmation;
5. preview generation;
6. registration conversion to test user A;
7. denial for test user B;
8. repeated conversion does not create a second property;
9. an expired anonymous fixture is selected for cleanup;
10. `/health/live` and `/health/ready` return 200.

Delete only the synthetic smoke-test objects and rows created by this task after recording assertions. Do not delete user data.

- [ ] **Step 7: Run real-browser acceptance**

Test Chromium desktop and `390x844` mobile for the happy path, invalid file, expired session, API failure, keyboard navigation, visible labels, focus, and console errors.

- [ ] **Step 8: Update docs and commit**

Document the deployed endpoint, bucket privacy, 24-hour retention, synthetic smoke test, and exactly what Phase 1 does not yet calculate.

```bash
git add tests/smoke/test_intake_contract.py docs/supabase-setup.md docs/data-warehouse-architecture.md
git commit -m "docs: verify property intake staging flow"
```

## Phase 1 Definition of Done

- All Task 1–8 tests pass at their stated level.
- `zoubeacon-staging` contains migration 004 and no production project was changed.
- Render remains Free and uses the existing API/static services.
- An anonymous user can submit text, URL metadata, PDF, JPG, or PNG and receive a free preview.
- Every confirmed field records a source input or the explicit locator `用户手动填写`, plus a server-derived unit.
- Registration atomically creates one user-owned residential property.
- Another user cannot discover or read that project.
- The UI explicitly labels automatic extraction, market comparison, tax amounts, legal analysis, and the complete report as later phases rather than fabricating results.
- Anonymous access expires at 24 hours; staging purges expired objects on the next API wake, and documentation records this Free-plan limitation.
