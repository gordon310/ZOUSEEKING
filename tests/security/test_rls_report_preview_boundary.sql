-- Synthetic, transactional four-identity regression. Run after all migrations
-- on disposable PostgreSQL/Supabase; this script always rolls its fixtures back.
begin;

insert into auth.users(id, email) values
 ('00000000-0000-0000-0000-000000009701', 'preview-owner@fixture.invalid'),
 ('00000000-0000-0000-0000-000000009702', 'preview-other@fixture.invalid');

insert into public.queries(id, query_key, owner_user_id, prefecture, city, ward, asset_type, year, month)
values
 ('00000000-0000-0000-0000-000000009711', 'preview-owned', '00000000-0000-0000-0000-000000009701', 'Tokyo', 'Chiyoda', '', 'apartment', 2026, 10),
 ('00000000-0000-0000-0000-000000009712', 'preview-other', '00000000-0000-0000-0000-000000009702', 'Tokyo', 'Chiyoda', '', 'apartment', 2026, 10),
 ('00000000-0000-0000-0000-000000009713', 'preview-conflict', '00000000-0000-0000-0000-000000009701', 'Tokyo', 'Chiyoda', '', 'apartment', 2026, 10),
 ('00000000-0000-0000-0000-000000009714', 'preview-legacy', '00000000-0000-0000-0000-000000009701', 'Tokyo', 'Chiyoda', '', 'apartment', 2026, 10);

insert into public.property_reports(
 query_id, query_key, slug, title, publish_month, owner_user_id,
 markdown, xhs_content, rental, sale, images, raw_record, summary, data_sources,
 report_status, data_class, source_period, observed_at, transformation_version,
 report_version, limitations, source_locator
)
select query_id, report_key, report_key, 'preview title', '2026-10', report_owner,
 'paid-only-markdown', 'paid-only-xhs', '["paid-only-rental"]'::jsonb,
 '["paid-only-sale"]'::jsonb, '["paid-only-image"]'::jsonb,
 '{"content":"paid-only-raw"}'::jsonb,
 '{"line":"free summary"}'::jsonb,
 '[{"url":"https://example.invalid/synthetic-source"}]'::jsonb,
 'full_report', 'synthetic_fixture'::public.data_class, '2026-10', now(),
 'synthetic-v1', 'synthetic-v1', 'Synthetic fixture only', 'paid-only-locator'
from (values
 ('00000000-0000-0000-0000-000000009711'::uuid, 'preview-owned', '00000000-0000-0000-0000-000000009701'::uuid),
 ('00000000-0000-0000-0000-000000009712'::uuid, 'preview-other', '00000000-0000-0000-0000-000000009702'::uuid),
 ('00000000-0000-0000-0000-000000009713'::uuid, 'preview-conflict', '00000000-0000-0000-0000-000000009702'::uuid),
 ('00000000-0000-0000-0000-000000009714'::uuid, 'preview-legacy', null::uuid),
 (null::uuid, 'preview-orphan', '00000000-0000-0000-0000-000000009701'::uuid)
) as fixtures(query_id, report_key, report_owner);

do $$
declare field text;
begin
 if has_table_privilege('authenticated', 'public.property_reports', 'select') then
   raise exception 'authenticated retains full report SELECT';
 end if;
 foreach field in array array['markdown','xhs_content','rental','sale','images','raw_record','source_locator','source_id','report_version'] loop
   if has_column_privilege('authenticated', 'public.property_reports', field, 'select')
      or has_column_privilege('anon', 'public.property_reports', field, 'select') then
     raise exception 'restricted column is readable: %', field;
   end if;
 end loop;
 if not has_column_privilege('authenticated', 'public.property_reports', 'summary', 'select') then
   raise exception 'free summary column unavailable';
 end if;
 if not has_table_privilege('service_role', 'public.property_reports', 'select,insert,update') then
   raise exception 'trusted writer grants changed';
 end if;
 if not exists (select 1 from pg_class where oid='public.member_property_reports'::regclass
                and 'security_invoker=true'=any(reloptions)) then
   raise exception 'preview view is not security_invoker';
 end if;
end $$;

set local role anon;
do $$
begin
 begin perform * from public.member_property_reports;
   raise exception 'anon read preview view';
 exception when insufficient_privilege then null; end;
 begin perform title from public.property_reports;
   raise exception 'anon read direct report metadata';
 exception when insufficient_privilege then null; end;
end $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.role', 'authenticated', true);
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000009701', true);
do $$
declare preview jsonb; probe text; count_rows integer;
begin
 select to_jsonb(r) into preview from public.member_property_reports r where query_key='preview-owned';
 if preview is null or preview->>'title'<>'preview title'
    or preview->'summary'->>'line'<>'free summary'
    or preview->>'locked'<>'true' or preview->>'unlocked'<>'false'
    or preview::text like '%paid-only-%' then
   raise exception 'unpaid owner preview is missing or discloses paid content: %', preview;
 end if;
 if preview->>'markdown' is not null or preview->>'raw_record' is not null then
   raise exception 'compatibility columns must be NULL';
 end if;
 select count(*) into count_rows from public.member_property_reports where query_key like 'preview-%';
 if count_rows<>3 then raise exception 'owner history/legacy/orphan isolation changed: %', count_rows; end if;
 if exists (select 1 from public.member_property_reports where query_key in ('preview-other','preview-conflict')) then
   raise exception 'owner read another or conflicting report';
 end if;
 foreach probe in array array[
   'select * from public.property_reports',
   'select markdown from public.property_reports',
   'select raw_record from public.property_reports',
   'select to_jsonb(r) from public.property_reports r',
   'select row_to_json(r) from public.property_reports r',
   'select json_agg(r) from public.property_reports r',
   'select title from public.property_reports where markdown like ''%paid-only%''',
   'select q.id, r.markdown from public.queries q join public.property_reports r on r.query_id=q.id',
   'update public.member_property_reports set title=''changed''',
   'update public.property_reports set title=''changed'''
 ] loop
   begin execute probe; raise exception 'restricted report query succeeded: %', probe;
   exception when insufficient_privilege then null; end;
 end loop;
end $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000009702', true);
do $$
declare count_rows integer;
begin
 select count(*) into count_rows from public.member_property_reports where query_key like 'preview-%';
 if count_rows<>1 then raise exception 'other-user/conflicting-owner isolation changed: %', count_rows; end if;
 if exists (select 1 from public.member_property_reports where query_key in ('preview-owned','preview-conflict','preview-legacy','preview-orphan')) then
   raise exception 'other user read owner metadata';
 end if;
end $$;
reset role;

set local role service_role;
select set_config('request.jwt.claim.role', 'service_role', true);
do $$
declare body text;
begin
 select markdown into body from public.property_reports where query_key='preview-owned';
 if body is distinct from 'paid-only-markdown' then raise exception 'trusted reader lost full content'; end if;
 update public.property_reports set markdown='paid-only-writer-update' where query_key='preview-owned';
 select markdown into body from public.property_reports where query_key='preview-owned';
 if body is distinct from 'paid-only-writer-update' then raise exception 'trusted writer failed'; end if;
 if exists (select 1 from public.member_property_reports where markdown is not null) then
   raise exception 'member preview view exposed contents to its caller';
 end if;
end $$;
reset role;

do $$
begin
 if exists (select 1 from public.usage_events where scope_key in (
   'user:00000000-0000-0000-0000-000000009701',
   'user:00000000-0000-0000-0000-000000009702')) then
   raise exception 'report reads consumed usage';
 end if;
end $$;
rollback;
