-- Collection runs domain schema assertions
-- (migration 20260905000601_collection_runs).
-- Run against a disposable Supabase/PostgreSQL database only, AFTER the full
-- 20260905xxxx batch has been applied. Behavioural probes insert throwaway
-- rows into public.collection_runs inside savepoint blocks.
do $$
declare
  r text;
  t text;
  c record;
  v_msg text;
  v_id uuid;
  v_status text;
  v_rows integer;
  v_created timestamptz;
begin
  -- 0. Expected Supabase roles must exist before privilege assertions.
  if to_regrole('anon') is null
     or to_regrole('authenticated') is null
     or to_regrole('service_role') is null then
    raise exception 'expected Supabase roles anon/authenticated/service_role';
  end if;

  -- 1. Table exists.
  if to_regclass('public.collection_runs') is null then
    raise exception 'missing table: public.collection_runs';
  end if;

  -- 2. Row level security is enabled.
  if exists (
    select 1
    from pg_class pc
    join pg_namespace pn on pn.oid = pc.relnamespace
    where pn.nspname = 'public'
      and pc.relname = 'collection_runs'
      and not pc.relrowsecurity
  ) then
    raise exception 'row level security disabled on public.collection_runs';
  end if;

  -- 3. No RLS policies at all: internal domain, reached only through
  -- service_role table grants.
  if exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'collection_runs'
  ) then
    raise exception 'unexpected RLS policy on public.collection_runs';
  end if;

  -- 4. Privilege contract: anon/authenticated zero, service_role full.
  for r in select unnest(array['anon', 'authenticated']) loop
    if has_table_privilege(r, 'public.collection_runs', 'SELECT')
       or has_table_privilege(r, 'public.collection_runs', 'INSERT')
       or has_table_privilege(r, 'public.collection_runs', 'UPDATE')
       or has_table_privilege(r, 'public.collection_runs', 'DELETE') then
      raise exception 'role % must have zero privileges on public.collection_runs', r;
    end if;
  end loop;
  if not (
       has_table_privilege('service_role', 'public.collection_runs', 'SELECT')
   and has_table_privilege('service_role', 'public.collection_runs', 'INSERT')
   and has_table_privilege('service_role', 'public.collection_runs', 'UPDATE')
   and has_table_privilege('service_role', 'public.collection_runs', 'DELETE')) then
    raise exception 'service_role must have full privileges on public.collection_runs';
  end if;

  -- 5. All columns exist.
  for c in select * from (values
    ('collection_runs', 'id'),
    ('collection_runs', 'source_key'),
    ('collection_runs', 'source_type'),
    ('collection_runs', 'status'),
    ('collection_runs', 'rows_collected'),
    ('collection_runs', 'snapshot_hash'),
    ('collection_runs', 'error_message'),
    ('collection_runs', 'operator_user_id'),
    ('collection_runs', 'started_at'),
    ('collection_runs', 'completed_at'),
    ('collection_runs', 'created_at')
  ) as cols(tbl, col)
  loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = c.tbl
        and column_name = c.col
    ) then
      raise exception 'missing column public.%.%', c.tbl, c.col;
    end if;
  end loop;

  -- 6. Column type / length / nullability / default contract.
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'collection_runs'
      and column_name = 'id' and data_type = 'uuid'
      and is_nullable = 'NO' and column_default like 'gen_random_uuid()%'
  ) then
    raise exception 'collection_runs.id must be uuid pk default gen_random_uuid()';
  end if;
  for c in select * from (values
    ('source_key', 'text', 'NO', false),
    ('source_type', 'text', 'NO', false),
    ('rows_collected', 'integer', 'NO', true),
    ('created_at', 'timestamp with time zone', 'NO', true)
  ) as cols(col, dtype, nullable, has_default)
  loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'collection_runs'
        and column_name = c.col and data_type = c.dtype
        and is_nullable = c.nullable
        and ((c.has_default and column_default is not null)
             or (not c.has_default and column_default is null))
    ) then
      raise exception 'unexpected definition for collection_runs.%', c.col;
    end if;
  end loop;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'collection_runs'
      and column_name = 'status' and column_default = '''queued''::text'
  ) then
    raise exception 'collection_runs.status must default to queued';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'collection_runs'
      and column_name = 'rows_collected' and column_default = '0'
  ) then
    raise exception 'collection_runs.rows_collected must default to 0';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'collection_runs'
      and column_name = 'snapshot_hash' and data_type = 'character'
      and character_maximum_length = 64 and is_nullable = 'YES'
  ) then
    raise exception 'collection_runs.snapshot_hash must be char(64) nullable';
  end if;
  -- Nullable bookkeeping columns.
  for c in select * from (values
    ('error_message', 'text'),
    ('started_at', 'timestamp with time zone'),
    ('completed_at', 'timestamp with time zone')
  ) as cols(col, dtype)
  loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = 'collection_runs'
        and column_name = c.col and data_type = c.dtype and is_nullable = 'YES'
    ) then
      raise exception 'collection_runs.% must be nullable %', c.col, c.dtype;
    end if;
  end loop;

  -- 7. Named constraints exist.
  for c in select * from (values
    ('collection_runs', 'collection_runs_pkey'),
    ('collection_runs', 'collection_runs_source_type_allowed'),
    ('collection_runs', 'collection_runs_status_allowed'),
    ('collection_runs', 'collection_runs_rows_collected_nonnegative'),
    ('collection_runs', 'collection_runs_completed_requires_started')
  ) as cons(tbl, con)
  loop
    if not exists (
      select 1
      from pg_constraint pc
      join pg_class tc on tc.oid = pc.conrelid
      join pg_namespace pn on pn.oid = tc.relnamespace
      where pn.nspname = 'public' and tc.relname = c.tbl
        and pc.conname = c.con
    ) then
      raise exception 'missing constraint % on public.%', c.con, c.tbl;
    end if;
  end loop;

  -- 8. Foreign key targets auth.users with on delete set null.
  if not exists (
    select 1
    from pg_constraint pc
    join pg_class tc on tc.oid = pc.conrelid
    join pg_namespace pn on pn.oid = tc.relnamespace
    where pn.nspname = 'public' and tc.relname = 'collection_runs'
      and pc.conname = 'collection_runs_operator_user_id_fkey'
      and pc.contype = 'f' and pc.confdeltype = 'n'
      and pc.confrelid = to_regclass('auth.users')
  ) then
    raise exception 'missing or unexpected FK collection_runs_operator_user_id_fkey';
  end if;

  -- 9. Support indexes exist.
  for c in select * from (values
    ('collection_runs', 'idx_collection_runs_status_created'),
    ('collection_runs', 'idx_collection_runs_source_created')
  ) as idxs(tbl, idx)
  loop
    if not exists (
      select 1 from pg_indexes
      where schemaname = 'public' and tablename = c.tbl and indexname = c.idx
    ) then
      raise exception 'missing index % on public.%', c.idx, c.tbl;
    end if;
  end loop;

  -- 10. Behavioural probes: defaults, vocabulary checks and the
  --     completed-requires-started invariant (each inside a savepoint so a
  --     failed probe does not poison later assertions).
  begin
    insert into public.collection_runs (source_key, source_type)
    values ('probe/queue', 'authorized_csv')
    returning id, status, rows_collected, created_at
    into v_id, v_status, v_rows, v_created;
    if v_status is distinct from 'queued' then
      raise exception 'default status must be queued, got %', v_status;
    end if;
    if v_rows is distinct from 0 then
      raise exception 'default rows_collected must be 0';
    end if;
    if v_created is null then
      raise exception 'created_at must default to now()';
    end if;
    delete from public.collection_runs where id = v_id;
  end;

  begin
    insert into public.collection_runs (source_key, source_type)
    values ('probe/bad-type', 'scraped_aggregate');
    raise exception 'invalid source_type was not rejected';
  exception when check_violation then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'collection_runs_source_type_allowed' then raise; end if;
  end;

  begin
    insert into public.collection_runs (source_key, source_type, status)
    values ('probe/bad-status', 'official_open', 'done');
    raise exception 'invalid status was not rejected';
  exception when check_violation then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'collection_runs_status_allowed' then raise; end if;
  end;

  begin
    insert into public.collection_runs (source_key, source_type, rows_collected)
    values ('probe/neg-rows', 'partner', -1);
    raise exception 'negative rows_collected was not rejected';
  exception when check_violation then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'collection_runs_rows_collected_nonnegative' then raise; end if;
  end;

  begin
    insert into public.collection_runs
      (source_key, source_type, completed_at)
    values ('probe/complete-no-start', 'partner', now());
    raise exception 'completed_at without started_at was not rejected';
  exception when check_violation then
    get stacked diagnostics v_msg = message_text;
    if v_msg !~ 'collection_runs_completed_requires_started' then raise; end if;
  end;

  -- A completed run with both timestamps is legal, and every vocabulary
  -- value is insertable.
  for t in select unnest(array[
    'authorized_csv', 'official_open', 'partner',
    'user_submitted', 'aggregate_authorized'
  ]) loop
    insert into public.collection_runs (source_key, source_type)
    values ('probe/source-type', t);
  end loop;
  for t in select unnest(array[
    'queued', 'running', 'succeeded', 'failed', 'cancelled'
  ]) loop
    insert into public.collection_runs (source_key, source_type, status)
    values ('probe/status', 'official_open', t);
  end loop;
  insert into public.collection_runs
    (source_key, source_type, status, rows_collected, snapshot_hash,
     started_at, completed_at)
  values
    ('probe/full', 'authorized_csv', 'succeeded', 120,
     repeat('ab', 32), now() - interval '1 hour', now());

  -- 11. Cleanup: remove the throwaway probe rows.
  delete from public.collection_runs
  where source_key in
    ('probe/queue', 'probe/bad-type', 'probe/bad-status', 'probe/neg-rows',
     'probe/complete-no-start', 'probe/source-type', 'probe/status',
     'probe/full');

  raise notice 'test_collection_runs: all assertions passed';
end $$;
