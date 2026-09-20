-- Account deletion removes the Auth identity. PostgreSQL then follows the
-- usage_events.actor_user_id FK's ON DELETE SET NULL action. Keep that
-- de-identification update as the sole exception to the append-only ledger:
-- it may null the actor and may not alter amounts, timestamps, fingerprints,
-- or any other event fact.

create or replace function public.prevent_usage_event_mutation()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'usage_events is append-only; delete is forbidden';
  end if;

  if new.actor_user_id is null
     and old.id is not distinct from new.id
     and old.scope_key is not distinct from new.scope_key
     and old.usage_kind is not distinct from new.usage_kind
     and old.operation is not distinct from new.operation
     and old.units is not distinct from new.units
     and old.period_key is not distinct from new.period_key
     and old.idempotency_key is not distinct from new.idempotency_key
     and old.fingerprint is not distinct from new.fingerprint
     and old.reservation_key is not distinct from new.reservation_key
     and old.reversal_of is not distinct from new.reversal_of
     and old.note is not distinct from new.note
     and old.created_at is not distinct from new.created_at then
    return new;
  end if;

  raise exception 'usage_events is append-only; update is forbidden';
end;
$$;

revoke all on function public.prevent_usage_event_mutation() from public, anon, authenticated;
