-- MB1.5 RLS matrix. Run after all migrations in a disposable database.
begin;
insert into auth.users(id,email) values
 ('00000000-0000-0000-0000-000000000301','rls-owner@example.com'),
 ('00000000-0000-0000-0000-000000000302','rls-member@example.com'),
 ('00000000-0000-0000-0000-000000000303','rls-outsider@example.com');
insert into public.organizations(id,name,created_by_user_id)
 values('00000000-0000-0000-0000-000000000304','RLS invitation org','00000000-0000-0000-0000-000000000301');
insert into public.organization_members(organization_id,user_id,role)
 values
 ('00000000-0000-0000-0000-000000000304','00000000-0000-0000-0000-000000000301','owner'),
 ('00000000-0000-0000-0000-000000000304','00000000-0000-0000-0000-000000000302','member');
insert into public.organization_invitations(organization_id,email,role,token_hash,created_by_user_id,expires_at)
 values('00000000-0000-0000-0000-000000000304','rls-member2@example.com','member',repeat('a',64),'00000000-0000-0000-0000-000000000301',now()+interval '7 days');

set local role authenticated;
set local "request.jwt.claim.sub"='00000000-0000-0000-0000-000000000301';
do $$ begin
  if (select count(*) from public.organization_invitations) <> 1 then raise exception 'owner cannot read invitation'; end if;
end $$;
set local "request.jwt.claim.sub"='00000000-0000-0000-0000-000000000302';
do $$ begin
  if (select count(*) from public.organization_invitations) <> 0 then raise exception 'member can read invitation'; end if;
end $$;
set local "request.jwt.claim.sub"='00000000-0000-0000-0000-000000000303';
do $$ begin
  if (select count(*) from public.organization_invitations) <> 0 then raise exception 'outsider can read invitation'; end if;
end $$;
rollback;

