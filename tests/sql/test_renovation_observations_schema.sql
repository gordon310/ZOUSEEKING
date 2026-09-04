-- Renovation-observation intake schema assertions.
-- Run against a disposable Supabase/PostgreSQL database only.
do $$
declare
  required_constraint text;
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'analysis_sessions'
      and column_name = 'asset_type'
  ) then
    raise exception 'missing analysis_sessions.asset_type column';
  end if;

  if to_regclass('public.renovation_observations') is null then
    raise exception 'missing renovation_observations table';
  end if;

  if not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'renovation_observations'
      and c.relrowsecurity
  ) then
    raise exception 'RLS disabled for renovation_observations';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'renovation_observations'
      and roles::text like '%anon%'
  ) then
    raise exception 'anonymous REST policy exists on renovation_observations';
  end if;

  foreach required_constraint in array array[
    'renovation_observations_room_allowed',
    'renovation_observations_component_allowed',
    'renovation_observations_condition_allowed',
    'renovation_observations_scope_allowed',
    'renovation_observations_unique_scope'
  ] loop
    if not exists (
      select 1 from pg_constraint where conname = required_constraint
    ) then
      raise exception 'missing renovation constraint: %', required_constraint;
    end if;
  end loop;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'free_previews'
      and column_name = 'renovation_estimate'
  ) then
    raise exception 'missing free_previews.renovation_estimate column';
  end if;
end $$;
