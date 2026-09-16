-- MB1.5 invitation schema contract. Run after the canonical migrations.
begin;
do $$
declare
  required text[] := array['id','organization_id','email','role','token_hash','created_by_user_id','expires_at','accepted_at','accepted_by_user_id','revoked_at','created_at','updated_at'];
  item text;
begin
  if to_regclass('public.organization_invitations') is null then
    raise exception 'organization_invitations table missing';
  end if;
  foreach item in array required loop
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='organization_invitations' and column_name=item) then
      raise exception 'organization_invitations column missing: %', item;
    end if;
  end loop;
  if not exists (select 1 from pg_class where oid='public.organization_invitations'::regclass and relrowsecurity) then
    raise exception 'organization_invitations RLS is not enabled';
  end if;
  if not exists (select 1 from pg_constraint where conrelid='public.organization_invitations'::regclass and contype='u' and pg_get_constraintdef(oid) like '%token_hash%') then
    raise exception 'token_hash unique constraint missing';
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='organization_invitations' and policyname='organization managers can read invitations') then
    raise exception 'manager invitation SELECT policy missing';
  end if;
end $$;
select 1 as invitation_contract_probe from public.organization_invitations where false;
rollback;
