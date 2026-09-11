-- Compile the member usage query against the real PostgreSQL schema.
-- This catches missing SELECT columns that fake rows can accidentally hide.

do $$
begin
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'usage_quotas'
      and column_name in ('usage_kind', 'period_key', 'consumed_units', 'limit_units')
    group by table_schema, table_name
    having count(*) = 4
  ) then
    raise exception 'public.usage_quotas is missing a member snapshot column';
  end if;
end $$;

prepare member_usage_quotas (text, text[]) as
select usage_kind, period_key, consumed_units, limit_units
from public.usage_quotas
where scope_key = $1 and period_key = any($2::text[]);

deallocate member_usage_quotas;
