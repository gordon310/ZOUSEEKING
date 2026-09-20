-- Run after the canonical migrations in a disposable PostgreSQL/Supabase DB.
do $$
declare
  policy_using text;
begin
  if to_regclass('public.account_deletion_requests') is null then
    raise exception 'account deletion ledger is missing';
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.account_deletion_requests'::regclass
      and conname = 'account_deletion_requests_status_check'
  ) then
    raise exception 'account deletion status check is missing';
  end if;
  if not exists (
    select 1 from pg_indexes
    where schemaname = 'public'
      and indexname = 'uq_account_deletion_requests_user'
  ) then
    raise exception 'account deletion idempotency index is missing';
  end if;
  if exists (
    select 1
    from pg_attribute
    where attrelid = 'public.account_deletion_requests'::regclass
      and attname = 'user_id'
      and attnotnull
  ) then
    raise exception 'account deletion ledger user_id must allow Auth-delete anonymization';
  end if;
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.account_deletion_requests'::regclass
      and conname = 'account_deletion_requests_user_id_fkey'
      and confdeltype = 'n'
  ) then
    raise exception 'account deletion ledger must set user_id null on Auth delete';
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'account_deletion_requests'
      and policyname = 'users can read own account deletion requests'
  ) then
    raise exception 'owner read policy is missing';
  end if;
  select pol.qual into policy_using
  from pg_policies pol
  where pol.schemaname = 'public'
    and pol.tablename = 'account_deletion_requests'
    and pol.policyname = 'users can read own account deletion requests';
  if policy_using is null or policy_using ilike '%true%' then
    raise exception 'account deletion policy is broader than owner scope';
  end if;
  if has_table_privilege('anon', 'public.account_deletion_requests', 'SELECT') then
    raise exception 'anon must not read account deletion ledger';
  end if;
  if has_table_privilege('authenticated', 'public.account_deletion_requests', 'INSERT') then
    raise exception 'authenticated must not write account deletion ledger';
  end if;
end $$;
