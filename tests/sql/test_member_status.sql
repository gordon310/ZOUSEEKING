-- Member account status assertions (migration 20260905000600_member_status).
-- Run against a disposable Supabase/PostgreSQL database only, AFTER the full
-- canonical history up to 20260905000600 has been applied (roles
-- anon/authenticated/service_role must exist). The behavioural probes insert
-- one throwaway row and mutate status inside sub-transactions that roll back,
-- so the member row set is left untouched.
do $$
declare
  v_msg text;
  v_probe_id uuid;
begin
  -- 0. Expected Supabase roles must exist before privilege assertions.
  if to_regrole('anon') is null
     or to_regrole('authenticated') is null
     or to_regrole('service_role') is null then
    raise exception 'expected Supabase roles anon/authenticated/service_role';
  end if;

  -- 1. Prerequisite table and column exist.
  if to_regclass('public.user_profiles') is null then
    raise exception 'missing table: public.user_profiles';
  end if;
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'user_profiles'
      and column_name = 'status'
  ) then
    raise exception 'missing column: public.user_profiles.status';
  end if;

  -- 2. Column contract: text, not null, default 'active'.
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'user_profiles'
      and column_name = 'status' and data_type = 'text'
      and is_nullable = 'NO' and column_default = '''active''::text'
  ) then
    raise exception 'user_profiles.status must be text not null default active';
  end if;

  -- 3. Named CHECK constraint exists and admits exactly the two states.
  if not exists (
    select 1
    from pg_constraint pc
    join pg_class tc on tc.oid = pc.conrelid
    join pg_namespace pn on pn.oid = tc.relnamespace
    where pn.nspname = 'public' and tc.relname = 'user_profiles'
      and pc.conname = 'user_profiles_status_allowed'
      and pc.contype = 'c'
  ) then
    raise exception 'missing check constraint user_profiles_status_allowed';
  end if;

  -- 4. Privilege contract: authenticated cannot UPDATE the status column
  --    (column-level revoke), but keeps UPDATE on the client preference
  --    columns; anon has nothing; service_role keeps full UPDATE.
  if has_column_privilege('authenticated', 'public.user_profiles', 'status', 'UPDATE') then
    raise exception 'authenticated must not hold UPDATE on user_profiles.status';
  end if;
  if not has_column_privilege('authenticated', 'public.user_profiles', 'display_name', 'UPDATE') then
    raise exception 'authenticated must keep UPDATE on user_profiles.display_name';
  end if;
  if not has_column_privilege('authenticated', 'public.user_profiles', 'bio', 'UPDATE') then
    raise exception 'authenticated must keep UPDATE on user_profiles.bio';
  end if;
  if has_column_privilege('authenticated', 'public.user_profiles', 'membership_tier', 'UPDATE') then
    raise exception 'authenticated must not hold UPDATE on user_profiles.membership_tier';
  end if;
  if has_column_privilege('anon', 'public.user_profiles', 'status', 'UPDATE')
     or has_column_privilege('anon', 'public.user_profiles', 'display_name', 'UPDATE') then
    raise exception 'anon must hold no UPDATE on user_profiles';
  end if;
  if not has_column_privilege('service_role', 'public.user_profiles', 'status', 'UPDATE') then
    raise exception 'service_role must keep UPDATE on user_profiles.status';
  end if;

  -- 5. The existing profile update RLS policy still exists (self-row scope) so
  --    the preference-update feature is unchanged; the fence above limits what
  --    it can write.
  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public' and tablename = 'user_profiles'
      and policyname = 'users can update own profile preferences'
      and cmd = 'UPDATE' and roles = '{authenticated}'
  ) then
    raise exception 'expected self-row profile update policy to remain in place';
  end if;

  -- 6. Behavioural probes (self-rolled-back sub-transactions).  Re-runnable:
  -- the two probe rows are removed first so a repeated run on the same
  -- disposable database starts from a clean state.
  delete from public.user_profiles
  where user_id = '00000000-0000-0000-0000-000000000901';
  delete from auth.users
  where id = '00000000-0000-0000-0000-000000000901';
  insert into auth.users (id, email)
  values ('00000000-0000-0000-0000-000000000901', 'probe901@example.test');
  insert into public.user_profiles (user_id)
  values ('00000000-0000-0000-0000-000000000901')
  returning user_id into v_probe_id;

  -- 6a. Trigger: a non-service writer that somehow holds UPDATE on status
  --     (temporary grant inside the probe, rolled back with it) is refused by
  --     the server-managed guard, not silently accepted.
  begin
    grant update (status) on public.user_profiles to authenticated;
    alter table public.user_profiles disable row level security;
    set local role authenticated;
    update public.user_profiles
    set status = 'suspended'
    where user_id = v_probe_id;
    raise exception 'status UPDATE by authenticated was not rejected';
  exception when others then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'server-managed' then raise; end if;
  end;

  -- 6b. Trigger: INSERTing a non-active status as a non-service writer is
  --     refused the same way.
  begin
    alter table public.user_profiles disable row level security;
    set local role authenticated;
    insert into public.user_profiles (user_id, status)
    values ('00000000-0000-0000-0000-000000000902', 'suspended');
    raise exception 'status INSERT by authenticated was not rejected';
  exception when others then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'server-managed' then raise; end if;
  end;

  -- 6c. CHECK constraint: a service writer cannot store a value outside the
  --     two-state vocabulary (probe transaction rolls back on the error).
  begin
    update public.user_profiles
    set status = 'banned'
    where user_id = v_probe_id;
    raise exception 'out-of-vocabulary status was accepted';
  exception when others then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'user_profiles_status_allowed' then raise; end if;
  end;

  raise notice 'test_member_status: all assertions passed';
end $$;
