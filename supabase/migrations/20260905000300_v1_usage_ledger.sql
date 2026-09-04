-- V1 usage ledger and quota counters for the trusted usage metering path.
--
-- All usage facts are recorded by the trusted server path; the browser never
-- writes usage state. Events are append-only and deduplicated by fingerprint
-- plus client idempotency key, so retries and queue/mail redeliveries never
-- double-meter one request. Records cannot be overwritten; corrections are
-- new reversal events that reference the original event.
--
-- Period keys are UTC+8 calendar buckets: 'YYYY-MM' (month) or 'YYYY-MM-DD'
-- (day), bucket end exclusive. Quota counters are mutated only through atomic
-- conditional server-side updates (consumed + reserved + requested <= limit,
-- otherwise 429 with no counter change); this migration supplies the
-- cardinality constraints, uniqueness, append-only guards, indexes and RLS.
--
-- RLS scope contract:
--   * scope_key 'user:<uuid>' rows are readable by that authenticated user;
--   * scope_key 'org:<uuid>' rows are readable by members of that
--     organization (exists in organization_members joined to organizations).
-- Depends on the preceding V1 migration 20260905000100, which creates
-- public.organizations and public.organization_members.

do $$
declare
  required_table text;
begin
  foreach required_table in array array[
    'organizations', 'organization_members'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing usage ledger prerequisite: public.%', required_table;
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- usage_quotas: one counter row per (scope, usage_kind, UTC+8 period).
-- ---------------------------------------------------------------------------
create table if not exists public.usage_quotas (
  id uuid primary key default gen_random_uuid(),
  -- Server-generated ownership handle, e.g. 'user:<uuid>' or 'org:<uuid>'.
  scope_key text not null,
  usage_kind text not null,
  period_key text not null,
  limit_units int not null,
  consumed_units int not null default 0,
  reserved_units int not null default 0,
  -- Scheduled counter reset point (e.g. next UTC+8 00:00 for daily plans).
  reset_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint usage_quotas_scope_key_format check (
    scope_key ~ '^(user|org):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  ),
  constraint usage_quotas_period_key_format check (
    period_key ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
    or period_key ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
  ),
  constraint usage_quotas_usage_kind_allowed check (usage_kind in (
    'query', 'report', 'stats_query', 'export_row', 'subscription_slot'
  )),
  constraint usage_quotas_counts_nonnegative check (
    limit_units >= 0 and consumed_units >= 0 and reserved_units >= 0
  ),
  constraint usage_quotas_scope_kind_period_unique unique (scope_key, usage_kind, period_key),
  -- Hard limit enforcement lives in the server layer (atomic conditional
  -- update, 429 when consumed + reserved + requested > limit). The 100000
  -- slack keeps reversals and administrative corrections from deadlocking the
  -- ledger; this check only keeps counter sums inside sane cardinality.
  constraint usage_quotas_capacity_bound check (
    consumed_units + reserved_units <= limit_units + 100000
  )
);

create index if not exists idx_usage_quotas_scope_period
  on public.usage_quotas(scope_key, period_key);

drop trigger if exists set_usage_quotas_updated_at on public.usage_quotas;
create trigger set_usage_quotas_updated_at
before update on public.usage_quotas
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- usage_events: append-only audit trail of every metered operation.
-- ---------------------------------------------------------------------------
create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  scope_key text not null,
  usage_kind text not null,
  operation text not null,
  units int not null,
  period_key text not null,
  -- Client-supplied Idempotency-Key and server-derived request fingerprint.
  idempotency_key text,
  fingerprint text,
  -- Links a commit/release event to its original reserve reservation.
  reservation_key text,
  -- Set only on reversal events: the id of the original event being reversed.
  reversal_of uuid references public.usage_events(id),
  -- Server-resolved actor; null after the auth user is deleted.
  actor_user_id uuid references auth.users(id) on delete set null,
  -- Optional human-readable reason for reversals or administrative events.
  note text,
  created_at timestamptz not null default now(),
  constraint usage_events_scope_key_format check (
    scope_key ~ '^(user|org):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  ),
  constraint usage_events_period_key_format check (
    period_key ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'
    or period_key ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
  ),
  constraint usage_events_usage_kind_allowed check (usage_kind in (
    'query', 'report', 'stats_query', 'export_row', 'subscription_slot'
  )),
  constraint usage_events_operation_allowed check (operation in (
    'consume', 'reserve', 'commit', 'release', 'reversal'
  )),
  constraint usage_events_units_positive check (units > 0),
  constraint usage_events_note_length check (
    note is null or char_length(note) <= 500
  ),
  constraint usage_events_reversal_target check (
    (operation = 'reversal' and reversal_of is not null)
    or (operation <> 'reversal' and reversal_of is null)
  )
);

-- Same fingerprint on the same (scope, kind, operation) is recorded once;
-- repeated identical requests return duplicate instead of double-metering.
create unique index if not exists uq_usage_events_fingerprint
  on public.usage_events(scope_key, usage_kind, operation, fingerprint)
  where fingerprint is not null;

create index if not exists idx_usage_events_scope_period_created
  on public.usage_events(scope_key, period_key, created_at);

-- Events are immutable facts: forbid in-place UPDATE and DELETE entirely.
create or replace function public.prevent_usage_event_mutation()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'usage_events is append-only; delete is forbidden';
  end if;
  raise exception 'usage_events is append-only; update is forbidden';
end;
$$;
revoke all on function public.prevent_usage_event_mutation() from public, anon, authenticated;

drop trigger if exists enforce_usage_events_append_only on public.usage_events;
create trigger enforce_usage_events_append_only
before update or delete on public.usage_events
for each row execute function public.prevent_usage_event_mutation();

-- ---------------------------------------------------------------------------
-- usage_idempotency: registry mapping client idempotency keys and request
-- fingerprints to processed events (server-side lookup table only).
-- ---------------------------------------------------------------------------
create table if not exists public.usage_idempotency (
  id uuid primary key default gen_random_uuid(),
  scope_key text not null,
  usage_kind text not null,
  operation text not null,
  idempotency_key text not null,
  fingerprint text,
  processed_at timestamptz not null default now(),
  constraint usage_idempotency_scope_key_format check (
    scope_key ~ '^(user|org):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  ),
  constraint usage_idempotency_usage_kind_allowed check (usage_kind in (
    'query', 'report', 'stats_query', 'export_row', 'subscription_slot'
  )),
  constraint usage_idempotency_operation_allowed check (operation in (
    'consume', 'reserve', 'commit', 'release', 'reversal'
  )),
  constraint usage_idempotency_fingerprint_unique unique (
    scope_key, usage_kind, operation, fingerprint
  ),
  constraint usage_idempotency_client_key_unique unique (
    scope_key, usage_kind, operation, idempotency_key
  )
);

-- ---------------------------------------------------------------------------
-- Row level security.
-- ---------------------------------------------------------------------------
alter table public.usage_quotas enable row level security;
alter table public.usage_events enable row level security;
alter table public.usage_idempotency enable row level security;

revoke all on public.usage_quotas, public.usage_events, public.usage_idempotency
from anon, authenticated;

-- authenticated may read only rows whose scope belongs to them; writes are
-- reserved for the trusted service_role path.
grant select on public.usage_quotas, public.usage_events to authenticated;

grant all on public.usage_quotas, public.usage_events, public.usage_idempotency
to service_role;

create policy "users can read own usage quotas"
on public.usage_quotas for select to authenticated
using (
  starts_with(scope_key, 'user:' || (select auth.uid())::text)
  or exists (
    select 1
    from public.organization_members om
    join public.organizations o on o.id = om.organization_id
    where om.user_id = (select auth.uid())
      and starts_with(usage_quotas.scope_key, 'org:' || o.id::text)
  )
);

create policy "users can read own usage events"
on public.usage_events for select to authenticated
using (
  starts_with(scope_key, 'user:' || (select auth.uid())::text)
  or exists (
    select 1
    from public.organization_members om
    join public.organizations o on o.id = om.organization_id
    where om.user_id = (select auth.uid())
      and starts_with(usage_events.scope_key, 'org:' || o.id::text)
  )
);

-- usage_idempotency carries no direct policy: it is fully server-managed and
-- authenticated/anon roles hold no grants on it.
