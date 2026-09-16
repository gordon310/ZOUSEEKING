-- MB1.5: trusted organization invitations and additive admin-member role support.
-- Forward-only: existing organization columns and rows are preserved.

do $$
begin
  if to_regclass('public.organizations') is null
     or to_regclass('public.organization_members') is null
     or to_regclass('auth.users') is null then
    raise exception 'MB1.5 prerequisites are missing';
  end if;
end $$;

alter table public.organization_members
  drop constraint if exists organization_members_role_allowed;
alter table public.organization_members
  add constraint organization_members_role_allowed
  check (role in ('owner', 'admin', 'member'));

create table if not exists public.organization_invitations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  email text not null,
  role text not null check (role in ('owner', 'admin', 'member')),
  token_hash char(64) not null unique,
  created_by_user_id uuid not null references auth.users(id) on delete restrict,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  accepted_by_user_id uuid references auth.users(id) on delete set null,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organization_invitations_email_check check (
    email = lower(btrim(email)) and email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
  ),
  constraint organization_invitations_token_hash_check check (token_hash ~ '^[0-9a-f]{64}$'),
  constraint organization_invitations_expiry_check check (expires_at > created_at),
  constraint organization_invitations_acceptance_check check (
    (accepted_at is null and accepted_by_user_id is null)
    or (accepted_at is not null and accepted_by_user_id is not null)
  )
);

create index if not exists idx_org_invitations_org_created
  on public.organization_invitations(organization_id, created_at desc);
create index if not exists idx_org_invitations_pending_email
  on public.organization_invitations(organization_id, email)
  where accepted_at is null and revoked_at is null;

create or replace function public.set_organization_invitations_updated_at()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_organization_invitations_updated_at on public.organization_invitations;
create trigger set_organization_invitations_updated_at
before update on public.organization_invitations
for each row execute function public.set_organization_invitations_updated_at();

alter table public.organization_invitations enable row level security;
revoke all on public.organization_invitations from anon, authenticated;
grant all privileges on public.organization_invitations to service_role;
grant select on public.organization_invitations to authenticated;

create policy "organization managers can read invitations"
on public.organization_invitations for select to authenticated
using (exists (
  select 1 from public.organization_members om
  where om.organization_id = organization_invitations.organization_id
    and om.user_id = (select auth.uid())
    and om.role in ('owner', 'admin')
    and om.status = 'active'
));

revoke all on function public.set_organization_invitations_updated_at() from public, anon, authenticated;

