-- Shared, fail-closed rate-limit storage for every abuse-sensitive API instance.
begin;

create table public.shared_rate_limits (
  subject_hash char(64) not null check (subject_hash ~ '^[0-9a-f]{64}$'),
  action text not null check (length(btrim(action)) between 1 and 80),
  window_started_at timestamptz not null,
  request_count integer not null default 1 check (request_count > 0),
  expires_at timestamptz not null,
  primary key (subject_hash, action, window_started_at)
);
create index shared_rate_limits_expiry on public.shared_rate_limits(expires_at);
alter table public.shared_rate_limits enable row level security;
revoke all on public.shared_rate_limits from anon, authenticated;
grant all privileges on public.shared_rate_limits to service_role;

do $$
begin
  if to_regclass('public.shared_rate_limits') is null then
    raise exception 'shared rate-limit table was not created';
  end if;
  if not exists (select 1 from pg_class where oid='public.shared_rate_limits'::regclass and relrowsecurity) then
    raise exception 'shared rate-limit RLS was not enabled';
  end if;
  if exists (select 1 from information_schema.role_table_grants where table_schema='public' and table_name='shared_rate_limits' and grantee in ('anon','authenticated')) then
    raise exception 'shared rate-limit table must remain server-only';
  end if;
end $$;

commit;
