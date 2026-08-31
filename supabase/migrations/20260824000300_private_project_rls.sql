-- Candidate ownership/RLS baseline. It deliberately does not backfill owners
-- from requested_by_email or any other client-maintained identity field.
alter table public.queries add column if not exists owner_user_id uuid references auth.users(id) on delete set null;
alter table public.property_reports add column if not exists owner_user_id uuid references auth.users(id) on delete set null;
alter table public.data_sources add column if not exists owner_user_id uuid references auth.users(id) on delete set null;
create index if not exists idx_queries_owner_user_id on public.queries(owner_user_id);
create index if not exists idx_reports_owner_user_id on public.property_reports(owner_user_id);
create index if not exists idx_data_sources_owner_user_id on public.data_sources(owner_user_id);
drop index if exists public.uq_property_reports_query_id;
create unique index if not exists uq_property_reports_query_id on public.property_reports(query_id);

create or replace function public.is_service_role() returns boolean language sql stable set search_path = public as $$
  select current_user in ('postgres', 'service_role', 'supabase_admin')
      or coalesce(current_setting('request.jwt.claim.role', true), '') in ('service_role', 'supabase_admin');
$$;
create or replace function public.prevent_client_ownership_change() returns trigger language plpgsql set search_path = public as $$
begin
  if public.is_service_role() then return new; end if;
  if tg_op = 'UPDATE' and new.owner_user_id is distinct from old.owner_user_id then
    raise exception 'owner_user_id is server-managed';
  end if;
  return new;
end;
$$;
drop trigger if exists protect_queries_ownership on public.queries;
create trigger protect_queries_ownership before update on public.queries for each row execute function public.prevent_client_ownership_change();
drop trigger if exists protect_reports_ownership on public.property_reports;
create trigger protect_reports_ownership before update on public.property_reports for each row execute function public.prevent_client_ownership_change();
drop trigger if exists protect_sources_ownership on public.data_sources;
create trigger protect_sources_ownership before update on public.data_sources for each row execute function public.prevent_client_ownership_change();

alter table public.queries enable row level security;
alter table public.query_field_options enable row level security;
alter table public.generation_jobs enable row level security;
alter table public.property_reports enable row level security;
alter table public.data_sources enable row level security;
alter table public.user_profiles enable row level security;
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

do $$
declare policy_row record;
begin
  for policy_row in select policyname, tablename from pg_policies
    where schemaname = 'public' and tablename = any (array[
      'queries', 'query_field_options', 'generation_jobs', 'property_reports', 'data_sources', 'user_profiles',
      'sources', 'properties', 'residential_details', 'new_build_details', 'commercial_investment_details',
      'evidences', 'analysis_metrics', 'risk_findings', 'policy_documents', 'product_events'
    ])
  loop
    execute format('drop policy if exists %I on public.%I', policy_row.policyname, policy_row.tablename);
  end loop;
end $$;
revoke all on public.queries, public.query_field_options, public.generation_jobs, public.property_reports, public.data_sources,
  public.user_profiles, public.sources, public.properties, public.residential_details, public.new_build_details,
  public.commercial_investment_details, public.evidences, public.analysis_metrics, public.risk_findings, public.policy_documents,
  public.product_events from anon, authenticated;
grant select on public.queries, public.generation_jobs, public.property_reports, public.data_sources, public.properties,
  public.residential_details, public.new_build_details, public.commercial_investment_details, public.evidences,
  public.analysis_metrics, public.risk_findings, public.product_events to authenticated;
grant select, insert, update on public.user_profiles to authenticated;

create policy "owners can read own queries" on public.queries for select to authenticated using (owner_user_id = auth.uid());
create policy "owners can read own jobs" on public.generation_jobs for select to authenticated using (exists (select 1 from public.queries q where q.id = generation_jobs.query_id and q.owner_user_id = auth.uid()));
create policy "owners can read own reports" on public.property_reports for select to authenticated using (owner_user_id = auth.uid() or exists (select 1 from public.queries q where q.id = property_reports.query_id and q.owner_user_id = auth.uid()));
create policy "owners can read own sources" on public.data_sources for select to authenticated using (owner_user_id = auth.uid() or exists (select 1 from public.queries q where q.id = data_sources.query_id and q.owner_user_id = auth.uid()));
create policy "owners can read own properties" on public.properties for select to authenticated using (owner_user_id = auth.uid());
create policy "owners can read own residential details" on public.residential_details for select to authenticated using (exists (select 1 from public.properties p where p.id = property_id and p.owner_user_id = auth.uid()));
create policy "owners can read own new build details" on public.new_build_details for select to authenticated using (exists (select 1 from public.properties p where p.id = property_id and p.owner_user_id = auth.uid()));
create policy "owners can read own commercial details" on public.commercial_investment_details for select to authenticated using (exists (select 1 from public.properties p where p.id = property_id and p.owner_user_id = auth.uid()));
create policy "owners can read own evidence" on public.evidences for select to authenticated using (exists (select 1 from public.properties p where p.id = property_id and p.owner_user_id = auth.uid()));
create policy "owners can read own metrics" on public.analysis_metrics for select to authenticated using (exists (select 1 from public.properties p where p.id = property_id and p.owner_user_id = auth.uid()));
create policy "owners can read own risks" on public.risk_findings for select to authenticated using (exists (select 1 from public.properties p where p.id = property_id and p.owner_user_id = auth.uid()));
create policy "owners can read own events" on public.product_events for select to authenticated using (user_id = auth.uid());
create policy "users can read own profile" on public.user_profiles for select to authenticated using (auth.uid() = user_id);
create policy "users can insert own profile" on public.user_profiles for insert to authenticated with check (auth.uid() = user_id);
create policy "users can update own profile preferences" on public.user_profiles for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

create or replace function public.prevent_client_membership_change() returns trigger language plpgsql set search_path = public as $$
begin
  if not public.is_service_role() and ((tg_op = 'INSERT' and (new.membership_tier <> 'free' or new.daily_query_limit <> 3))
    or (tg_op = 'UPDATE' and (new.membership_tier is distinct from old.membership_tier or new.daily_query_limit is distinct from old.daily_query_limit))) then
    raise exception 'membership fields are server-managed';
  end if;
  return new;
end;
$$;
drop trigger if exists protect_membership_fields on public.user_profiles;
create trigger protect_membership_fields before insert or update on public.user_profiles for each row execute function public.prevent_client_membership_change();
