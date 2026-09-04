-- V1 organizations: identity and membership-seat domain (spec section 2).
-- Adds public.organizations (B-side organization profile plus the
-- certification-partner status machine) and public.organization_members
-- (member seats: at most 5 active members per organization including the
-- owner, and at most one active owner).
--
-- Access contract:
--   * organization_members.user_id is the ownership boundary for
--     org-scoped data. RLS lets an authenticated user read the organization
--     rows they belong to and their own membership rows only.
--   * All inserts -- organizations and memberships -- are trusted-backend
--     only: service_role bypasses RLS and holds full privileges; anon and
--     authenticated hold no write grants and no INSERT policies exist.
--   * partner_status, membership role, and membership status are
--     server-managed fields, so no browser path can write them.
--   * The active owner may update only the organization display-name column
--     (column-level grant + RLS policy). Owner-driven member deactivation,
--     invitations, and role changes intentionally go through the trusted
--     backend in V1 so seat-cap, single-owner, and audit invariants hold in
--     one transaction; organization_members therefore exposes SELECT only.
--   * created_by_user_id is provenance, not ownership: it is ON DELETE SET
--     NULL so an organization survives its founder's account deletion
--     (membership rows terminate their own access via the member FK cascade).

do $$
declare
  required_table text;
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;

  if to_regprocedure('public.set_updated_at()') is null then
    raise exception 'missing prerequisite function: public.set_updated_at()';
  end if;

  foreach required_table in array array[
    'public.organizations', 'public.organization_members'
  ] loop
    if to_regclass(required_table) is not null then
      raise exception 'v1 organizations migration already applied: %', required_table;
    end if;
  end loop;
end $$;

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  partner_status text not null default 'none',
  created_by_user_id uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organizations_name_length_check check (
    nullif(btrim(name), '') is not null
    and char_length(btrim(name)) <= 120
  ),
  constraint organizations_partner_status_check check (
    partner_status in ('none', 'pending', 'certified', 'suspended')
  )
);

alter table public.organizations enable row level security;

create table if not exists public.organization_members (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint organization_members_role_allowed check (role in ('owner', 'member')),
  constraint organization_members_status_allowed check (status in ('active', 'inactive')),
  constraint organization_members_unique_membership unique (organization_id, user_id)
);

alter table public.organization_members enable row level security;

-- RLS self-scope lookups (user_id = auth.uid()) drive both SELECT policies;
-- owner scope first, per the "owner-scope-first composite index" rule.
create index if not exists idx_organization_members_user_org
  on public.organization_members(user_id, organization_id);

-- At most one active owner per organization. The <=5 active-seat cap is
-- enforced by the trigger below (a partial unique index cannot express it).
create unique index if not exists uq_organization_members_active_owner
  on public.organization_members(organization_id)
  where role = 'owner' and status = 'active';

-- Trusted worker/backend writes; RLS remains enforced for the other roles.
grant all privileges on public.organizations, public.organization_members to service_role;

revoke all on public.organizations, public.organization_members from anon, authenticated;

grant select on public.organizations, public.organization_members to authenticated;

-- Active owners may edit only the organization display-name column. No other
-- column of organizations -- and nothing on organization_members -- is
-- browser-writable (server-managed fields stay service_role-only).
grant update (name) on public.organizations to authenticated;

create policy "members can read organizations they belong to"
on public.organizations
for select to authenticated
using (
  exists (
    select 1
    from public.organization_members m
    where m.organization_id = organizations.id
      and m.user_id = (select auth.uid())
  )
);

create policy "active owners can update their organization profile"
on public.organizations
for update to authenticated
using (
  exists (
    select 1
    from public.organization_members m
    where m.organization_id = organizations.id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.status = 'active'
  )
)
with check (
  exists (
    select 1
    from public.organization_members m
    where m.organization_id = organizations.id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.status = 'active'
  )
);

create policy "members can read their own memberships"
on public.organization_members
for select to authenticated
using (user_id = (select auth.uid()));

-- Enforce the B-side seat cap: at most 5 active members per organization,
-- owner included. Fires on insert and on any update (no-op updates that do
-- not change active-seat accounting are skipped). SECURITY DEFINER so the
-- count is never filtered by the caller's RLS scope; search_path is pinned
-- and the function is not callable by anon/authenticated.
create or replace function public.enforce_organization_member_active_seat_cap()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  active_count integer;
begin
  if tg_op = 'UPDATE'
     and new.organization_id is not distinct from old.organization_id
     and new.status = old.status then
    return new;
  end if;

  if new.status = 'active' then
    select count(*)
      into active_count
    from public.organization_members
    where organization_id = new.organization_id
      and status = 'active';

    if active_count + 1 > 5 then
      raise exception
        'organization % exceeds the maximum of 5 active members (owner included)',
        new.organization_id;
    end if;
  end if;

  return new;
end;
$$;

revoke all on function public.enforce_organization_member_active_seat_cap()
from public, anon, authenticated;

drop trigger if exists enforce_organization_member_active_seat_cap
  on public.organization_members;
create trigger enforce_organization_member_active_seat_cap
before insert or update on public.organization_members
for each row execute function public.enforce_organization_member_active_seat_cap();

drop trigger if exists set_organizations_updated_at on public.organizations;
create trigger set_organizations_updated_at
before update on public.organizations
for each row execute function public.set_updated_at();

drop trigger if exists set_organization_members_updated_at
  on public.organization_members;
create trigger set_organization_members_updated_at
before update on public.organization_members
for each row execute function public.set_updated_at();
