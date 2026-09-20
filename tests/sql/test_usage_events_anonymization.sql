-- Run against a disposable PostgreSQL/Supabase database after the complete
-- forward migration history. Proves the account-deletion FK anonymization is
-- the only permitted UPDATE to the append-only usage ledger.

begin;

insert into auth.users (id, email)
values ('00000000-0000-0000-0000-000000009201', 'usage-delete@example.invalid')
on conflict (id) do update set email = excluded.email;

insert into auth.users (id, email)
values ('00000000-0000-0000-0000-000000009203', 'usage-fk-delete@example.invalid')
on conflict (id) do update set email = excluded.email;

insert into public.usage_events (
  id, scope_key, usage_kind, operation, units, period_key, idempotency_key,
  fingerprint, reservation_key, actor_user_id, note, created_at
) values (
  '00000000-0000-0000-0000-000000009202',
  'user:00000000-0000-0000-0000-000000009201',
  'query', 'consume', 1, '2026-09', 'delete-fixture-key',
  'delete-fixture-fingerprint', 'delete-fixture-reservation',
  '00000000-0000-0000-0000-000000009201', 'retain every event fact',
  '2026-09-20T00:00:00Z'
) on conflict (id) do nothing;

-- The FK-compatible anonymous update is permitted and every other column is
-- preserved by the trigger predicate.
update public.usage_events
set actor_user_id = null
where id = '00000000-0000-0000-0000-000000009202';

do $$
declare
  event_row public.usage_events%rowtype;
begin
  select * into event_row
  from public.usage_events
  where id = '00000000-0000-0000-0000-000000009202';
  if event_row.actor_user_id is not null
     or event_row.units <> 1
     or event_row.created_at <> '2026-09-20T00:00:00Z'::timestamptz
     or event_row.fingerprint <> 'delete-fixture-fingerprint' then
    raise exception 'anonymization changed a retained usage event fact';
  end if;

  begin
    update public.usage_events set units = 2 where id = event_row.id;
    raise exception 'quantity mutation was accepted';
  exception when raise_exception then
    if sqlerrm <> 'usage_events is append-only; update is forbidden' then raise; end if;
  end;

  begin
    update public.usage_events
    set created_at = created_at + interval '1 second'
    where id = event_row.id;
    raise exception 'created_at mutation was accepted';
  exception when raise_exception then
    if sqlerrm <> 'usage_events is append-only; update is forbidden' then raise; end if;
  end;

  begin
    delete from public.usage_events where id = event_row.id;
    raise exception 'delete was accepted';
  exception when raise_exception then
    if sqlerrm <> 'usage_events is append-only; delete is forbidden' then raise; end if;
  end;
end $$;

-- GoTrue's Auth DELETE uses the FK action, which must reach the same narrow
-- allowance without deleting the ledger row.
insert into public.usage_events (
  id, scope_key, usage_kind, operation, units, period_key, actor_user_id,
  created_at
) values (
  '00000000-0000-0000-0000-000000009204',
  'user:00000000-0000-0000-0000-000000009203',
  'report', 'consume', 1, '2026-09',
  '00000000-0000-0000-0000-000000009203', '2026-09-20T00:00:01Z'
);

delete from auth.users where id = '00000000-0000-0000-0000-000000009203';

do $$
declare retained_count integer;
begin
  select count(*) into retained_count
  from public.usage_events
  where id = '00000000-0000-0000-0000-000000009204'
    and actor_user_id is null
    and units = 1
    and created_at = '2026-09-20T00:00:01Z'::timestamptz;
  if retained_count <> 1 then
    raise exception 'Auth DELETE did not retain and anonymize its usage event (%)', retained_count;
  end if;
end $$;

rollback;
