-- Forward candidate: close the V1 provenance contract without fabricating
-- defaults or backfilling existing records.

alter table public.sources
  add column if not exists data_class public.data_class,
  add column if not exists observed_at timestamptz,
  add column if not exists transformation_version text;

alter table public.sources
  alter column data_class set not null,
  alter column source_period set not null,
  alter column observed_at set not null,
  alter column transformation_version set not null,
  alter column limitations set not null,
  alter column permission_status drop default;

alter table public.sources drop constraint if exists sources_url_http_check;
alter table public.sources add constraint sources_url_http_check check (url ~ '^https?://.+');
alter table public.sources drop constraint if exists sources_source_period_nonempty_check;
alter table public.sources add constraint sources_source_period_nonempty_check check (nullif(btrim(source_period), '') is not null);
alter table public.sources drop constraint if exists sources_transformation_version_nonempty_check;
alter table public.sources add constraint sources_transformation_version_nonempty_check check (nullif(btrim(transformation_version), '') is not null);
alter table public.sources drop constraint if exists sources_limitations_nonempty_check;
alter table public.sources add constraint sources_limitations_nonempty_check check (nullif(btrim(limitations), '') is not null);

alter table public.property_reports
  add column if not exists source_id uuid references public.sources(id) on delete set null,
  add column if not exists report_version text;

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
    and case
      when data_class = 'synthetic_fixture' then true
      when data_class = 'user_submitted' then nullif(btrim(source_locator), '') is not null
      else source_id is not null
    end
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
     or new.data_class in ('synthetic_fixture', 'user_submitted') then
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

drop trigger if exists enforce_property_report_source_rights on public.property_reports;
create trigger enforce_property_report_source_rights
before insert or update on public.property_reports
for each row execute function public.enforce_published_source_rights();
drop trigger if exists enforce_analysis_metric_source_rights on public.analysis_metrics;
create trigger enforce_analysis_metric_source_rights
before insert or update on public.analysis_metrics
for each row execute function public.enforce_published_source_rights();
drop trigger if exists enforce_risk_finding_source_rights on public.risk_findings;
create trigger enforce_risk_finding_source_rights
before insert or update on public.risk_findings
for each row execute function public.enforce_published_source_rights();
