-- Osaka property-intake schema assertions.
-- Run against a disposable Supabase/PostgreSQL database only.
do $$
declare
  required_table text;
  required_column text;
begin
  foreach required_table in array array[
    'analysis_sessions', 'project_inputs', 'project_field_evidence', 'project_fields', 'free_previews',
    'intake_rate_limits'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing intake table: %', required_table;
    end if;
    if not exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = required_table
        and c.relrowsecurity
    ) then
      raise exception 'RLS disabled for intake table: %', required_table;
    end if;
  end loop;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename in (
        'analysis_sessions', 'project_inputs', 'project_field_evidence', 'project_fields', 'free_previews'
      )
      and roles::text like '%anon%'
  ) then
    raise exception 'anonymous REST policy exists on private intake data';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conname = 'analysis_sessions_expires_after_creation'
  ) then
    raise exception '24-hour expiry constraint is missing';
  end if;

  foreach required_column in array array[
    'project_name', 'latitude', 'longitude', 'location_accuracy_m',
    'location_source', 'location_captured_at', 'address_source', 'address_precision'
  ] loop
    if not exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'properties'
        and column_name = required_column
    ) then
      raise exception 'missing properties column: %', required_column;
    end if;
  end loop;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'analysis_sessions'
      and column_name = 'address_candidate'
  ) then
    raise exception 'missing analysis_sessions address_candidate column';
  end if;

  if not exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and indexname = 'idx_properties_owner_project_name'
  ) then
    raise exception 'owner-scoped project name uniqueness index is missing';
  end if;
end $$;
