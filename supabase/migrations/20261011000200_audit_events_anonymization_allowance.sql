-- Auth deletion follows audit_events.actor_user_id ON DELETE SET NULL.
-- Permit only that FK-triggered de-identification, retaining every event fact.
-- Direct updates, DELETE and TRUNCATE remain forbidden.
create or replace function public.audit_events_append_only()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if tg_op = 'UPDATE' then
    if old.actor_user_id is not null
       and new.actor_user_id is null
       and pg_trigger_depth() > 1
       and not exists (select 1 from auth.users where id = old.actor_user_id)
       and (to_jsonb(new) - 'actor_user_id') = (to_jsonb(old) - 'actor_user_id') then
      return new;
    end if;
  end if;
  raise exception 'audit_events is append-only: % is forbidden', tg_op;
end;
$$;

revoke all on function public.audit_events_append_only() from public, anon, authenticated;
