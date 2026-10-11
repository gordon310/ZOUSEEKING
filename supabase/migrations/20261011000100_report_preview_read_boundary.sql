-- Forward-only paywall hardening. Browser SQL reads are always previews;
-- authenticated FastAPI endpoints alone return paid/consumed report contents.
-- Apply with the matching API/frontend release after backup and local RLS
-- verification. This migration changes no report, payment, or usage data.
-- Roll forward on failure: never restore broad authenticated report SELECT.

revoke all on public.property_reports from public, anon, authenticated;
-- Table-level REVOKE does not remove pre-existing column privileges.
revoke select (markdown, xhs_content, rental, sale, images, raw_record,
               source_locator, source_id, report_version)
  on public.property_reports from public, anon, authenticated;

grant select (
  id, query_id, query_key, slug, title, publish_month, summary, data_sources,
  created_at, updated_at, owner_user_id, data_class, source_url, source_period,
  observed_at, transformation_version, limitations, report_status
) on public.property_reports to authenticated;

-- Preserve the established view shape without reading any restricted column.
-- Typed NULLs prevent direct selects, JSON serialization and embedded PostgREST
-- reads from reconstructing the report. New columns must be added explicitly.
create or replace view public.member_property_reports as
select
  r.id,
  r.query_id,
  r.query_key,
  r.slug,
  r.title,
  r.publish_month,
  null::text as markdown,
  null::text as xhs_content,
  null::jsonb as rental,
  null::jsonb as sale,
  r.summary,
  null::jsonb as images,
  r.data_sources,
  null::jsonb as raw_record,
  r.created_at,
  r.updated_at,
  r.owner_user_id,
  r.data_class,
  r.source_url,
  null::text as source_locator,
  r.source_period,
  r.observed_at,
  r.transformation_version,
  r.limitations,
  r.report_status,
  null::uuid as source_id,
  null::text as report_version,
  true as locked,
  false as unlocked,
  '完整深度报告与导出需通过已登录的报告接口验证付费权益。'::text as unlock_hint
from public.property_reports r;

alter view public.member_property_reports set (security_invoker = true);
revoke all on public.member_property_reports from public, anon, authenticated, service_role;
grant select on public.member_property_reports to authenticated, service_role;

-- Do not let disagreeing report/query ownership expose even preview metadata.
-- Keep legacy query-owned reports and explicitly owned orphan history readable.
drop policy if exists "owners can read own reports" on public.property_reports;
create policy "owners can read own reports"
on public.property_reports for select to authenticated
using (
  (owner_user_id is null or owner_user_id = (select auth.uid()))
  and (
    (query_id is null and owner_user_id = (select auth.uid()))
    or exists (
      select 1 from public.queries q
      where q.id = property_reports.query_id
        and q.owner_user_id = (select auth.uid())
    )
  )
);

comment on view public.member_property_reports is
  'Owner-scoped, security-invoker report previews only. Restricted fields are NULL. Full reports require the authenticated API payment/consumption check.';

-- Verification: authenticated table-wide and paid-column reads must be false,
-- preview-column reads true; service_role retains its existing full grants.
-- select has_table_privilege('authenticated','public.property_reports','SELECT'),
--        has_column_privilege('authenticated','public.property_reports','markdown','SELECT'),
--        has_column_privilege('authenticated','public.property_reports','summary','SELECT'),
--        has_table_privilege('service_role','public.property_reports','SELECT');
