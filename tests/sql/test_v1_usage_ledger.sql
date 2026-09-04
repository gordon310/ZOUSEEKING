-- V1 usage ledger schema assertions.
-- Run against a disposable Supabase/PostgreSQL database that has applied the
-- full canonical migration history (20260905000100 organizations included).
-- Fails with an exception when a required table, constraint, index, trigger,
-- grant or RLS posture is missing.

do $$
declare
  item record;
  matched integer;
  policy_count integer;
begin
  -- ---------------------------------------------------------------------
  -- Tables exist.
  -- ---------------------------------------------------------------------
  for item in select unnest(array[
    'public.usage_quotas', 'public.usage_events', 'public.usage_idempotency'
  ]) as relname loop
    if to_regclass(item.relname) is null then
      raise exception 'missing % table', item.relname;
    end if;
  end loop;

  -- ---------------------------------------------------------------------
  -- Row level security is enabled on all three tables.
  -- ---------------------------------------------------------------------
  for item in
    select c.relname
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname in ('usage_quotas', 'usage_events', 'usage_idempotency')
      and not c.relrowsecurity
  loop
    raise exception 'RLS disabled for %', item.relname;
  end loop;

  -- ---------------------------------------------------------------------
  -- No anon policy may exist on any usage table.
  -- ---------------------------------------------------------------------
  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('usage_quotas', 'usage_events', 'usage_idempotency')
      and 'anon' = any (roles)
  ) then
    raise exception 'anonymous policy exists on a usage table';
  end if;

  -- authenticated has read-only policy coverage: exactly the two SELECT
  -- policies below and no INSERT/UPDATE/DELETE policies anywhere.
  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('usage_quotas', 'usage_events', 'usage_idempotency')
      and 'authenticated' = any (roles)
      and cmd <> 'SELECT'
  ) then
    raise exception 'authenticated write policy exists on a usage table';
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'usage_quotas'
      and 'authenticated' = any (roles) and cmd = 'SELECT'
  ) then
    raise exception 'missing authenticated SELECT policy on usage_quotas';
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'usage_events'
      and 'authenticated' = any (roles) and cmd = 'SELECT'
  ) then
    raise exception 'missing authenticated SELECT policy on usage_events';
  end if;

  select count(*) into policy_count
  from pg_policies
  where schemaname = 'public' and tablename = 'usage_idempotency';
  if policy_count <> 0 then
    raise exception 'usage_idempotency must carry no RLS policies, found %', policy_count;
  end if;

  -- ---------------------------------------------------------------------
  -- Grants: anon zero privileges; authenticated SELECT-only on the two read
  -- tables and nothing on usage_idempotency; service_role full access.
  -- ---------------------------------------------------------------------
  for item in select unnest(array['usage_quotas', 'usage_events', 'usage_idempotency']) as relname loop
    if has_table_privilege('anon', 'public.' || item.relname, 'select')
       or has_table_privilege('anon', 'public.' || item.relname, 'insert')
       or has_table_privilege('anon', 'public.' || item.relname, 'update')
       or has_table_privilege('anon', 'public.' || item.relname, 'delete') then
      raise exception 'anon holds privileges on %', item.relname;
    end if;
  end loop;

  for item in select unnest(array['usage_quotas', 'usage_events']) as relname loop
    if not has_table_privilege('authenticated', 'public.' || item.relname, 'select') then
      raise exception 'authenticated lacks SELECT on %', item.relname;
    end if;
    if has_table_privilege('authenticated', 'public.' || item.relname, 'insert')
       or has_table_privilege('authenticated', 'public.' || item.relname, 'update')
       or has_table_privilege('authenticated', 'public.' || item.relname, 'delete') then
      raise exception 'authenticated holds write privileges on %', item.relname;
    end if;
  end loop;

  if has_table_privilege('authenticated', 'public.usage_idempotency', 'select')
     or has_table_privilege('authenticated', 'public.usage_idempotency', 'insert') then
    raise exception 'authenticated holds privileges on usage_idempotency';
  end if;

  for item in select unnest(array['usage_quotas', 'usage_events', 'usage_idempotency']) as relname loop
    if not has_table_privilege('service_role', 'public.' || item.relname, 'select')
       or not has_table_privilege('service_role', 'public.' || item.relname, 'insert')
       or not has_table_privilege('service_role', 'public.' || item.relname, 'update')
       or not has_table_privilege('service_role', 'public.' || item.relname, 'delete') then
      raise exception 'service_role lacks full privileges on %', item.relname;
    end if;
  end loop;

  -- ---------------------------------------------------------------------
  -- Named CHECK/UNIQUE constraints per table.
  -- ---------------------------------------------------------------------
  for item in select * from (values
    ('usage_quotas',      'usage_quotas_scope_key_format'),
    ('usage_quotas',      'usage_quotas_period_key_format'),
    ('usage_quotas',      'usage_quotas_usage_kind_allowed'),
    ('usage_quotas',      'usage_quotas_counts_nonnegative'),
    ('usage_quotas',      'usage_quotas_scope_kind_period_unique'),
    ('usage_quotas',      'usage_quotas_capacity_bound'),
    ('usage_events',      'usage_events_scope_key_format'),
    ('usage_events',      'usage_events_period_key_format'),
    ('usage_events',      'usage_events_usage_kind_allowed'),
    ('usage_events',      'usage_events_operation_allowed'),
    ('usage_events',      'usage_events_units_positive'),
    ('usage_events',      'usage_events_note_length'),
    ('usage_events',      'usage_events_reversal_target'),
    ('usage_events',      'usage_events_actor_user_id_fkey'),
    ('usage_events',      'usage_events_reversal_of_fkey'),
    ('usage_idempotency', 'usage_idempotency_scope_key_format'),
    ('usage_idempotency', 'usage_idempotency_usage_kind_allowed'),
    ('usage_idempotency', 'usage_idempotency_operation_allowed'),
    ('usage_idempotency', 'usage_idempotency_fingerprint_unique'),
    ('usage_idempotency', 'usage_idempotency_client_key_unique')
  ) as v(tab, con) loop
    execute format(
      'select 1 from pg_constraint c join pg_class x on x.oid = c.conrelid '
      || 'where c.conname = %L and x.relname = %L',
      item.con, item.tab
    ) into matched;
    if matched is null then
      raise exception 'missing constraint %.%', item.tab, item.con;
    end if;
  end loop;

  -- ---------------------------------------------------------------------
  -- Indexes, including the partial fingerprint uniqueness index.
  -- ---------------------------------------------------------------------
  for item in select * from (values
    ('public', 'usage_quotas', 'idx_usage_quotas_scope_period'),
    ('public', 'usage_events', 'idx_usage_events_scope_period_created'),
    ('public', 'usage_events', 'uq_usage_events_fingerprint')
  ) as v(sch, tab, idx) loop
    if not exists (
      select 1 from pg_indexes
      where schemaname = item.sch and tablename = item.tab and indexname = item.idx
    ) then
      raise exception 'missing index % on %', item.idx, item.tab;
    end if;
  end loop;

  if not exists (
    select 1
    from pg_index i
    join pg_class c on c.oid = i.indexrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'uq_usage_events_fingerprint'
      and i.indpred is not null
  ) then
    raise exception 'uq_usage_events_fingerprint must be a partial index';
  end if;

  -- ---------------------------------------------------------------------
  -- Triggers: append-only guard on usage_events and updated_at touch on
  -- usage_quotas.
  -- ---------------------------------------------------------------------
  if not exists (
    select 1
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'usage_events'
      and t.tgname = 'enforce_usage_events_append_only'
      and not t.tgisinternal
  ) then
    raise exception 'missing append-only trigger on usage_events';
  end if;

  if not exists (
    select 1
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'usage_quotas'
      and t.tgname = 'set_usage_quotas_updated_at'
      and not t.tgisinternal
  ) then
    raise exception 'missing updated_at trigger on usage_quotas';
  end if;
end $$;
