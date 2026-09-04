-- Reconcile the empty staging baseline with the canonical final contract.
-- This is the only migration applied to staging for M1. Historical applied
-- migration files stay byte-identical and missing historical IDs are not
-- manufactured in the remote ledger.

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
      raise exception 'missing M1 reconciliation prerequisite: public.%', required_table;
    end if;
  end loop;

  if exists (select 1 from public.sources)
     and not (
       exists (
         select 1 from information_schema.columns
         where table_schema = 'public' and table_name = 'sources'
           and column_name = 'data_class'
       )
       and exists (
         select 1 from information_schema.columns
         where table_schema = 'public' and table_name = 'sources'
           and column_name = 'source_period'
       )
       and exists (
         select 1 from information_schema.columns
         where table_schema = 'public' and table_name = 'sources'
           and column_name = 'observed_at'
       )
       and exists (
         select 1 from information_schema.columns
         where table_schema = 'public' and table_name = 'sources'
           and column_name = 'transformation_version'
       )
       and exists (
         select 1 from information_schema.columns
         where table_schema = 'public' and table_name = 'sources'
           and column_name = 'limitations'
       )
     ) then
    raise exception 'existing sources require reviewed provenance classification before M1 reconciliation';
  end if;

  if exists (select 1 from public.property_reports)
     and not exists (
       select 1 from information_schema.columns
       where table_schema = 'public' and table_name = 'property_reports'
         and column_name = 'report_status'
     ) then
    raise exception 'existing property_reports require reviewed provenance classification before M1 reconciliation';
  end if;

  if exists (select 1 from public.analysis_metrics)
     and not exists (
       select 1 from information_schema.columns
       where table_schema = 'public' and table_name = 'analysis_metrics'
         and column_name = 'report_status'
     ) then
    raise exception 'existing analysis_metrics require reviewed provenance classification before M1 reconciliation';
  end if;

  if exists (select 1 from public.risk_findings)
     and not exists (
       select 1 from information_schema.columns
       where table_schema = 'public' and table_name = 'risk_findings'
         and column_name = 'report_status'
     ) then
    raise exception 'existing risk_findings require reviewed provenance classification before M1 reconciliation';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'storage'
      and tablename = 'objects'
      and roles && array['anon', 'authenticated']::name[]
  ) then
    raise exception 'review Storage client policies before M1 reconciliation';
  end if;
end
$$;

alter table public.sources
  add column if not exists source_period text,
  add column if not exists limitations text,
  add column if not exists data_class public.data_class,
  add column if not exists observed_at timestamptz,
  add column if not exists transformation_version text;

alter table public.sources drop constraint if exists sources_permission_status_check;
alter table public.sources add constraint sources_permission_status_check
  check (
    permission_status in (
      'unverified', 'rights_confirmed', 'rights_restricted', 'not_permitted'
    )
  );

alter table public.sources
  alter column data_class set not null,
  alter column source_period set not null,
  alter column observed_at set not null,
  alter column transformation_version set not null,
  alter column limitations set not null,
  alter column permission_status drop default;

alter table public.sources drop constraint if exists sources_url_http_check;
alter table public.sources add constraint sources_url_http_check
  check (url ~ '^https?://.+');
alter table public.sources drop constraint if exists sources_source_period_nonempty_check;
alter table public.sources add constraint sources_source_period_nonempty_check
  check (nullif(btrim(source_period), '') is not null);
alter table public.sources drop constraint if exists sources_transformation_version_nonempty_check;
alter table public.sources add constraint sources_transformation_version_nonempty_check
  check (nullif(btrim(transformation_version), '') is not null);
alter table public.sources drop constraint if exists sources_limitations_nonempty_check;
alter table public.sources add constraint sources_limitations_nonempty_check
  check (nullif(btrim(limitations), '') is not null);

alter table public.property_reports
  add column if not exists data_class public.data_class,
  add column if not exists source_url text,
  add column if not exists source_locator text,
  add column if not exists source_period text,
  add column if not exists observed_at timestamptz,
  add column if not exists transformation_version text,
  add column if not exists limitations text,
  add column if not exists report_status text not null default 'generating',
  add column if not exists source_id uuid references public.sources(id) on delete set null,
  add column if not exists report_version text;

