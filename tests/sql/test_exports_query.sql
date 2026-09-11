-- Compile the production export predicates against the real PostgreSQL schema.
-- This catches enum/text coercion errors that fake-store API tests cannot see.

do $$
begin
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'property_reports'
      and column_name = 'data_class'
      and udt_schema = 'public'
      and udt_name = 'data_class'
  ) then
    raise exception 'public.property_reports.data_class must use public.data_class enum';
  end if;
end $$;

prepare exports_selected (uuid, uuid[]) as
select q.id, q.query_key, q.prefecture, q.city, q.ward, q.asset_type,
       q.year, q.month, q.status as query_status, pr.title,
       pr.publish_month, pr.summary
from public.queries q
join public.property_reports pr on pr.query_id = q.id
where q.owner_user_id = $1 and q.id = any($2::uuid[])
  and coalesce(pr.data_class::text, '') <> 'synthetic_fixture';

deallocate exports_selected;

prepare exports_limited (uuid, integer) as
select q.id, q.query_key, q.prefecture, q.city, q.ward, q.asset_type,
       q.year, q.month, q.status as query_status, pr.title,
       pr.publish_month, pr.summary
from public.queries q
join public.property_reports pr on pr.query_id = q.id
where q.owner_user_id = $1
  and coalesce(pr.data_class::text, '') <> 'synthetic_fixture'
order by q.created_at desc
limit $2;

deallocate exports_limited;
