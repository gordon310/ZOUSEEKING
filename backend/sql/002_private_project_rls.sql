-- 私有项目安全迁移。
-- 运行前提：Supabase Auth 已启用；service_role 用于后台写入。

alter table public.queries
  add column if not exists owner_user_id uuid references auth.users(id) on delete set null;

alter table public.property_reports
  add column if not exists owner_user_id uuid references auth.users(id) on delete set null;

alter table public.data_sources
  add column if not exists owner_user_id uuid references auth.users(id) on delete set null;

alter table public.sources enable row level security;
alter table public.properties enable row level security;
alter table public.residential_details enable row level security;
alter table public.new_build_details enable row level security;
alter table public.commercial_investment_details enable row level security;
alter table public.evidences enable row level security;
alter table public.analysis_metrics enable row level security;
alter table public.risk_findings enable row level security;
alter table public.policy_documents enable row level security;
alter table public.product_events enable row level security;

create index if not exists idx_queries_owner_user_id on public.queries(owner_user_id);
create index if not exists idx_reports_owner_user_id on public.property_reports(owner_user_id);
create index if not exists idx_data_sources_owner_user_id on public.data_sources(owner_user_id);
drop index if exists public.uq_property_reports_query_id;
create unique index if not exists uq_property_reports_query_id
  on public.property_reports(query_id);

create or replace function public.is_service_role()
returns boolean
language sql
stable
as $$
  select coalesce(current_setting('request.jwt.claim.role', true), '') in ('service_role', 'supabase_admin');
$$;

create or replace function public.prevent_client_ownership_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if public.is_service_role() then
    return new;
  end if;
  if tg_op = 'UPDATE' and (new.owner_user_id is distinct from old.owner_user_id) then
    raise exception 'owner_user_id is server-managed';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_queries_ownership on public.queries;
create trigger protect_queries_ownership
before insert or update on public.queries
for each row execute function public.prevent_client_ownership_change();

drop trigger if exists protect_reports_ownership on public.property_reports;
create trigger protect_reports_ownership
before insert or update on public.property_reports
for each row execute function public.prevent_client_ownership_change();

drop trigger if exists protect_sources_ownership on public.data_sources;
create trigger protect_sources_ownership
before insert or update on public.data_sources
for each row execute function public.prevent_client_ownership_change();

-- 旧的匿名读写策略必须移除；前端不能再用 anon 角色写入用户项目。
drop policy if exists "public can read queries" on public.queries;
drop policy if exists "public can insert queries" on public.queries;
drop policy if exists "public can update queries" on public.queries;
drop policy if exists "public can read jobs" on public.generation_jobs;
drop policy if exists "public can insert jobs" on public.generation_jobs;
drop policy if exists "public can read reports" on public.property_reports;
drop policy if exists "public can read data sources" on public.data_sources;
drop policy if exists "owners can read own queries" on public.queries;
drop policy if exists "owners can create own queries" on public.queries;
drop policy if exists "owners can update own queries" on public.queries;
drop policy if exists "owners can delete own queries" on public.queries;
drop policy if exists "owners can read own jobs" on public.generation_jobs;
drop policy if exists "owners can create own jobs" on public.generation_jobs;
drop policy if exists "owners can read own reports" on public.property_reports;
drop policy if exists "owners can read own sources" on public.data_sources;
drop policy if exists "owners can read own properties" on public.properties;
drop policy if exists "owners can create own properties" on public.properties;
drop policy if exists "owners can update own properties" on public.properties;
drop policy if exists "owners can delete own properties" on public.properties;
drop policy if exists "owners can read own residential details" on public.residential_details;
drop policy if exists "owners can read own new build details" on public.new_build_details;
drop policy if exists "owners can read own commercial details" on public.commercial_investment_details;
drop policy if exists "owners can read own evidence" on public.evidences;
drop policy if exists "owners can read own metrics" on public.analysis_metrics;
drop policy if exists "owners can read own risks" on public.risk_findings;
drop policy if exists "service can manage policies" on public.policy_documents;
drop policy if exists "owners can read own events" on public.product_events;

