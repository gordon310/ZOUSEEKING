-- Static contract exercised by the migration review runner.
-- The forward migration must contain only additive DDL.
do $$
declare
  migration text := pg_read_file('supabase/migrations/20260914000200_realtime_authenticated_quota.sql');
begin
  if migration ~* 'drop\s+(constraint|column|policy|trigger|function)' then
    raise exception 'quota migration contains destructive DDL';
  end if;
  if migration ~* 'create\s+or\s+replace' then
    raise exception 'quota migration replaces an existing object';
  end if;
  if migration !~* 'create\s+index' then
    raise exception 'quota migration does not add an index';
  end if;
end $$;

