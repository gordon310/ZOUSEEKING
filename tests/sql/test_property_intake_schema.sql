-- Osaka property-intake schema assertions.
-- Run against a disposable Supabase/PostgreSQL database only.
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
end $$;
