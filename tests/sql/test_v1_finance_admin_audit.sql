-- V1 finance / back-office roles / audit schema assertions
-- (migration 20260905000500_v1_finance_admin_audit).
-- Run against a disposable Supabase/PostgreSQL database only, AFTER the full
-- 20260905xxxx batch has been applied. The append-only behaviour probe
-- inserts one throwaway row into public.audit_events.
do $$
declare
  r text;
  t text;
  c record;
  v_msg text;
begin
  -- 0. Expected Supabase roles must exist before privilege assertions.
  if to_regrole('anon') is null
     or to_regrole('authenticated') is null
     or to_regrole('service_role') is null then
    raise exception 'expected Supabase roles anon/authenticated/service_role';
  end if;

  -- 1. Tables exist.
  foreach t in array array[
    'payment_orders', 'refunds', 'payment_events',
    'internal_role_assignments', 'audit_events'
  ] loop
    if to_regclass(format('public.%s', t)) is null then
      raise exception 'missing table: public.%', t;
    end if;
  end loop;

  -- 2. Row level security is enabled on every table.
  if exists (
    select 1
    from pg_class pc
    join pg_namespace pn on pn.oid = pc.relnamespace
    where pn.nspname = 'public'
      and pc.relname in (
        'payment_orders', 'refunds', 'payment_events',
        'internal_role_assignments', 'audit_events'
      )
      and not pc.relrowsecurity
  ) then
    raise exception 'row level security disabled on one or more V1 tables';
  end if;

  -- 3. No RLS policies at all: this internal domain is reached exclusively
  -- through service_role table grants, never through anon/authenticated
  -- policies.
  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename in (
        'payment_orders', 'refunds', 'payment_events',
        'internal_role_assignments', 'audit_events'
      )
  ) then
    raise exception 'unexpected RLS policy on V1 finance/admin table';
  end if;

  -- 4. Privilege contract: anon/authenticated zero, service_role full.
  for r in select unnest(array['anon', 'authenticated']) loop
    for t in select unnest(array[
      'payment_orders', 'refunds', 'payment_events',
      'internal_role_assignments', 'audit_events'
    ]) loop
      if has_table_privilege(r, format('public.%s', t), 'SELECT')
         or has_table_privilege(r, format('public.%s', t), 'INSERT')
         or has_table_privilege(r, format('public.%s', t), 'UPDATE')
         or has_table_privilege(r, format('public.%s', t), 'DELETE') then
        raise exception 'role % must have zero privileges on public.%', r, t;
      end if;
    end loop;
  end loop;
  for t in select unnest(array[
    'payment_orders', 'refunds', 'payment_events',
    'internal_role_assignments', 'audit_events'
  ]) loop
    if not (
         has_table_privilege('service_role', format('public.%s', t), 'SELECT')
     and has_table_privilege('service_role', format('public.%s', t), 'INSERT')
     and has_table_privilege('service_role', format('public.%s', t), 'UPDATE')
     and has_table_privilege('service_role', format('public.%s', t), 'DELETE')) then
      raise exception 'service_role must have full privileges on public.%', t;
    end if;
  end loop;

  -- 5. Key columns exist.
  for c in select *
    from (values
      ('payment_orders', 'order_no'),
      ('payment_orders', 'owner_user_id'),
      ('payment_orders', 'organization_id'),
      ('payment_orders', 'product_code'),
      ('payment_orders', 'price_version'),
      ('payment_orders', 'currency'),
      ('payment_orders', 'amount_minor'),
      ('payment_orders', 'status'),
      ('payment_orders', 'provider'),
      ('payment_orders', 'provider_session_id'),
      ('payment_orders', 'provider_payment_intent_id'),
      ('payment_orders', 'paid_at'),
      ('payment_orders', 'created_at'),
      ('payment_orders', 'updated_at'),
      ('refunds', 'order_id'),
      ('refunds', 'amount_minor'),
      ('refunds', 'currency'),
      ('refunds', 'reason'),
      ('refunds', 'status'),
      ('refunds', 'provider_refund_id'),
      ('refunds', 'created_at'),
      ('refunds', 'updated_at'),
      ('payment_events', 'provider'),
      ('payment_events', 'provider_event_id'),
      ('payment_events', 'event_type'),
      ('payment_events', 'status'),
      ('payment_events', 'payload_sha256'),
      ('payment_events', 'processed_at'),
      ('payment_events', 'created_at'),
      ('internal_role_assignments', 'user_id'),
      ('internal_role_assignments', 'role'),
      ('internal_role_assignments', 'granted_by_user_id'),
      ('internal_role_assignments', 'granted_at'),
      ('internal_role_assignments', 'expires_at'),
      ('internal_role_assignments', 'note'),
      ('audit_events', 'actor_user_id'),
      ('audit_events', 'action'),
      ('audit_events', 'target_type'),
      ('audit_events', 'target_id'),
      ('audit_events', 'summary'),
      ('audit_events', 'occurred_at')
    ) as cols(tbl, col)
  loop
    if not exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = c.tbl
        and column_name = c.col
    ) then
      raise exception 'missing column public.%.%', c.tbl, c.col;
    end if;
  end loop;

  -- 6. Column type/length/nullability contract.
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'payment_orders'
      and column_name = 'currency' and data_type = 'character varying'
      and character_maximum_length = 3 and is_nullable = 'NO'
  ) then
    raise exception 'payment_orders.currency must be varchar(3) not null';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'refunds'
      and column_name = 'currency' and data_type = 'character varying'
      and character_maximum_length = 3 and is_nullable = 'NO'
  ) then
    raise exception 'refunds.currency must be varchar(3) not null';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'payment_events'
      and column_name = 'payload_sha256' and data_type = 'character'
      and character_maximum_length = 64 and is_nullable = 'NO'
  ) then
    raise exception 'payment_events.payload_sha256 must be char(64) not null';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'audit_events'
      and column_name = 'summary' and data_type = 'jsonb'
      and is_nullable = 'NO' and column_default is not null
  ) then
    raise exception 'audit_events.summary must be jsonb not null default {}';
  end if;
  -- Not-null core identifiers.
  for c in select *
    from (values
      ('payment_orders', 'order_no'),
      ('payment_orders', 'product_code'),
      ('payment_orders', 'price_version'),
      ('payment_orders', 'amount_minor'),
      ('payment_orders', 'status'),
      ('payment_orders', 'provider'),
      ('refunds', 'order_id'),
      ('refunds', 'amount_minor'),
      ('refunds', 'reason'),
      ('refunds', 'status'),
      ('payment_events', 'provider'),
      ('payment_events', 'provider_event_id'),
      ('payment_events', 'event_type'),
      ('internal_role_assignments', 'user_id'),
      ('internal_role_assignments', 'role'),
      ('audit_events', 'action'),
      ('audit_events', 'target_type')
    ) as cols(tbl, col)
  loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public' and table_name = c.tbl
        and column_name = c.col and is_nullable = 'NO'
    ) then
      raise exception 'column public.%.% must be not null', c.tbl, c.col;
    end if;
  end loop;

  -- 7. Named constraints exist.
  for c in select *
    from (values
      ('payment_orders', 'payment_orders_order_no_unique'),
      ('payment_orders', 'payment_orders_single_scope'),
      ('payment_orders', 'payment_orders_currency_allowed'),
      ('payment_orders', 'payment_orders_amount_positive'),
      ('payment_orders', 'payment_orders_status_allowed'),
      ('payment_orders', 'payment_orders_provider_allowed'),
      ('payment_orders', 'payment_orders_paid_at_status_allowed'),
      ('refunds', 'refunds_currency_allowed'),
      ('refunds', 'refunds_amount_positive'),
      ('refunds', 'refunds_reason_allowed'),
      ('refunds', 'refunds_status_allowed'),
      ('refunds', 'refunds_provider_refund_id_unique'),
      ('payment_events', 'payment_events_provider_event_id_unique'),
      ('payment_events', 'payment_events_status_allowed'),
      ('internal_role_assignments', 'internal_role_assignments_user_role_unique'),
      ('internal_role_assignments', 'internal_role_assignments_role_allowed'),
      ('internal_role_assignments', 'internal_role_assignments_expiry_after_grant')
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

  -- 8. Foreign keys point at the right relations with the right delete rule.
  --    confdeltype: n = set null, c = cascade, r = restrict.
  for c in select *
    from (values
      ('payment_orders', 'payment_orders_owner_user_id_fkey', 'auth.users', 'n'),
      ('payment_orders', 'payment_orders_organization_id_fkey', 'public.organizations', 'n'),
      ('refunds', 'refunds_order_id_fkey', 'public.payment_orders', 'r'),
      ('internal_role_assignments', 'internal_role_assignments_user_id_fkey', 'auth.users', 'c'),
      ('internal_role_assignments', 'internal_role_assignments_granted_by_user_id_fkey', 'auth.users', 'n'),
      ('audit_events', 'audit_events_actor_user_id_fkey', 'auth.users', 'n')
    ) as fks(tbl, con, ref, del)
  loop
    if not exists (
      select 1
      from pg_constraint pc
      join pg_class tc on tc.oid = pc.conrelid
      join pg_namespace pn on pn.oid = tc.relnamespace
      where pn.nspname = 'public' and tc.relname = c.tbl
        and pc.conname = c.con and pc.contype = 'f'
        and pc.confdeltype = c.del
        and pc.confrelid = to_regclass(c.ref)
    ) then
      raise exception 'missing or unexpected FK % on public.%', c.con, c.tbl;
    end if;
  end loop;

  -- 9. Support indexes exist.
  for c in select *
    from (values
      ('payment_orders', 'payment_orders_order_no_unique'),
      ('refunds', 'refunds_provider_refund_id_unique'),
      ('refunds', 'idx_refunds_order_id'),
      ('payment_events', 'payment_events_provider_event_id_unique'),
      ('internal_role_assignments', 'internal_role_assignments_user_role_unique'),
      ('audit_events', 'idx_audit_events_occurred_at'),
      ('audit_events', 'idx_audit_events_actor_user_id')
    ) as idxs(tbl, idx)
  loop
    if not exists (
      select 1 from pg_indexes
      where schemaname = 'public' and tablename = c.tbl and indexname = c.idx
    ) then
      raise exception 'missing index % on public.%', c.idx, c.tbl;
    end if;
  end loop;

  -- 10. Triggers: append-only guards on audit_events, updated_at maintenance
  --     on mutable finance tables.
  for c in select *
    from (values
      ('audit_events', 'audit_events_no_update'),
      ('audit_events', 'audit_events_no_delete'),
      ('audit_events', 'audit_events_no_truncate'),
      ('payment_orders', 'set_payment_orders_updated_at'),
      ('refunds', 'set_refunds_updated_at')
    ) as trgs(tbl, trg)
  loop
    if not exists (
      select 1
      from pg_trigger pt
      join pg_class tc on tc.oid = pt.tgrelid
      join pg_namespace pn on pn.oid = tc.relnamespace
      where pn.nspname = 'public' and tc.relname = c.tbl
        and pt.tgname = c.trg and not pt.tgisinternal
    ) then
      raise exception 'missing trigger % on public.%', c.trg, c.tbl;
    end if;
  end loop;

  -- 11. Behavioural probe: audit_events must reject UPDATE, DELETE, TRUNCATE.
  declare
    v_audit_id uuid;
  begin
    insert into public.audit_events (action, target_type, target_id)
    values ('test.append_only', 'schema_test', 'audit_events')
    returning id into v_audit_id;

    begin
      update public.audit_events
      set summary = jsonb_build_object('tampered', true)
      where id = v_audit_id;
      raise exception 'audit_events UPDATE was not rejected';
    exception when others then
      get stacked diagnostics v_msg = message_text;
      if v_msg !~ 'append-only' then raise; end if;
    end;

    begin
      delete from public.audit_events where id = v_audit_id;
      raise exception 'audit_events DELETE was not rejected';
    exception when others then
      get stacked diagnostics v_msg = message_text;
      if v_msg !~ 'append-only' then raise; end if;
    end;

    begin
      truncate table public.audit_events;
      raise exception 'audit_events TRUNCATE was not rejected';
    exception when others then
      get stacked diagnostics v_msg = message_text;
      if v_msg !~ 'append-only' then raise; end if;
    end;
  end;

  raise notice 'test_v1_finance_admin_audit: all assertions passed';
end $$;
