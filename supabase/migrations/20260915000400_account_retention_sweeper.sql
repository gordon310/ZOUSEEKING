-- Additive retention evidence for completed account deletion requests.
-- The sweeper records provider-backup expiry; it does not mutate provider
-- backups, auth.users, or append-only usage_events.
alter table public.account_deletion_requests
  add column if not exists backup_expired_at timestamptz;

create index if not exists idx_account_deletion_requests_backup_expiry_due
  on public.account_deletion_requests(backup_expiry_due)
  where status = 'completed' and backup_expired_at is null;

comment on column public.account_deletion_requests.backup_expired_at is
  'UTC fact timestamp recorded once the provider backup retention deadline has passed; provider backup deletion is not performed by this job';
