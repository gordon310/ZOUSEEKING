-- Retain the account-deletion audit request after its Auth subject is removed.
-- The prior RESTRICT FK made a completed identity deletion impossible; this
-- forward-only change de-identifies the retained ledger row instead.

alter table public.account_deletion_requests
  alter column user_id drop not null;

alter table public.account_deletion_requests
  drop constraint if exists account_deletion_requests_user_id_fkey;

alter table public.account_deletion_requests
  add constraint account_deletion_requests_user_id_fkey
  foreign key (user_id) references auth.users(id) on delete set null;
