-- 在 Supabase 测试项目执行。需要使用测试用户 JWT 设置 request.jwt.claims。
-- 此文件只做安全回归断言，不包含真实用户或真实房产资料。
do $$
declare
  required_table text;
begin
  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('queries', 'generation_jobs', 'property_reports', 'data_sources')
      and 'anon' = any(roles)
  ) then
    raise exception 'anonymous public policies remain on private project tables';
  end if;

  foreach required_table in array array[
    'queries', 'generation_jobs', 'property_reports', 'data_sources'
  ] loop
    if has_table_privilege('anon', 'public.' || required_table, 'select')
       or has_table_privilege('anon', 'public.' || required_table, 'insert')
       or has_table_privilege('anon', 'public.' || required_table, 'update')
       or has_table_privilege('anon', 'public.' || required_table, 'delete') then
      raise exception 'anonymous table privilege remains on %', required_table;
    end if;
    if has_table_privilege('authenticated', 'public.' || required_table, 'insert')
       or has_table_privilege('authenticated', 'public.' || required_table, 'update')
       or has_table_privilege('authenticated', 'public.' || required_table, 'delete') then
      raise exception 'authenticated write privilege remains on %', required_table;
    end if;
    if not has_table_privilege('authenticated', 'public.' || required_table, 'select') then
      raise exception 'authenticated read privilege is missing on %', required_table;
    end if;
  end loop;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('queries', 'generation_jobs', 'property_reports', 'data_sources')
      and 'authenticated' = any(roles)
      and cmd in ('INSERT', 'UPDATE', 'DELETE')
  ) then
    raise exception 'authenticated write policies remain on private project tables';
  end if;

  if not exists (
    select 1 from pg_policies
      where schemaname = 'public'
      and tablename = 'queries'
      and policyname = 'owners can read own queries'
      and 'authenticated' = any(roles)
      and cmd = 'SELECT'
  ) then
    raise exception 'owner-scoped query select policy is missing';
  end if;

  foreach required_table in array array[
    'properties', 'residential_details', 'new_build_details',
    'commercial_investment_details', 'evidences', 'analysis_metrics',
    'risk_findings', 'product_events'
  ] loop
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public' and tablename = required_table
    ) then
      raise exception 'RLS policy is missing for %', required_table;
    end if;
  end loop;

  if not exists (
    select 1 from pg_trigger
    where tgname = 'protect_membership_fields'
      and tgrelid = 'public.user_profiles'::regclass
  ) then
    raise exception 'membership protection trigger is missing';
  end if;

  if has_table_privilege('anon', 'public.user_profiles', 'select')
     or has_table_privilege('anon', 'public.user_profiles', 'insert')
     or has_table_privilege('anon', 'public.user_profiles', 'update')
     or has_table_privilege('anon', 'public.user_profiles', 'delete') then
    raise exception 'anonymous table privilege remains on user_profiles';
  end if;
  if has_table_privilege('authenticated', 'public.user_profiles', 'delete') then
    raise exception 'authenticated delete privilege remains on user_profiles';
  end if;

  if not has_table_privilege('anon', 'public.query_field_options', 'select') then
    raise exception 'anonymous field-option read privilege is missing';
  end if;
  if has_table_privilege('anon', 'public.query_field_options', 'insert')
     or has_table_privilege('anon', 'public.query_field_options', 'update')
     or has_table_privilege('anon', 'public.query_field_options', 'delete') then
    raise exception 'anonymous field-option write privilege remains';
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'query_field_options'
      and policyname = 'public can read active field options'
      and 'anon' = any(roles)
      and cmd = 'SELECT'
      and qual like '%is_active%'
  ) then
    raise exception 'active-only anonymous field-option policy is missing';
  end if;
end $$;
