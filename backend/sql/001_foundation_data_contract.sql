-- 小象避坑第一阶段：可追溯数据契约。
-- 本迁移只新增基础表和约束，不删除或覆盖现有业务表。

create extension if not exists pgcrypto;

do $$
begin
  create type public.data_class as enum (
    'verified_observation',
    'scraped_aggregate',
    'modeled_estimate',
    'synthetic_fixture',
    'user_submitted'
  );
exception when duplicate_object then null;
end $$;

create table if not exists public.sources (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  source_type text not null,
  url text not null,
  permission_status text not null default 'unverified',
  update_frequency text not null default 'manual',
  parser_version text not null default 'unparsed',
  last_success_at timestamptz,
  last_error_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (url)
);

create table if not exists public.properties (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid references auth.users(id) on delete set null,
  workspace_id uuid,
  project_type text not null check (project_type in ('residential', 'new_build', 'commercial_investment')),
  prefecture text not null default '',
  city text not null default '',
  ward text not null default '',
  station text not null default '',
  address_normalized text not null default '',
  building_name text not null default '',
  building_year int check (building_year is null or building_year between 1800 and 2200),
  area_sqm numeric(12,2) check (area_sqm is null or area_sqm >= 0),
  asking_price numeric(18,2) check (asking_price is null or asking_price >= 0),
  price_currency char(3) not null default 'JPY',
  data_class public.data_class not null default 'user_submitted',
  confidence text not null default 'unreviewed' check (confidence in ('high', 'medium', 'low', 'unreviewed')),
  observed_at timestamptz,
  source_id uuid references public.sources(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_properties_location_type
  on public.properties(prefecture, city, ward, project_type);
create index if not exists idx_properties_owner
  on public.properties(owner_user_id);
create index if not exists idx_properties_observed_at
  on public.properties(observed_at desc);

create table if not exists public.residential_details (
  property_id uuid primary key references public.properties(id) on delete cascade,
  layout text not null default '',
  floor text not null default '',
  management_fee_jpy numeric(18,2) check (management_fee_jpy is null or management_fee_jpy >= 0),
  repair_reserve_jpy numeric(18,2) check (repair_reserve_jpy is null or repair_reserve_jpy >= 0),
  monthly_rent_jpy numeric(18,2) check (monthly_rent_jpy is null or monthly_rent_jpy >= 0),
  fixed_asset_tax_jpy numeric(18,2) check (fixed_asset_tax_jpy is null or fixed_asset_tax_jpy >= 0),
  details jsonb not null default '{}'::jsonb
);

create table if not exists public.new_build_details (
  property_id uuid primary key references public.properties(id) on delete cascade,
  developer_name text not null default '',
  contractor_name text not null default '',
  project_status text not null default 'unknown',
  launch_date date,
  expected_completion_date date,
  handover_date date,
  phase_name text not null default '',
  payment_schedule jsonb not null default '{}'::jsonb,
  details jsonb not null default '{}'::jsonb
);

create table if not exists public.commercial_investment_details (
  property_id uuid primary key references public.properties(id) on delete cascade,
  tenant_status text not null default 'unknown',
  monthly_rent_jpy numeric(18,2) check (monthly_rent_jpy is null or monthly_rent_jpy >= 0),
  lease_start date,
  lease_end date,
  rent_guarantee text not null default '',
  management_company text not null default '',
  operating_permit_status text not null default 'unknown',
  details jsonb not null default '{}'::jsonb
);

create table if not exists public.evidences (
  id uuid primary key default gen_random_uuid(),
  property_id uuid references public.properties(id) on delete cascade,
  source_id uuid references public.sources(id) on delete set null,
  snapshot_id uuid,
  field_name text not null,
  locator text not null default '',
  extracted_value jsonb not null default 'null'::jsonb,
  extraction_method text not null default 'manual',
  observed_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_evidences_property_field
  on public.evidences(property_id, field_name);

create table if not exists public.analysis_metrics (
  id uuid primary key default gen_random_uuid(),
  property_id uuid references public.properties(id) on delete cascade,
  metric_name text not null,
  metric_value numeric,
  unit text not null,
  currency char(3),
  calculation_version text not null,
  assumption_set jsonb not null default '{}'::jsonb,
  calculated_at timestamptz not null default now(),
  unique(property_id, metric_name, calculation_version)
);

create table if not exists public.risk_findings (
  id uuid primary key default gen_random_uuid(),
  property_id uuid references public.properties(id) on delete cascade,
  category text not null,
  severity text not null check (severity in ('info', 'low', 'medium', 'high', 'critical')),
  basis text not null,
  required_evidence jsonb not null default '[]'::jsonb,
  action text not null,
  confidence text not null default 'unreviewed',
  calculation_version text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.policy_documents (
  id uuid primary key default gen_random_uuid(),
  policy_key text not null,
  title text not null,
  jurisdiction text not null,
  authority text not null,
  source_url text not null,
  published_at date,
  effective_from date not null,
  effective_to date,
  status text not null default 'active',
  scope text not null default '',
  summary text not null default '',
  impact_categories jsonb not null default '[]'::jsonb,
  source_snapshot_id uuid,
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  unique(policy_key, effective_from)
);

create table if not exists public.product_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  workspace_id uuid,
  event_name text not null,
  project_type text,
  prefecture text,
  city text,
  budget_band text,
  risk_topics jsonb not null default '[]'::jsonb,
  outcome text,
  consent_scope text not null default 'internal_product_analytics',
  occurred_at timestamptz not null default now()
);

create index if not exists idx_product_events_occurred_at
  on public.product_events(occurred_at desc);
create index if not exists idx_product_events_segment
  on public.product_events(project_type, prefecture, city, occurred_at desc);
