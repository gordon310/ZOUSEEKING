-- Run after canonical migrations in a disposable PostgreSQL/Supabase DB.
do $$
declare
  nullable boolean;
begin
  select not attnotnull into nullable
  from pg_attribute
  where attrelid = 'public.account_deletion_requests'::regclass
    and attname = 'backup_expired_at'
    and not attisdropped;
  if nullable is distinct from true then
    raise exception 'backup_expired_at must be an additive nullable column';
  end if;
  if not exists (
    select 1 from supabase_migrations.schema_migrations
    where version = '20260915000400'
  ) then
    raise exception 'retention sweeper migration ledger entry is missing';
  end if;
  if not exists (
    select 1 from pg_indexes
    where schemaname = 'public'
      and indexname = 'idx_account_deletion_requests_backup_expiry_due'
  ) then
    raise exception 'backup expiry due index is missing';
  end if;
  if has_table_privilege('anon', 'public.account_deletion_requests', 'UPDATE')
     or has_table_privilege('authenticated', 'public.account_deletion_requests', 'UPDATE') then
    raise exception 'retention ledger update must remain service-only';
  end if;
  if to_regclass('public.usage_events') is null then
    raise exception 'usage_events append-only table is missing';
  end if;
end $$;
