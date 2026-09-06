-- Collection sources registry schema assertions
-- (migration 20260906000100_collection_sources).
-- Run against a disposable Supabase/PostgreSQL database only, AFTER the full
-- 20260906xxxx batch has been applied. Behavioural probes insert throwaway
-- rows inside a rolled-back sub-transaction.

begin;

-- 0. Expected Supabase roles must exist before privilege assertions.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    raise exception 'missing role: anon';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    raise exception 'missing role: authenticated';
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    raise exception 'missing role: service_role';
  end if;
end $$;

-- 1. Table, RLS and key columns exist.
select count(*) from pg_tables
  where schemaname = 'public' and tablename = 'collection_sources';
select count(*) from pg_policies
  where schemaname = 'public' and tablename = 'collection_sources';

do $$
declare
  rls_on boolean;
  has_cadence boolean;
  has_rights boolean;
begin
  select relrowsecurity into rls_on
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'collection_sources';
  if rls_on is not true then
    raise exception 'collection_sources RLS must be enabled';
  end if;
  select exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'collection_sources'
      and column_name = 'cadence'
  ) into has_cadence;
  select exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'collection_sources'
      and column_name = 'rights_confirmed'
  ) into has_rights;
  if not has_cadence or not has_rights then
    raise exception 'collection_sources missing cadence/rights_confirmed column';
  end if;
end $$;

-- 2. anon/authenticated hold no table privileges (internal domain).
do $$
declare
  anon_grants int;
  auth_grants int;
begin
  select count(*) into anon_grants from information_schema.role_table_grants
    where table_schema = 'public' and table_name = 'collection_sources'
      and grantee = 'anon';
  select count(*) into auth_grants from information_schema.role_table_grants
    where table_schema = 'public' and table_name = 'collection_sources'
      and grantee = 'authenticated';
  if anon_grants <> 0 or auth_grants <> 0 then
    raise exception 'collection_sources must be zero-privilege for anon/authenticated';
  end if;
end $$;

-- 3. Vocabulary CHECKs reject bad source_type / cadence (probe in savepoint).
do $$
begin
  begin
    insert into public.collection_sources (source_key, source_type, cadence)
      values ('probe/bad-type', 'not_a_type', 'weekly');
    raise exception 'bad source_type must be rejected';
  exception when check_violation then
    null;
  end;

  begin
    insert into public.collection_sources (source_key, source_type, cadence)
      values ('probe/bad-cadence', 'aggregate_authorized', 'hourly');
    raise exception 'bad cadence must be rejected';
  exception when check_violation then
    null;
  end;
end $$;

-- 4. Happy-path upsert + updated_at trigger behaviour (rolled back).
-- created_at is set in the past so the same-transaction now() on UPDATE
-- still advances updated_at beyond it (now() is transaction-stable).
insert into public.collection_sources (
  source_key, source_type, display_name, source_url,
  cadence, rights_confirmed, robots_policy, rate_limit_note,
  retention_policy, enabled, notes, created_at
) values (
  'probe/jphouse_23ku_shibuya', 'aggregate_authorized', 'probe source',
  'https://example.test/source', 'weekly', true, 'allow', '10/min',
  '12 months', true, 'probe', now() - interval '1 minute'
);

update public.collection_sources
  set rights_confirmed = false
  where source_key = 'probe/jphouse_23ku_shibuya';

do $$
declare
  updated timestamptz;
  created timestamptz;
begin
  select created_at, updated_at into created, updated
    from public.collection_sources
    where source_key = 'probe/jphouse_23ku_shibuya';
  if updated <= created then
    raise exception 'updated_at must advance on update (trigger missing?)';
  end if;
end $$;

-- 5. source_url/notes constraint: one of them must be present.
do $$
begin
  begin
    insert into public.collection_sources (source_key, source_type, cadence)
      values ('probe/no-url-no-note', 'aggregate_authorized', 'weekly');
    raise exception 'missing source_url and notes must be rejected';
  exception when check_violation then
    null;
  end;
end $$;

rollback;
