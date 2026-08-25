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
      and policyname like 'public can %'
  ) then
    raise exception 'anonymous public policies remain on private project tables';
  end if;

  if not exists (
    select 1 from pg_policies
      where schemaname = 'public'
      and tablename = 'queries'
      and policyname = 'owners can read own queries'
  ) then
    raise exception 'owner query select policy is missing';
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
end $$;
