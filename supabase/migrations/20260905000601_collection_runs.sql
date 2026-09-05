-- V1 collection runs domain (20260905000601).
--
-- collection_runs: one row per collection execution against an authorized
-- data source, keyed by the local configuration identity (source_key, e.g.
-- the configs/jphouse_23ku/<ward>.json report identity) plus a coarse
-- source_type family. Rows are created in status 'queued' by the back-office
-- API (audited) and advanced to running/succeeded/failed/cancelled by the
-- future collection worker; this batch only enqueues - it never executes a
-- collection. rows_collected and snapshot_hash are filled by the worker.
--
-- Internal domain: the table is reached exclusively by the back-office API
-- and trusted services under service_role; anon/authenticated get zero table
-- privileges and no policies (same access contract as the finance/admin
-- batch 20260905000500).
--
-- Prerequisites (earlier migrations, applied before this file):
--   auth.users                          (managed Supabase schema)

do $$
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;
  if to_regclass('public.collection_runs') is not null then
    raise exception 'v1 collection runs migration already applied: public.collection_runs';
  end if;
end $$;

-- One run row per collection attempt. operator_user_id records which admin
-- queued the run (or which user-submitted trigger started it); it is
-- provenance, not ownership, so ON DELETE SET NULL keeps history readable
-- after an operator account is removed.
create table if not exists public.collection_runs (
  id uuid primary key default gen_random_uuid(),
  source_key text not null,
  source_type text not null,
  status text not null default 'queued',
  rows_collected integer not null default 0,
  snapshot_hash char(64),
  error_message text,
  operator_user_id uuid references auth.users(id) on delete set null,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  constraint collection_runs_source_type_allowed check (
    source_type in (
      'authorized_csv', 'official_open', 'partner',
      'user_submitted', 'aggregate_authorized'
    )
  ),
  constraint collection_runs_status_allowed check (
    status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')
  ),
  constraint collection_runs_rows_collected_nonnegative check (rows_collected >= 0),
  constraint collection_runs_completed_requires_started check (
    completed_at is null or started_at is not null
  )
);

-- Traced query shapes: a status queue scan (worker claim / ops dashboard)
-- and the per-source recent history (admin runs list for one source).
create index if not exists idx_collection_runs_status_created
  on public.collection_runs (status, created_at desc);
create index if not exists idx_collection_runs_source_created
  on public.collection_runs (source_key, created_at desc);

-- Row level security: internal domain only - service_role bypasses RLS via
-- table grants; anon/authenticated have no table privileges and no policies.
alter table public.collection_runs enable row level security;

revoke all on public.collection_runs from anon, authenticated;

grant all privileges on table public.collection_runs to service_role;

comment on table public.collection_runs is
  'One row per collection execution against an authorized data source, queued'
  'by the back-office API and advanced by the collection worker. The worker'
  'executor is a separate unit; this migration only defines the run ledger.';

comment on column public.collection_runs.source_key is
  'Local configuration identity of the collected source, e.g. the'
  'configs/jphouse_23ku/<ward>.json report identity.';

comment on column public.collection_runs.snapshot_hash is
  'Lowercase hex sha256 of the collected snapshot; raw payloads are never'
  'stored on this row.';

comment on column public.collection_runs.operator_user_id is
  'Admin (or submitting user) who queued the run; null when a service queued'
  'it. Provenance only - ON DELETE SET NULL.';
