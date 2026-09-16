-- M-B2 organization export idempotency. Additive forward migration only.
alter table public.exports
  add column if not exists idempotency_key text;

create unique index if not exists uq_exports_org_owner_idempotency
  on public.exports(organization_id, owner_user_id, idempotency_key)
  where idempotency_key is not null;
