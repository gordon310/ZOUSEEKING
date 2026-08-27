-- Osaka property intake: anonymous sessions, evidence-ready inputs, and previews.
-- Prerequisites: the foundation schema has created public.properties and
-- public.residential_details. This migration does not create or alter those
-- existing business tables.

do $$
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;
  if to_regclass('public.properties') is null then
    raise exception 'missing prerequisite table: public.properties';
  end if;
  if to_regclass('public.residential_details') is null then
    raise exception 'missing prerequisite table: public.residential_details';
  end if;
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'properties'
      and column_name in (
        'owner_user_id', 'project_type', 'prefecture', 'city', 'ward',
        'address_normalized', 'building_name', 'building_year', 'area_sqm',
        'asking_price', 'price_currency', 'data_class', 'confidence'
      )
    group by table_schema, table_name
    having count(*) = 13
  ) then
    raise exception 'incompatible prerequisite columns: public.properties';
  end if;
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'residential_details'
      and column_name in (
        'property_id', 'management_fee_jpy', 'repair_reserve_jpy',
        'monthly_rent_jpy', 'details'
      )
    group by table_schema, table_name
    having count(*) = 5
  ) then
    raise exception 'incompatible prerequisite columns: public.residential_details';
  end if;
end $$;

create table if not exists public.analysis_sessions (
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

create table if not exists public.project_inputs (
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

create table if not exists public.project_field_evidence (
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
  constraint project_field_evidence_field_name_allowed check (field_name in (
    'building_name', 'address', 'ward', 'station', 'walk_minutes',
    'building_year', 'total_units', 'floor', 'orientation', 'area_sqm',
    'balcony_area_sqm', 'land_right', 'land_share', 'asking_price_jpy',
    'management_fee_jpy', 'repair_reserve_jpy', 'monthly_rent_jpy'
  )),
  created_at timestamptz not null default now(),
  unique (session_id, source_input_id, field_name, locator, normalized_value)
);

create table if not exists public.project_fields (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.analysis_sessions(id) on delete cascade,
  field_name text not null,
  selected_evidence_id uuid references public.project_field_evidence(id) on delete set null,
  confirmed_value jsonb,
  unit text,
  confirmation_status text not null default 'unreviewed'
    check (confirmation_status in ('unreviewed', 'confirmed', 'corrected', 'unknown', 'conflict')),
  constraint project_fields_field_name_allowed check (field_name in (
    'building_name', 'address', 'ward', 'station', 'walk_minutes',
    'building_year', 'total_units', 'floor', 'orientation', 'area_sqm',
    'balcony_area_sqm', 'land_right', 'land_share', 'asking_price_jpy',
    'management_fee_jpy', 'repair_reserve_jpy', 'monthly_rent_jpy'
  )),
  confirmed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (session_id, field_name)
);

create table if not exists public.free_previews (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null unique references public.analysis_sessions(id) on delete cascade,
  completeness jsonb not null,
  acquisition_costs jsonb not null,
  risk_summary jsonb not null,
  comparable_status text not null check (comparable_status in ('not_checked', 'sufficient', 'insufficient')),
  calculation_version text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.intake_rate_limits (
  abuse_key_hash char(64) not null,
  action text not null,
  window_started_at timestamptz not null,
  request_count integer not null default 1 check (request_count > 0),
  expires_at timestamptz not null,
  primary key (abuse_key_hash, action, window_started_at)
);

create index if not exists idx_analysis_sessions_owner
  on public.analysis_sessions(owner_user_id, created_at desc);
create index if not exists idx_analysis_sessions_expiry
  on public.analysis_sessions(expires_at)
  where status <> 'converted';
create index if not exists idx_project_inputs_session
  on public.project_inputs(session_id, created_at);
create index if not exists idx_project_field_evidence_session
  on public.project_field_evidence(session_id, field_name);
create index if not exists idx_project_fields_session
  on public.project_fields(session_id, field_name);
create index if not exists idx_intake_rate_limits_expiry
  on public.intake_rate_limits(expires_at);

alter table public.analysis_sessions enable row level security;
alter table public.project_inputs enable row level security;
alter table public.project_field_evidence enable row level security;
alter table public.project_fields enable row level security;
alter table public.free_previews enable row level security;
alter table public.intake_rate_limits enable row level security;

revoke all on public.analysis_sessions,
  public.project_inputs,
  public.project_field_evidence,
  public.project_fields,
  public.free_previews,
  public.intake_rate_limits
from anon, authenticated;

create or replace function public.set_intake_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_analysis_sessions_updated_at on public.analysis_sessions;
create trigger set_analysis_sessions_updated_at
before update on public.analysis_sessions
for each row execute function public.set_intake_updated_at();

drop trigger if exists set_project_fields_updated_at on public.project_fields;
create trigger set_project_fields_updated_at
before update on public.project_fields
for each row execute function public.set_intake_updated_at();

create or replace function public.prevent_intake_identity_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  jwt_role text := coalesce(current_setting('request.jwt.claim.role', true), '');
begin
  if current_user not in ('postgres', 'service_role', 'supabase_admin')
     and jwt_role not in ('service_role', 'supabase_admin') then
    if tg_op = 'INSERT'
       and (new.owner_user_id is not null or new.property_id is not null) then
      raise exception 'intake identity is server-managed';
    end if;
    if tg_op = 'UPDATE'
       and (
         new.owner_user_id is distinct from old.owner_user_id
         or new.property_id is distinct from old.property_id
         or new.token_hash is distinct from old.token_hash
         or new.expires_at is distinct from old.expires_at
         or new.converted_at is distinct from old.converted_at
       ) then
      raise exception 'intake identity is server-managed';
    end if;
  end if;
  if tg_op = 'UPDATE'
     and old.purpose_locked_at is not null
     and new.purpose is distinct from old.purpose then
    raise exception 'analysis purpose is locked';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_intake_identity on public.analysis_sessions;
create trigger protect_intake_identity
before insert or update on public.analysis_sessions
for each row execute function public.prevent_intake_identity_change();
