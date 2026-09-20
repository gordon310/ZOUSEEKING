-- Four-identity contract for browser member-read views. Run after the full
-- canonical migration history in a disposable Supabase/PostgreSQL database.

begin;

insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-000000009301', 'view-owner@example.invalid'),
  ('00000000-0000-0000-0000-000000009302', 'view-other@example.invalid')
on conflict (id) do update set email = excluded.email;

insert into public.user_profiles (user_id, email, bio) values
  ('00000000-0000-0000-0000-000000009301', 'view-owner@example.invalid', 'owner profile'),
  ('00000000-0000-0000-0000-000000009302', 'view-other@example.invalid', 'other profile')
on conflict (user_id) do update set bio = excluded.bio;

insert into public.queries (
  id, query_key, prefecture, city, ward, asset_type, year, month,
  owner_user_id, requested_by_email
) values (
  '00000000-0000-0000-0000-000000009303', 'member-view-owner-query',
  'Tokyo', 'Chiyoda', '', 'apartment', 2026, 9,
  '00000000-0000-0000-0000-000000009301', 'view-owner@example.invalid'
);

insert into public.generation_jobs (id, query_id, status, progress, current_step)
values (
  '00000000-0000-0000-0000-000000009304',
  '00000000-0000-0000-0000-000000009303', 'completed', 100, 'done'
);

insert into public.property_reports (
  id, query_id, query_key, slug, title, publish_month, owner_user_id
) values (
  '00000000-0000-0000-0000-000000009305',
  '00000000-0000-0000-0000-000000009303', 'member-view-owner-report',
  'member-view-owner-report', 'owner report', '2026-09',
  '00000000-0000-0000-0000-000000009301'
);

set local role anon;
do $$
declare view_name text;
begin
  foreach view_name in array array['member_queries', 'member_property_reports', 'member_profiles'] loop
    begin
      execute format('select * from public.%I limit 1', view_name);
      raise exception 'anon read %', view_name;
    exception when insufficient_privilege then null; end;
  end loop;
end $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.role', 'authenticated', true);
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000009301', true);
do $$
declare count_rows integer;
begin
  select count(*) into count_rows from public.member_queries where id = '00000000-0000-0000-0000-000000009303';
  if count_rows <> 1 then raise exception 'owner could not read own query view (%)', count_rows; end if;
  select count(*) into count_rows from public.member_property_reports where id = '00000000-0000-0000-0000-000000009305';
  if count_rows <> 1 then raise exception 'owner could not read own report view (%)', count_rows; end if;
  select count(*) into count_rows from public.member_profiles where user_id = '00000000-0000-0000-0000-000000009301';
  if count_rows <> 1 then raise exception 'owner could not read own profile view (%)', count_rows; end if;
  begin update public.member_profiles set bio = 'blocked' where user_id = '00000000-0000-0000-0000-000000009301';
    raise exception 'authenticated wrote member view'; exception when insufficient_privilege then null; end;
end $$;
reset role;

set local role authenticated;
select set_config('request.jwt.claim.role', 'authenticated', true);
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000009302', true);
do $$
declare count_rows integer;
begin
  select count(*) into count_rows from public.member_queries where id = '00000000-0000-0000-0000-000000009303';
  if count_rows <> 0 then raise exception 'other user read owner query view (%)', count_rows; end if;
  select count(*) into count_rows from public.member_property_reports where id = '00000000-0000-0000-0000-000000009305';
  if count_rows <> 0 then raise exception 'other user read owner report view (%)', count_rows; end if;
  select count(*) into count_rows from public.member_profiles where user_id = '00000000-0000-0000-0000-000000009301';
  if count_rows <> 0 then raise exception 'other user read owner profile view (%)', count_rows; end if;
end $$;
reset role;

set local role service_role;
do $$
declare count_rows integer;
begin
  select count(*) into count_rows from public.member_queries where id = '00000000-0000-0000-0000-000000009303';
  if count_rows <> 1 then raise exception 'service_role could not read query view (%)', count_rows; end if;
  select count(*) into count_rows from public.member_property_reports where id = '00000000-0000-0000-0000-000000009305';
  if count_rows <> 1 then raise exception 'service_role could not read report view (%)', count_rows; end if;
  select count(*) into count_rows from public.member_profiles where user_id = '00000000-0000-0000-0000-000000009301';
  if count_rows <> 1 then raise exception 'service_role could not read profile view (%)', count_rows; end if;
  begin update public.member_queries set status = 'failed' where id = '00000000-0000-0000-0000-000000009303';
    raise exception 'service_role wrote member view'; exception when insufficient_privilege then null; end;
end $$;
reset role;

rollback;
