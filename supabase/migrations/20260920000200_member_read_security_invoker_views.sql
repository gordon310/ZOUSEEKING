-- Browser reads of member-owned rows use SECURITY INVOKER views so the base
-- table RLS policies are evaluated as the requesting role, never as the view
-- owner. These are deliberately read-only grants; profile preference writes
-- remain on the existing base-table endpoint and RLS policy.

create or replace view public.member_queries as
select
  q.*,
  coalesce(
    (
      select jsonb_agg(
        jsonb_build_object(
          'id', j.id,
          'status', j.status,
          'progress', j.progress,
          'current_step', j.current_step,
          'error_message', j.error_message,
          'created_at', j.created_at
        )
        order by j.created_at desc
      )
      from public.generation_jobs j
      where j.query_id = q.id
    ),
    '[]'::jsonb
  ) as generation_jobs
from public.queries q;

create or replace view public.member_property_reports as
select r.*
from public.property_reports r;

create or replace view public.member_profiles as
select p.*
from public.user_profiles p;

alter view public.member_queries set (security_invoker = true);
alter view public.member_property_reports set (security_invoker = true);
alter view public.member_profiles set (security_invoker = true);

revoke all on public.member_queries from public, anon, authenticated, service_role;
revoke all on public.member_property_reports from public, anon, authenticated, service_role;
revoke all on public.member_profiles from public, anon, authenticated, service_role;

grant select on public.member_queries to authenticated, service_role;
grant select on public.member_property_reports to authenticated, service_role;
grant select on public.member_profiles to authenticated, service_role;
