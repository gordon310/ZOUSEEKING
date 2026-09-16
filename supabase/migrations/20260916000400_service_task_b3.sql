-- M-B3 is an application/workflow release over the frozen V1 service-task
-- tables.  The four tables and all constraints are owned by
-- 20260905000400_v1_service_tasks_contacts.sql; this migration deliberately
-- adds no parallel tables, columns, policies, or contact channel.
do $$
begin
  if to_regclass('public.service_tasks') is null
     or to_regclass('public.task_applications') is null
     or to_regclass('public.task_status_history') is null
     or to_regclass('public.contact_consents') is null then
    raise exception 'M-B3 requires the frozen V1 service-task tables';
  end if;
end $$;
