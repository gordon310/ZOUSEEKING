-- M-B3 contract assertions against the frozen V1 tables only.
begin;
do $$
declare c text;
begin
  foreach c in array array['id','creator_user_id','purpose','region_pref','asset_type','compensation','public_description','apply_deadline','status','created_at','updated_at'] loop
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='service_tasks' and column_name=c) then raise exception 'missing service_tasks column: %', c; end if;
  end loop;
  foreach c in array array['id','task_id','organization_id','assigned_member_user_id','status','applied_at','updated_at'] loop
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='task_applications' and column_name=c) then raise exception 'missing task_applications column: %', c; end if;
  end loop;
  if exists (select 1 from information_schema.columns where table_schema='public' and table_name='service_tasks' and column_name in ('assignee_organization_id','accepted_at')) then raise exception 'parallel denormalized service task columns remain'; end if;
  if exists (select 1 from information_schema.tables where table_schema='public' and table_name in ('service_task_applications','service_task_events')) then raise exception 'parallel service task tables remain'; end if;
  if not exists (select 1 from pg_indexes where schemaname='public' and indexname='uq_task_applications_single_match') then raise exception 'missing single-match index'; end if;
  if not exists (select 1 from pg_constraint where conname='task_applications_one_per_org') then raise exception 'missing per-org application uniqueness'; end if;
  if not exists (select 1 from pg_constraint where conname='task_status_history_from_differs_to_check') then raise exception 'missing append-only history no-op guard'; end if;
end $$;
rollback;
