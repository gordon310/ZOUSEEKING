-- Static contract exercised by the migration review runner.
-- The forward migration must contain only additive DDL.
create temporary table migration_source (line text);
\copy migration_source(line) from 'supabase/migrations/20260914000200_realtime_authenticated_quota.sql'

do $$
declare
  migration text;
begin
  select string_agg(line, E'\n' order by ordinal) into migration
  from (
    select line, row_number() over () as ordinal
    from migration_source
  ) source;
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
