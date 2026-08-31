-- Forward candidate: user-submitted publication remains auditable through a
-- rights-bearing source row as well as its evidence locator.

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
    and (data_class <> 'user_submitted' or nullif(btrim(source_locator), '') is not null)
  )
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
    and (data_class <> 'user_submitted' or nullif(btrim(source_locator), '') is not null)
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
    and (data_class <> 'user_submitted' or nullif(btrim(source_locator), '') is not null)
  )
);

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
revoke all on function public.enforce_published_source_rights() from public, anon, authenticated;
