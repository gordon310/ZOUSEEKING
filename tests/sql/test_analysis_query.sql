-- Compile the owner and provenance predicates used by the analysis store.
-- This is intentionally executable against PostgreSQL, not only a fake store.

prepare analysis_owned (uuid, text[]) as
select q.year, q.month, q.prefecture, q.city, q.ward, q.asset_type,
       pr.title, pr.data_class::text as data_class, pr.rental, pr.sale, pr.data_sources
from public.queries q
join public.property_reports pr on pr.query_id = q.id
where (q.owner_user_id = $1 or pr.owner_user_id = $1)
  and q.status = 'completed'
  and coalesce(pr.data_class::text, '') = any($2::text[]);

deallocate analysis_owned;