alter table public.property_reports drop constraint if exists property_reports_report_status_check;
alter table public.property_reports add constraint property_reports_report_status_check
  check (
    report_status in (
      'free_preview', 'full_report', 'generating', 'failed', 'insufficient_data'
    )
  );
alter table public.property_reports drop constraint if exists property_reports_published_provenance_check;
alter table public.property_reports add constraint property_reports_published_provenance_check check (
  report_status not in ('free_preview', 'full_report')
  or (
    data_class is not null
    and observed_at is not null
    and nullif(btrim(source_period), '') is not null
    and nullif(btrim(transformation_version), '') is not null
    and nullif(btrim(report_version), '') is not null
    and nullif(btrim(limitations), '') is not null
    and (data_class = 'synthetic_fixture' or source_id is not null)
    and (
      data_class <> 'user_submitted'
      or nullif(btrim(source_locator), '') is not null
    )
  )
);

alter table public.analysis_metrics
  add column if not exists data_class public.data_class,
  add column if not exists source_id uuid references public.sources(id) on delete set null,
  add column if not exists source_locator text,
  add column if not exists source_period text,
  add column if not exists observed_at timestamptz,
  add column if not exists report_version text,
  add column if not exists limitations text,
  add column if not exists report_status text not null default 'generating',
  add column if not exists sample_count integer,
  add column if not exists metric_period_from date,
  add column if not exists metric_period_to date,
  add column if not exists aggregation_method text,
  add column if not exists listing_or_closed text,
  add column if not exists asset_type text;

alter table public.analysis_metrics drop constraint if exists analysis_metrics_report_status_check;
alter table public.analysis_metrics add constraint analysis_metrics_report_status_check
  check (
    report_status in (
      'free_preview', 'full_report', 'generating', 'failed', 'insufficient_data'
    )
  );
alter table public.analysis_metrics drop constraint if exists analysis_metrics_sample_count_check;
alter table public.analysis_metrics add constraint analysis_metrics_sample_count_check
  check (sample_count is null or sample_count > 0);
alter table public.analysis_metrics drop constraint if exists analysis_metrics_metric_period_check;
alter table public.analysis_metrics add constraint analysis_metrics_metric_period_check
  check (
    metric_period_to is null
    or metric_period_from is null
    or metric_period_to >= metric_period_from
  );
alter table public.analysis_metrics drop constraint if exists analysis_metrics_listing_or_closed_check;
alter table public.analysis_metrics add constraint analysis_metrics_listing_or_closed_check
  check (listing_or_closed is null or listing_or_closed in ('listing', 'closed'));
alter table public.analysis_metrics drop constraint if exists analysis_metrics_asset_type_check;
alter table public.analysis_metrics add constraint analysis_metrics_asset_type_check
  check (
    asset_type is null
    or asset_type in ('condo', 'tower', 'detached_house', 'other')
  );
alter table public.analysis_metrics drop constraint if exists analysis_metrics_published_provenance_check;
alter table public.analysis_metrics add constraint analysis_metrics_published_provenance_check check (
  report_status not in ('free_preview', 'full_report')
  or (
    data_class is not null
    and observed_at is not null
    and nullif(btrim(source_period), '') is not null
    and nullif(btrim(report_version), '') is not null
    and nullif(btrim(limitations), '') is not null
    and sample_count is not null
    and metric_period_from is not null
    and metric_period_to is not null
    and nullif(btrim(aggregation_method), '') is not null
    and listing_or_closed is not null
    and asset_type is not null
    and (data_class = 'synthetic_fixture' or source_id is not null)
    and (
      data_class <> 'user_submitted'
      or nullif(btrim(source_locator), '') is not null
    )
  )
);

alter table public.risk_findings
  add column if not exists data_class public.data_class,
  add column if not exists source_id uuid references public.sources(id) on delete set null,
  add column if not exists source_locator text,
  add column if not exists source_period text,
  add column if not exists observed_at timestamptz,
  add column if not exists report_version text,
  add column if not exists limitations text,
  add column if not exists report_status text not null default 'generating';