create policy "owners can read own queries"
on public.queries for select to authenticated
using (owner_user_id = auth.uid() or public.is_service_role());

create policy "owners can create own queries"
on public.queries for insert to authenticated
with check (owner_user_id = auth.uid());

create policy "owners can update own queries"
on public.queries for update to authenticated
using (owner_user_id = auth.uid())
with check (owner_user_id = auth.uid());

create policy "owners can delete own queries"
on public.queries for delete to authenticated
using (owner_user_id = auth.uid());

create policy "owners can read own jobs"
on public.generation_jobs for select to authenticated
using (
  public.is_service_role()
  or exists (
    select 1 from public.queries q
    where q.id = generation_jobs.query_id and q.owner_user_id = auth.uid()
  )
);

create policy "owners can create own jobs"
on public.generation_jobs for insert to authenticated
with check (
  exists (
    select 1 from public.queries q
    where q.id = generation_jobs.query_id and q.owner_user_id = auth.uid()
  )
);

create policy "owners can read own reports"
on public.property_reports for select to authenticated
using (owner_user_id = auth.uid() or public.is_service_role());

create policy "owners can read own sources"
on public.data_sources for select to authenticated
using (owner_user_id = auth.uid() or public.is_service_role());

create policy "owners can read own properties"
on public.properties for select to authenticated
using (owner_user_id = auth.uid() or public.is_service_role());

create policy "owners can create own properties"
on public.properties for insert to authenticated
with check (owner_user_id = auth.uid());

create policy "owners can update own properties"
on public.properties for update to authenticated
using (owner_user_id = auth.uid())
with check (owner_user_id = auth.uid());

create policy "owners can delete own properties"
on public.properties for delete to authenticated
using (owner_user_id = auth.uid());

create policy "owners can read own residential details"
on public.residential_details for select to authenticated
using (exists (select 1 from public.properties p where p.id = property_id and (p.owner_user_id = auth.uid() or public.is_service_role())));

create policy "owners can read own new build details"
on public.new_build_details for select to authenticated
using (exists (select 1 from public.properties p where p.id = property_id and (p.owner_user_id = auth.uid() or public.is_service_role())));

create policy "owners can read own commercial details"
on public.commercial_investment_details for select to authenticated
using (exists (select 1 from public.properties p where p.id = property_id and (p.owner_user_id = auth.uid() or public.is_service_role())));

create policy "owners can read own evidence"
on public.evidences for select to authenticated
using (exists (select 1 from public.properties p where p.id = property_id and (p.owner_user_id = auth.uid() or public.is_service_role())));

create policy "owners can read own metrics"
on public.analysis_metrics for select to authenticated
using (exists (select 1 from public.properties p where p.id = property_id and (p.owner_user_id = auth.uid() or public.is_service_role())));

create policy "owners can read own risks"
on public.risk_findings for select to authenticated
using (exists (select 1 from public.properties p where p.id = property_id and (p.owner_user_id = auth.uid() or public.is_service_role())));

create policy "service can manage policies"
on public.policy_documents for all to authenticated
using (public.is_service_role())
with check (public.is_service_role());

create policy "owners can read own events"
on public.product_events for select to authenticated
using (user_id = auth.uid() or public.is_service_role());

-- 详情字段中的会员权益必须由后台服务维护，客户端只能更新个人偏好。
create or replace function public.prevent_client_membership_change()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_service_role()
     and (
       tg_op = 'INSERT' and (new.membership_tier <> 'free' or new.daily_query_limit <> 3)
       or tg_op = 'UPDATE' and (
         new.membership_tier is distinct from old.membership_tier
         or new.daily_query_limit is distinct from old.daily_query_limit
       )
     ) then
    raise exception 'membership fields are server-managed';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_membership_fields on public.user_profiles;
create trigger protect_membership_fields
before insert or update on public.user_profiles
for each row execute function public.prevent_client_membership_change();

drop policy if exists "users can update own profile" on public.user_profiles;
drop policy if exists "users can update own profile preferences" on public.user_profiles;
create policy "users can update own profile preferences"
on public.user_profiles for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
