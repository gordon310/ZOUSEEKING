-- P1.3 source registry: collection_sources (20260906000100).
--
-- One row per authorised collection source, keyed by the same local
-- configuration identity used in collection_runs (source_key =
-- "<prefix>/<config-stem>", e.g. jphouse_23ku/shibuya).  This is the
-- roadmap P1.3 "来源登记" record: rights confirmation, robots/terms
-- summary, rate-limit and retention policy are captured here so a
-- scheduler/enqueue gate can refuse un-authorised sources (AGENTS.md:
-- rights_confirmed=yes is required; a URL alone does not prove
-- permission).  cadence documents the intended refresh rhythm; a later
-- scheduler unit may read it instead of a hard-coded weekly.
--
-- Internal domain: reached by the back-office API and trusted services
-- under service_role only; anon/authenticated get zero privileges and no
-- policies (same access contract as collection_runs 20260905000601).
--
-- Prerequisites (earlier migrations, applied before this file):
--   auth.users (managed Supabase schema)

do $$
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;
  if to_regclass('public.collection_sources') is not null then
    raise exception 'collection sources migration already applied: public.collection_sources';
  end if;
end $$;

create table if not exists public.collection_sources (
  source_key text primary key,
  source_type text not null,
  display_name text,
  source_url text,
  cadence text not null default 'weekly',
  rights_confirmed boolean not null default false,
  robots_policy text,
  rate_limit_note text,
  retention_policy text,
  enabled boolean not null default true,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint collection_sources_source_type_allowed check (
    source_type in (
      'authorized_csv', 'official_open', 'partner',
      'user_submitted', 'aggregate_authorized'
    )
  ),
  constraint collection_sources_cadence_allowed check (
    cadence in ('daily', 'weekly', 'monthly', 'event')
  ),
  constraint collection_sources_url_or_note check (
    source_url is not null or notes is not null
  )
);

create trigger set_collection_sources_updated_at
  before update on public.collection_sources
  for each row execute function public.set_updated_at();

-- Traced query shapes: registry listing by family prefix and enabled
-- sources (scheduler feed enumeration).
create index if not exists idx_collection_sources_enabled
  on public.collection_sources (enabled, source_key);

alter table public.collection_sources enable row level security;

revoke all on public.collection_sources from anon, authenticated;

grant all privileges on table public.collection_sources to service_role;

comment on table public.collection_sources is
  'Authorised collection source registry (P1.3 来源登记): one row per'
  ' source_key with rights/robots/rate-limit/retention confirmation and'
  ' intended cadence. Internal domain - service_role only.';

comment on column public.collection_sources.rights_confirmed is
  'Explicit authorisation/terms review completed (AGENTS: rights_confirmed'
  ' = yes required before live collection); a URL alone is not permission.';

comment on column public.collection_sources.cadence is
  'Intended refresh rhythm: daily/weekly/monthly/event. A later scheduler'
  ' unit reads this instead of a hard-coded cadence.';
