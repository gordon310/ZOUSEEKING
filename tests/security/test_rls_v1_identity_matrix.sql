-- V1 RLS identity behavior matrix. Run against a disposable local database.
-- Fixtures contain transaction-scoped UUIDs and synthetic labels only.
begin;

insert into auth.users (
  id, aud, role, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
  ('00000000-0000-0000-0000-000000000401', 'authenticated', 'authenticated', '{}'::jsonb, '{}'::jsonb, now(), now()),
  ('00000000-0000-0000-0000-000000000402', 'authenticated', 'authenticated', '{}'::jsonb, '{}'::jsonb, now(), now());

insert into public.query_field_options (
  id, option_type, value, label, is_active
) values
  ('00000000-0000-0000-0000-000000000403', 'fixture', 'active', 'active fixture', true),
  ('00000000-0000-0000-0000-000000000404', 'fixture', 'inactive', 'inactive fixture', false);

insert into public.queries (
  id, query_key, prefecture, city, asset_type, year, month, owner_user_id
) values
  ('00000000-0000-0000-0000-000000000411', 'rls-v1-owner-query', 'fixture', 'fixture', 'fixture', 2026, 8, '00000000-0000-0000-0000-000000000401'),
  ('00000000-0000-0000-0000-000000000412', 'rls-v1-other-query', 'fixture', 'fixture', 'fixture', 2026, 8, '00000000-0000-0000-0000-000000000402');
insert into public.generation_jobs (id, query_id, status, progress) values
  ('00000000-0000-0000-0000-000000000421', '00000000-0000-0000-0000-000000000411', 'pending', 0),
  ('00000000-0000-0000-0000-000000000422', '00000000-0000-0000-0000-000000000412', 'pending', 0);
insert into public.property_reports (
  id, query_id, query_key, slug, title, publish_month, owner_user_id
) values
  ('00000000-0000-0000-0000-000000000431', '00000000-0000-0000-0000-000000000411', 'rls-v1-owner-report', 'rls-v1-owner-report', 'fixture', '2026-08', '00000000-0000-0000-0000-000000000401'),
  ('00000000-0000-0000-0000-000000000432', '00000000-0000-0000-0000-000000000412', 'rls-v1-other-report', 'rls-v1-other-report', 'fixture', '2026-08', '00000000-0000-0000-0000-000000000402');
insert into public.properties (id, owner_user_id, project_type, building_name) values
  ('00000000-0000-0000-0000-000000000441', '00000000-0000-0000-0000-000000000401', 'residential', 'owner fixture'),
  ('00000000-0000-0000-0000-000000000442', '00000000-0000-0000-0000-000000000402', 'residential', 'other fixture');
insert into public.user_profiles (user_id, bio, membership_tier, daily_query_limit) values
  ('00000000-0000-0000-0000-000000000401', 'owner fixture', 'free', 3),
  ('00000000-0000-0000-0000-000000000402', 'other fixture', 'free', 3);

-- Anon may read active field options only; all private/member access fails.
set local role anon;
do $$
declare active_rows integer; inactive_rows integer;
begin
  select count(*) into active_rows from public.query_field_options
  where id = '00000000-0000-0000-0000-000000000403';
  select count(*) into inactive_rows from public.query_field_options
  where id = '00000000-0000-0000-0000-000000000404';
  if active_rows <> 1 or inactive_rows <> 0 then
    raise exception 'anonymous field-option filter returned active=% inactive=%', active_rows, inactive_rows;
  end if;
  begin update public.query_field_options set label = 'anon write' where id = '00000000-0000-0000-0000-000000000403'; raise exception 'anonymous updated field option'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.queries where id = '00000000-0000-0000-0000-000000000411'; raise exception 'anonymous selected query'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.generation_jobs where id = '00000000-0000-0000-0000-000000000421'; raise exception 'anonymous selected job'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.property_reports where id = '00000000-0000-0000-0000-000000000431'; raise exception 'anonymous selected report'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.properties where id = '00000000-0000-0000-0000-000000000441'; raise exception 'anonymous selected property'; exception when insufficient_privilege then null; end;
  begin perform 1 from public.user_profiles where user_id = '00000000-0000-0000-0000-000000000401'; raise exception 'anonymous selected profile'; exception when insufficient_privilege then null; end;
end;
$$;
reset role;

-- Owner reads own rows and may update profile preferences only.
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000401', true);
select set_config('request.jwt.claim.role', 'authenticated', true);
do $$
declare visible_rows integer; changed_rows integer;
begin
  select (select count(*) from public.queries where id = '00000000-0000-0000-0000-000000000411')
       + (select count(*) from public.generation_jobs where id = '00000000-0000-0000-0000-000000000421')
       + (select count(*) from public.property_reports where id = '00000000-0000-0000-0000-000000000431')
       + (select count(*) from public.properties where id = '00000000-0000-0000-0000-000000000441')
       + (select count(*) from public.user_profiles where user_id = '00000000-0000-0000-0000-000000000401')
    into visible_rows;
  if visible_rows <> 5 then
    raise exception 'owner expected five visible rows, got %', visible_rows;
  end if;

  update public.user_profiles set bio = 'owner preference write'
  where user_id = '00000000-0000-0000-0000-000000000401';
  get diagnostics changed_rows = row_count;
  if changed_rows <> 1 then raise exception 'owner preference update affected % rows', changed_rows; end if;

  begin update public.user_profiles set membership_tier = 'matrix-tier' where user_id = '00000000-0000-0000-0000-000000000401'; raise exception 'owner changed membership_tier'; exception when insufficient_privilege then null; when raise_exception then if SQLERRM <> 'membership fields are server-managed' then raise; end if; end;
  begin update public.user_profiles set daily_query_limit = 99 where user_id = '00000000-0000-0000-0000-000000000401'; raise exception 'owner changed daily_query_limit'; exception when insufficient_privilege then null; when raise_exception then if SQLERRM <> 'membership fields are server-managed' then raise; end if; end;
  -- status is server-managed too (00600): the column grant was removed for
  -- authenticated, so either the privilege layer (insufficient_privilege) or
  -- the trigger guard may reject the write - both are acceptable.
  begin update public.user_profiles set status = 'suspended' where user_id = '00000000-0000-0000-0000-000000000401'; raise exception 'owner changed member status'; exception when insufficient_privilege then null; when raise_exception then if SQLERRM <> 'member status is server-managed' then raise; end if; end;
  begin insert into public.properties(owner_user_id, project_type) values ('00000000-0000-0000-0000-000000000401', 'residential'); raise exception 'owner inserted property directly'; exception when insufficient_privilege then null; end;
  begin update public.properties set building_name = 'owner direct write' where id = '00000000-0000-0000-0000-000000000441'; raise exception 'owner updated property directly'; exception when insufficient_privilege then null; end;
  begin update public.queries set owner_user_id = '00000000-0000-0000-0000-000000000402' where id = '00000000-0000-0000-0000-000000000411'; raise exception 'owner changed query owner'; exception when insufficient_privilege then null; when raise_exception then if SQLERRM <> 'owner_user_id is server-managed' then raise; end if; end;
  begin update public.property_reports set owner_user_id = '00000000-0000-0000-0000-000000000402' where id = '00000000-0000-0000-0000-000000000431'; raise exception 'owner changed report owner'; exception when insufficient_privilege then null; when raise_exception then if SQLERRM <> 'owner_user_id is server-managed' then raise; end if; end;
end;
$$;
reset role;

-- Other authenticated user sees no owner rows and cannot mutate them.
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000402', true);
select set_config('request.jwt.claim.role', 'authenticated', true);
do $$
declare visible_rows integer; changed_rows integer;
begin
  select (select count(*) from public.queries where id = '00000000-0000-0000-0000-000000000411')
       + (select count(*) from public.generation_jobs where id = '00000000-0000-0000-0000-000000000421')
       + (select count(*) from public.property_reports where id = '00000000-0000-0000-0000-000000000431')
       + (select count(*) from public.properties where id = '00000000-0000-0000-0000-000000000441')
       + (select count(*) from public.user_profiles where user_id = '00000000-0000-0000-0000-000000000401')
    into visible_rows;
  if visible_rows <> 0 then raise exception 'other user observed % owner rows', visible_rows; end if;
  update public.user_profiles set bio = 'other write'
  where user_id = '00000000-0000-0000-0000-000000000401';
  get diagnostics changed_rows = row_count;
  if changed_rows <> 0 then raise exception 'other user updated % owner profiles', changed_rows; end if;
  begin update public.properties set building_name = 'other direct write' where id = '00000000-0000-0000-0000-000000000441'; exception when insufficient_privilege then null; end;
end;
$$;
reset role;

-- Service worker may write through the trusted role but cannot bypass checks.
set local role service_role;
select set_config('request.jwt.claim.role', 'service_role', true);
insert into public.queries (
  id, query_key, prefecture, city, asset_type, year, month, owner_user_id
) values (
  '00000000-0000-0000-0000-000000000451', 'rls-v1-worker-query',
  'fixture', 'fixture', 'fixture', 2026, 8,
  '00000000-0000-0000-0000-000000000401'
);
insert into public.generation_jobs (id, query_id, status, progress) values
  ('00000000-0000-0000-0000-000000000452', '00000000-0000-0000-0000-000000000451', 'running', 1);
insert into public.property_reports (
  id, query_id, query_key, slug, title, publish_month, owner_user_id
) values (
  '00000000-0000-0000-0000-000000000453',
  '00000000-0000-0000-0000-000000000451',
  'rls-v1-worker-report', 'rls-v1-worker-report', 'fixture', '2026-08',
  '00000000-0000-0000-0000-000000000401'
);
insert into public.properties (id, owner_user_id, project_type, building_name) values
  ('00000000-0000-0000-0000-000000000454', '00000000-0000-0000-0000-000000000401', 'residential', 'worker fixture');
update public.user_profiles set membership_tier = 'matrix-tier', daily_query_limit = 9
where user_id = '00000000-0000-0000-0000-000000000401';
do $$
begin
  begin
    insert into public.generation_jobs (id, query_id, progress) values
      ('00000000-0000-0000-0000-000000000455', '00000000-0000-0000-0000-000000000451', 101);
    raise exception 'service worker bypassed generation_jobs_progress_check';
  exception when check_violation then null;
  end;
end;
$$;
reset role;

do $$
declare owner_id uuid := '00000000-0000-0000-0000-000000000401';
begin
  if (select owner_user_id from public.queries where id = '00000000-0000-0000-0000-000000000411') <> owner_id then raise exception 'owner query ownership changed'; end if;
  if (select owner_user_id from public.property_reports where id = '00000000-0000-0000-0000-000000000431') <> owner_id then raise exception 'owner report ownership changed'; end if;
  if (select owner_user_id from public.properties where id = '00000000-0000-0000-0000-000000000441') <> owner_id then raise exception 'owner property ownership changed'; end if;
  if (select building_name from public.properties where id = '00000000-0000-0000-0000-000000000441') <> 'owner fixture' then raise exception 'untrusted property mutation persisted'; end if;
  if (select membership_tier from public.user_profiles where user_id = owner_id) <> 'matrix-tier'
     or (select daily_query_limit from public.user_profiles where user_id = owner_id) <> 9
     or (select bio from public.user_profiles where user_id = owner_id) <> 'owner preference write' then
    raise exception 'expected worker/profile writes were not preserved';
  end if;
end;
$$;

rollback;
