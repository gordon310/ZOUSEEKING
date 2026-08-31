-- Final access contract for the canonical fresh-install history.
-- This migration preserves the accepted anonymous field-option read while
-- keeping every private/member write behind the trusted FastAPI/service role.
-- It contains no customer data and does not infer ownership.

do $$
declare
  required_table text;
begin
  foreach required_table in array array[
    'queries', 'query_field_options', 'generation_jobs', 'property_reports',
    'data_sources', 'user_profiles', 'sources', 'properties',
    'residential_details', 'new_build_details',
    'commercial_investment_details', 'evidences', 'analysis_metrics',
    'risk_findings', 'policy_documents', 'product_events',
    'analysis_sessions', 'project_inputs', 'project_field_evidence',
    'project_fields', 'free_previews', 'intake_rate_limits'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing canonical access prerequisite: public.%', required_table;
    end if;
  end loop;
end $$;

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
alter table public.analysis_sessions enable row level security;
alter table public.project_inputs enable row level security;
alter table public.project_field_evidence enable row level security;
alter table public.project_fields enable row level security;
alter table public.free_previews enable row level security;
alter table public.intake_rate_limits enable row level security;

do $$
declare
  policy_row record;
begin
  for policy_row in
    select policyname, tablename
    from pg_policies
    where schemaname = 'public'
      and tablename = any (array[
        'queries', 'query_field_options', 'generation_jobs',
        'property_reports', 'data_sources', 'user_profiles', 'sources',
        'properties', 'residential_details', 'new_build_details',
        'commercial_investment_details', 'evidences', 'analysis_metrics',
        'risk_findings', 'policy_documents', 'product_events',
        'analysis_sessions', 'project_inputs', 'project_field_evidence',
        'project_fields', 'free_previews', 'intake_rate_limits'
      ])
  loop
    execute format(
      'drop policy if exists %I on public.%I',
      policy_row.policyname,
      policy_row.tablename
    );
  end loop;
end $$;

revoke all on public.queries,
  public.query_field_options,
  public.generation_jobs,
  public.property_reports,
  public.data_sources,
  public.user_profiles,
  public.sources,
  public.properties,
  public.residential_details,
  public.new_build_details,
  public.commercial_investment_details,
  public.evidences,
  public.analysis_metrics,
  public.risk_findings,
  public.policy_documents,
  public.product_events,
  public.analysis_sessions,
  public.project_inputs,
  public.project_field_evidence,
  public.project_fields,
  public.free_previews,
  public.intake_rate_limits
from public, anon, authenticated;

grant select on public.query_field_options to anon;

grant select on public.queries,
  public.generation_jobs,
  public.property_reports,
  public.data_sources,
  public.properties,
  public.residential_details,
  public.new_build_details,
  public.commercial_investment_details,
  public.evidences,
  public.analysis_metrics,
  public.risk_findings,
  public.product_events
to authenticated;

grant select, insert, update on public.user_profiles to authenticated;

create policy "public can read active field options"
on public.query_field_options for select to anon
using (is_active = true);

create policy "owners can read own queries"
on public.queries for select to authenticated
using (owner_user_id = (select auth.uid()));

create policy "owners can read own jobs"
on public.generation_jobs for select to authenticated
using (
  exists (
    select 1
    from public.queries q
    where q.id = generation_jobs.query_id
      and q.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own reports"
on public.property_reports for select to authenticated
using (
  owner_user_id = (select auth.uid())
  or exists (
    select 1
    from public.queries q
    where q.id = property_reports.query_id
      and q.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own sources"
on public.data_sources for select to authenticated
using (
  owner_user_id = (select auth.uid())
  or exists (
    select 1
    from public.queries q
    where q.id = data_sources.query_id
      and q.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own properties"
on public.properties for select to authenticated
using (owner_user_id = (select auth.uid()));

create policy "owners can read own residential details"
on public.residential_details for select to authenticated
using (
  exists (
    select 1
    from public.properties p
    where p.id = property_id
      and p.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own new build details"
on public.new_build_details for select to authenticated
using (
  exists (
    select 1
    from public.properties p
    where p.id = property_id
      and p.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own commercial details"
on public.commercial_investment_details for select to authenticated
using (
  exists (
    select 1
    from public.properties p
    where p.id = property_id
      and p.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own evidence"
on public.evidences for select to authenticated
using (
  exists (
    select 1
    from public.properties p
    where p.id = property_id
      and p.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own metrics"
on public.analysis_metrics for select to authenticated
using (
  exists (
    select 1
    from public.properties p
    where p.id = property_id
      and p.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own risks"
on public.risk_findings for select to authenticated
using (
  exists (
    select 1
    from public.properties p
    where p.id = property_id
      and p.owner_user_id = (select auth.uid())
  )
);

create policy "owners can read own events"
on public.product_events for select to authenticated
using (user_id = (select auth.uid()));

create policy "users can read own profile"
on public.user_profiles for select to authenticated
using (user_id = (select auth.uid()));

create policy "users can insert own profile"
on public.user_profiles for insert to authenticated
with check (user_id = (select auth.uid()));

create policy "users can update own profile preferences"
on public.user_profiles for update to authenticated
using (user_id = (select auth.uid()))
with check (user_id = (select auth.uid()));

create index if not exists idx_product_events_user_id
  on public.product_events(user_id);
create index if not exists idx_risk_findings_property_id
  on public.risk_findings(property_id);

alter function public.set_intake_updated_at() set search_path = public;
