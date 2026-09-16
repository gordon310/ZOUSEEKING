-- M-B2 organization export ownership. Additive forward migration only.
alter table public.exports
  add column if not exists organization_id uuid references public.organizations(id) on delete cascade;

create index if not exists idx_exports_organization_owner_created
  on public.exports(organization_id, owner_user_id, created_at desc);
