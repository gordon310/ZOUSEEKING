-- Forward candidate: enforce V1 provenance only when an output is publishable.
-- Draft/generating rows remain compatible with the existing backend insert path;
-- no rows are copied, inferred, or backfilled by this migration.

alter table public.sources
  add column if not exists source_period text,
  add column if not exists limitations text;

alter table public.sources drop constraint if exists sources_permission_status_check;
alter table public.sources add constraint sources_permission_status_check
  check (permission_status in ('unverified', 'rights_confirmed', 'rights_restricted', 'not_permitted'));

alter table public.property_reports
  add column if not exists data_class public.data_class,
  add column if not exists source_url text,
  add column if not exists source_locator text,
  add column if not exists source_period text,
  add column if not exists observed_at timestamptz,
  add column if not exists transformation_version text,
  add column if not exists limitations text,
  add column if not exists report_status text not null default 'generating';

alter table public.property_reports drop constraint if exists property_reports_report_status_check;
alter table public.property_reports add constraint property_reports_report_status_check
  check (report_status in ('free_preview', 'full_report', 'generating', 'failed', 'insufficient_data'));
alter table public.property_reports drop constraint if exists property_reports_published_provenance_check;
alter table public.property_reports add constraint property_reports_published_provenance_check check (
  report_status not in ('free_preview', 'full_report')
  or (
    data_class is not null
    and observed_at is not null
    and nullif(btrim(source_period), '') is not null
    and nullif(btrim(transformation_version), '') is not null
    and nullif(btrim(limitations), '') is not null
    and case
      when data_class = 'synthetic_fixture' then true
      when data_class = 'user_submitted' then nullif(btrim(source_locator), '') is not null
      else nullif(btrim(source_url), '') is not null
    end
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
  check (report_status in ('free_preview', 'full_report', 'generating', 'failed', 'insufficient_data'));
alter table public.analysis_metrics drop constraint if exists analysis_metrics_sample_count_check;
alter table public.analysis_metrics add constraint analysis_metrics_sample_count_check
  check (sample_count is null or sample_count > 0);
alter table public.analysis_metrics drop constraint if exists analysis_metrics_metric_period_check;
alter table public.analysis_metrics add constraint analysis_metrics_metric_period_check
  check (metric_period_to is null or metric_period_from is null or metric_period_to >= metric_period_from);
alter table public.analysis_metrics drop constraint if exists analysis_metrics_listing_or_closed_check;
alter table public.analysis_metrics add constraint analysis_metrics_listing_or_closed_check
  check (listing_or_closed is null or listing_or_closed in ('listing', 'closed'));
alter table public.analysis_metrics drop constraint if exists analysis_metrics_asset_type_check;
alter table public.analysis_metrics add constraint analysis_metrics_asset_type_check
  check (asset_type is null or asset_type in ('condo', 'tower', 'detached_house', 'other'));
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
    and case
      when data_class = 'synthetic_fixture' then true
      when data_class = 'user_submitted' then nullif(btrim(source_locator), '') is not null
      else source_id is not null
    end
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
  check (report_status in ('free_preview', 'full_report', 'generating', 'failed', 'insufficient_data'));
alter table public.risk_findings drop constraint if exists risk_findings_published_provenance_check;
alter table public.risk_findings add constraint risk_findings_published_provenance_check check (
  report_status not in ('free_preview', 'full_report')
  or (
    data_class is not null
    and observed_at is not null
    and nullif(btrim(source_period), '') is not null
    and nullif(btrim(report_version), '') is not null
    and nullif(btrim(limitations), '') is not null
    and case
      when data_class = 'synthetic_fixture' then true
      when data_class = 'user_submitted' then nullif(btrim(source_locator), '') is not null
      else source_id is not null
    end
  )
);

-- A GiST exclusion constraint, unlike a trigger-level EXISTS check, sees
-- conflicting concurrent writes. NULL upper bounds represent true infinity.
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
    select 1 from pg_constraint
    where conrelid = 'public.policy_documents'::regclass
      and conname = 'policy_documents_no_overlapping_versions'
  ) then
    alter table public.policy_documents drop constraint policy_documents_no_overlapping_versions;
  end if;
  alter table public.policy_documents add constraint policy_documents_no_overlapping_versions
    exclude using gist (
      policy_key with =,
      daterange(effective_from, effective_to + 1, '[)') with &&
    );
end;
$$;

-- Metrics are append-only for every database role. Revisions require a new
-- row with a new calculation_version; this trigger always raises, never no-ops.
create or replace function public.reject_analysis_metric_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
  raise exception 'analysis metric history is append-only; insert a new calculation_version instead';
end;
$$;
drop trigger if exists protect_analysis_metric_history on public.analysis_metrics;
create trigger protect_analysis_metric_history
before update or delete on public.analysis_metrics
for each row execute function public.reject_analysis_metric_mutation();
