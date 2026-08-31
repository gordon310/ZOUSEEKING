-- Candidate immutable analytics and non-overlapping policy-version baseline.
alter table public.policy_documents drop constraint if exists policy_documents_effective_dates_check;
alter table public.policy_documents add constraint policy_documents_effective_dates_check check (effective_to is null or effective_to >= effective_from);
create index if not exists idx_policy_documents_active_scope on public.policy_documents(jurisdiction, status, effective_from desc);
create or replace function public.prevent_policy_version_overlap() returns trigger language plpgsql set search_path = public as $$
begin
  if exists (select 1 from public.policy_documents p where p.policy_key = new.policy_key
    and p.id <> coalesce(new.id, '00000000-0000-0000-0000-000000000000')::uuid
    and daterange(p.effective_from, coalesce(p.effective_to + 1, '9999-12-31'::date), '[)')
      && daterange(new.effective_from, coalesce(new.effective_to + 1, '9999-12-31'::date), '[)')) then
    raise exception 'policy versions overlap for policy_key %', new.policy_key;
  end if;
  return new;
end;
$$;
drop trigger if exists prevent_policy_version_overlap on public.policy_documents;
create trigger prevent_policy_version_overlap before insert or update on public.policy_documents for each row execute function public.prevent_policy_version_overlap();
create or replace function public.prevent_published_metric_update() returns trigger language plpgsql set search_path = public as $$
begin
  if not public.is_service_role() then raise exception 'analysis metric history is immutable'; end if;
  return new;
end;
$$;
drop trigger if exists protect_analysis_metric_history on public.analysis_metrics;
create trigger protect_analysis_metric_history before update or delete on public.analysis_metrics for each row execute function public.prevent_published_metric_update();
