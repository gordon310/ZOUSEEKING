-- Controlled deletion ledger. auth.users and usage_events are retained.
-- Release procedure: take the normal provider backup before applying; verify
-- the new table/RLS assertion; rollback is a forward fix (drop is forbidden
-- after application) and no existing migration is edited.
create table if not exists public.account_deletion_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete restrict,
  status text not null default 'pending',
  policy_version text not null,
  terms_version text not null,
  requested_at timestamptz not null,
  acknowledgement_due timestamptz not null,
  access_restriction_due timestamptz not null,
  primary_data_deletion_due timestamptz not null,
  backup_expiry_due timestamptz not null,
  executed_at timestamptz,
  failure_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint account_deletion_requests_status_check check (status in ('pending', 'executing', 'completed', 'failed')),
  constraint account_deletion_requests_failure_reason_check check (failure_reason is null or char_length(failure_reason) <= 200),
  constraint account_deletion_requests_dates_check check (
    acknowledgement_due >= requested_at and access_restriction_due >= requested_at
    and primary_data_deletion_due >= requested_at and backup_expiry_due >= requested_at
  )
);
create unique index if not exists uq_account_deletion_requests_active_user
  on public.account_deletion_requests(user_id) where status in ('pending', 'executing');
create unique index if not exists uq_account_deletion_requests_user
  on public.account_deletion_requests(user_id);
create index if not exists idx_account_deletion_requests_status_due
  on public.account_deletion_requests(status, primary_data_deletion_due);
drop trigger if exists set_account_deletion_requests_updated_at on public.account_deletion_requests;
create trigger set_account_deletion_requests_updated_at before update on public.account_deletion_requests
for each row execute function public.set_updated_at();
alter table public.account_deletion_requests enable row level security;
revoke all on public.account_deletion_requests from anon, authenticated;
grant select on public.account_deletion_requests to authenticated;
grant all on public.account_deletion_requests to service_role;
create policy "users can read own account deletion requests"
on public.account_deletion_requests for select to authenticated
using (user_id = (select auth.uid()));
