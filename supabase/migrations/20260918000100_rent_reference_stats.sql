-- Official e-Stat rent reference observations. Additive forward migration only.
create table if not exists public.rent_reference_stats (
  id uuid primary key default gen_random_uuid(),
  source_key text not null,
  source_label text not null,
  prefecture text not null,
  city text not null,
  ward text not null default '__not_subdivided__',
  geo_level text not null check (geo_level in ('prefecture', 'city', 'ward', 'special_wards')),
  scope_label text not null,
  rent_jpy_per_sqm_month numeric(18,6) not null check (rent_jpy_per_sqm_month > 0),
  rent_jpy_per_sqm_month_excl_zero numeric(18,6) check (rent_jpy_per_sqm_month_excl_zero is null or rent_jpy_per_sqm_month_excl_zero > 0),
  survey_year smallint not null check (survey_year between 2005 and 2200),
  survey_label text not null,
  observed_month text check (observed_month is null or observed_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  source_url text not null,
  license_label text not null,
  fetched_at timestamptz not null,
  constraint rent_reference_stats_geo_shape check (
    (geo_level = 'prefecture' and city = '__not_subdivided__' and ward = '__not_subdivided__')
    or (geo_level = 'special_wards' and prefecture = '东京都' and city = '东京23区' and ward = '__not_subdivided__')
    or (geo_level in ('city', 'ward') and city <> '__not_subdivided__')
  )
);

create unique index if not exists uq_rent_reference_stats_natural_key
  on public.rent_reference_stats(source_key, prefecture, city, ward, scope_label, survey_year, coalesce(observed_month, ''));
create index if not exists idx_rent_reference_stats_region
  on public.rent_reference_stats(prefecture, city, ward, source_key, survey_year, observed_month);

alter table public.rent_reference_stats enable row level security;
revoke all on public.rent_reference_stats from anon, authenticated;
grant select on public.rent_reference_stats to authenticated;
grant all privileges on public.rent_reference_stats to service_role;
create policy "active organization members can read rent references"
  on public.rent_reference_stats for select to authenticated
  using (exists (
    select 1 from public.organization_members om
    where om.user_id = auth.uid() and om.status = 'active'
  ));

comment on table public.rent_reference_stats is
  'Official e-Stat rent observations; values are numeric and retain source/provenance metadata.';
