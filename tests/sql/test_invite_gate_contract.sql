-- Invite-only registration schema contract. Run after canonical migrations.
begin;
do $$
declare
  required text[] := array['id','code','label','note','max_uses','used_count','expires_at','enabled','created_at','created_by','last_used_at'];
  item text;
begin
  if to_regclass('public.invite_codes') is null or to_regclass('public.invite_redemptions') is null then
    raise exception 'invite tables missing';
  end if;
  foreach item in array required loop
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='invite_codes' and column_name=item) then
      raise exception 'invite_codes column missing: %', item;
    end if;
  end loop;
  if not exists (select 1 from pg_class where oid='public.invite_codes'::regclass and relrowsecurity) then
    raise exception 'invite_codes RLS is not enabled';
  end if;
  if exists (select 1 from information_schema.role_table_grants where table_schema='public' and table_name in ('invite_codes','invite_redemptions') and grantee in ('anon','authenticated')) then
    raise exception 'invite tables must not grant anon/authenticated access';
  end if;
  if not exists (select 1 from pg_proc where pronamespace='public'::regnamespace and proname='reserve_invite_code') then
    raise exception 'atomic invite reservation function missing';
  end if;
end $$;
rollback;
