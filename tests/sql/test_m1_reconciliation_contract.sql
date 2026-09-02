-- M1 reconciliation acceptance contract.
-- Safe for local, isolated restore, and staging: catalog assertions only.

do $$
declare
  missing_columns text[];
  rls_disabled_tables text[];
  anon_grant_count integer;
  authenticated_grant_count integer;
  service_grant_count integer;
begin
  select array_agg(required.table_name || '.' || required.column_name order by 1)
    into missing_columns
  from (
    values
      ('sources', 'data_class'),
      ('sources', 'source_period'),
      ('sources', 'observed_at'),
      ('sources', 'transformation_version'),
      ('sources', 'limitations'),
      ('property_reports', 'data_class'),
      ('property_reports', 'report_status'),
      ('property_reports', 'report_version'),
      ('analysis_metrics', 'data_class'),
      ('analysis_metrics', 'report_status'),
      ('risk_findings', 'data_class'),
      ('risk_findings', 'report_status')
  ) as required(table_name, column_name)
  where not exists (
    select 1
    from information_schema.columns actual
    where actual.table_schema = 'public'
      and actual.table_name = required.table_name
      and actual.column_name = required.column_name
  );

  if missing_columns is not null then
    raise exception 'missing M1 columns: %', missing_columns;
  end if;

  if not exists (
    select 1
    from supabase_migrations.schema_migrations
    where version = '20260902000100'
  ) then
    raise exception 'missing M1 reconciliation migration ledger entry';
  end if;

  select array_agg(c.relname order by c.relname)
    into rls_disabled_tables
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public'
    and c.relkind = 'r'
    and c.relname = any (array[
      'queries', 'query_field_options', 'generation_jobs',
      'property_reports', 'data_sources', 'user_profiles', 'sources',
      'properties', 'residential_details', 'new_build_details',
      'commercial_investment_details', 'evidences', 'analysis_metrics',
      'risk_findings', 'policy_documents', 'product_events',
      'analysis_sessions', 'project_inputs', 'project_field_evidence',
      'project_fields', 'free_previews', 'intake_rate_limits'
    ])
    and not c.relrowsecurity;

  if rls_disabled_tables is not null then
    raise exception 'M1 tables without RLS: %', rls_disabled_tables;
  end if;

  select count(*) into anon_grant_count
  from information_schema.role_table_grants
  where grantee = 'anon' and table_schema = 'public';

  select count(*) into authenticated_grant_count
  from information_schema.role_table_grants
  where grantee = 'authenticated' and table_schema = 'public';

  select count(*) into service_grant_count
  from information_schema.role_table_grants
  where grantee = 'service_role' and table_schema = 'public';

  if anon_grant_count <> 1 then
    raise exception 'anon public grant count %, expected 1', anon_grant_count;
  end if;
  if authenticated_grant_count <> 15 then
    raise exception 'authenticated public grant count %, expected 15', authenticated_grant_count;
  end if;
  if service_grant_count <> 154 then
    raise exception 'service_role public grant count %, expected 154', service_grant_count;
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'properties'
      and cmd in ('INSERT', 'UPDATE', 'DELETE', 'ALL')
  ) then
    raise exception 'authenticated property write policy remains after reconciliation';
  end if;

  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'query_field_options'
      and policyname = 'public can read active field options'
      and cmd = 'SELECT'
      and roles = array['anon']::name[]
  ) then
    raise exception 'active anonymous field-option policy is missing';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and roles && array['anon', 'authenticated']::name[]
  ) then
    raise exception 'property-intake Storage must remain service-only';
  end if;

end
$$;
