-- Property photo location and owner-scoped investigation naming.
-- Forward-only migration for the FastAPI property-intake path.

alter table public.analysis_sessions
  add column if not exists project_name text not null default '',
  add column if not exists latitude numeric(9,6),
  add column if not exists longitude numeric(10,6),
  add column if not exists location_accuracy_m numeric(10,2),
  add column if not exists location_source text not null default '',
  add column if not exists location_captured_at timestamptz,
  add column if not exists location_consent_version text not null default '',
  add column if not exists address_candidate text not null default '',
  add column if not exists address_source text not null default 'manual',
  add column if not exists address_precision text not null default '';

alter table public.properties
  add column if not exists project_name text not null default '',
  add column if not exists latitude numeric(9,6),
  add column if not exists longitude numeric(10,6),
  add column if not exists location_accuracy_m numeric(10,2),
  add column if not exists location_source text not null default '',
  add column if not exists location_captured_at timestamptz,
  add column if not exists address_source text not null default 'manual',
  add column if not exists address_precision text not null default '';

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'analysis_sessions_location_latitude_range'
  ) then
    alter table public.analysis_sessions
      add constraint analysis_sessions_location_latitude_range
      check (latitude is null or latitude between -90 and 90);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'analysis_sessions_location_longitude_range'
  ) then
    alter table public.analysis_sessions
      add constraint analysis_sessions_location_longitude_range
      check (longitude is null or longitude between -180 and 180);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'analysis_sessions_location_accuracy_positive'
  ) then
    alter table public.analysis_sessions
      add constraint analysis_sessions_location_accuracy_positive
      check (location_accuracy_m is null or location_accuracy_m > 0);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'analysis_sessions_location_source_allowed'
  ) then
    alter table public.analysis_sessions
      add constraint analysis_sessions_location_source_allowed
      check (location_source in ('', 'device_geolocation'));
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'analysis_sessions_address_source_allowed'
  ) then
    alter table public.analysis_sessions
      add constraint analysis_sessions_address_source_allowed
      check (address_source in ('manual', 'gsi_reverse_geocoder', 'unavailable'));
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'properties_location_latitude_range'
  ) then
    alter table public.properties
      add constraint properties_location_latitude_range
      check (latitude is null or latitude between -90 and 90);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'properties_location_longitude_range'
  ) then
    alter table public.properties
      add constraint properties_location_longitude_range
      check (longitude is null or longitude between -180 and 180);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'properties_location_accuracy_positive'
  ) then
    alter table public.properties
      add constraint properties_location_accuracy_positive
      check (location_accuracy_m is null or location_accuracy_m > 0);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'properties_location_source_allowed'
  ) then
    alter table public.properties
      add constraint properties_location_source_allowed
      check (location_source in ('', 'device_geolocation'));
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'properties_address_source_allowed'
  ) then
    alter table public.properties
      add constraint properties_address_source_allowed
      check (address_source in ('manual', 'gsi_reverse_geocoder', 'unavailable'));
  end if;
end $$;

create index if not exists idx_properties_owner_address
  on public.properties(owner_user_id, address_normalized)
  where owner_user_id is not null and address_normalized <> '';

create unique index if not exists idx_properties_owner_project_name
  on public.properties(owner_user_id, project_name)
  where owner_user_id is not null and project_name <> '';