alter table public.risk_findings drop constraint if exists risk_findings_report_status_check;
alter table public.risk_findings add constraint risk_findings_report_status_check
  check (
    report_status in (
      'free_preview', 'full_report', 'generating', 'failed', 'insufficient_data'
    )
  );
alter table public.risk_findings drop constraint if exists risk_findings_published_provenance_check;
alter table public.risk_findings add constraint risk_findings_published_provenance_check check (
  report_status not in ('free_preview', 'full_report')
  or (
    data_class is not null
    and observed_at is not null
    and nullif(btrim(source_period), '') is not null
    and nullif(btrim(report_version), '') is not null
    and nullif(btrim(limitations), '') is not null
    and (data_class = 'synthetic_fixture' or source_id is not null)
    and (
      data_class <> 'user_submitted'
      or nullif(btrim(source_locator), '') is not null
    )
  )
);

alter table public.policy_documents
  drop constraint if exists policy_documents_effective_dates_check;
alter table public.policy_documents
  add constraint policy_documents_effective_dates_check
  check (effective_to is null or effective_to >= effective_from);
create index if not exists idx_policy_documents_active_scope
  on public.policy_documents(jurisdiction, status, effective_from desc);

drop trigger if exists prevent_policy_version_overlap on public.policy_documents;
drop function if exists public.prevent_policy_version_overlap();
create extension if not exists btree_gist;

do $$
begin
  if exists (
    select 1
    from public.policy_documents left_row
    join public.policy_documents right_row
      on left_row.policy_key = right_row.policy_key
     and left_row.id < right_row.id
     and daterange(left_row.effective_from, left_row.effective_to + 1, '[)')
         && daterange(right_row.effective_from, right_row.effective_to + 1, '[)')
  ) then
    raise exception 'cannot add policy overlap constraint: existing policy versions overlap';
  end if;

  if exists (
    select 1
    from pg_constraint
    where conrelid = 'public.policy_documents'::regclass
      and conname = 'policy_documents_no_overlapping_versions'
  ) then
    alter table public.policy_documents
      drop constraint policy_documents_no_overlapping_versions;
  end if;

  alter table public.policy_documents
    add constraint policy_documents_no_overlapping_versions
    exclude using gist (
      policy_key with =,
      daterange(effective_from, effective_to + 1, '[)') with &&
    );
end
$$;

create or replace function public.reject_analysis_metric_mutation()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  raise exception 'analysis metric history is append-only; insert a new calculation_version instead';
end;
$$;

drop trigger if exists protect_analysis_metric_history on public.analysis_metrics;
create trigger protect_analysis_metric_history
before update or delete on public.analysis_metrics
for each row execute function public.reject_analysis_metric_mutation();

create or replace function public.enforce_published_source_rights()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  source_data_class public.data_class;
  source_permission_status text;
begin
  if new.report_status not in ('free_preview', 'full_report')
     or new.data_class = 'synthetic_fixture' then
    return new;
  end if;

  if new.source_id is null then
    raise exception 'published % requires an authorized source', tg_table_name;
  end if;

  select data_class, permission_status
    into source_data_class, source_permission_status
  from public.sources
  where id = new.source_id;

  if not found then
    raise exception 'published % references an unknown source', tg_table_name;
  end if;
  if source_permission_status <> 'rights_confirmed' then
    raise exception 'published % requires a rights_confirmed source', tg_table_name;
  end if;
  if source_data_class is distinct from new.data_class then
    raise exception 'published % data_class must match its source', tg_table_name;
  end if;
  return new;
end;
$$;

revoke all on function public.enforce_published_source_rights()
from public, anon, authenticated;

drop trigger if exists enforce_property_report_source_rights
  on public.property_reports;
create trigger enforce_property_report_source_rights
before insert or update on public.property_reports
for each row execute function public.enforce_published_source_rights();

drop trigger if exists enforce_analysis_metric_source_rights
  on public.analysis_metrics;
create trigger enforce_analysis_metric_source_rights
before insert or update on public.analysis_metrics
for each row execute function public.enforce_published_source_rights();

drop trigger if exists enforce_risk_finding_source_rights
  on public.risk_findings;
create trigger enforce_risk_finding_source_rights
before insert or update on public.risk_findings
for each row execute function public.enforce_published_source_rights();

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
end
$$;

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
