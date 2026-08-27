create extension if not exists pg_trgm;

create index if not exists idx_queries_location
on public.queries(prefecture, city, ward, asset_type, year, month);

create index if not exists idx_queries_lookup
on public.queries(query_key, status);

create index if not exists idx_queries_status
on public.queries(status);

create index if not exists idx_queries_created_at
on public.queries(created_at desc);

create index if not exists idx_queries_requested_email
on public.queries(requested_by_email);

create index if not exists idx_jobs_query_status
on public.generation_jobs(query_id, status);

create index if not exists idx_jobs_created_at
on public.generation_jobs(created_at desc);

create index if not exists idx_reports_query_key
on public.property_reports(query_key);

create index if not exists idx_reports_slug
on public.property_reports(slug);

create index if not exists idx_reports_publish_month
on public.property_reports(publish_month);

create index if not exists idx_reports_created_at
on public.property_reports(created_at desc);

create index if not exists idx_reports_title
on public.property_reports using gin(to_tsvector('simple', title || ' ' || markdown));

create index if not exists idx_reports_title_trgm
on public.property_reports using gin(title gin_trgm_ops);

create index if not exists idx_reports_markdown_trgm
on public.property_reports using gin(markdown gin_trgm_ops);

create index if not exists idx_reports_raw_record_gin
on public.property_reports using gin(raw_record);

create index if not exists idx_reports_summary_gin
on public.property_reports using gin(summary);

create index if not exists idx_sources_query_status
on public.data_sources(query_id, status);

create index if not exists idx_sources_created_at
on public.data_sources(created_at desc);
