create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

create table if not exists public.queries (
  id uuid primary key default gen_random_uuid(),
  query_key text not null unique,
  prefecture text not null,
  city text not null,
  ward text not null default '',
  asset_type text not null,
  year int not null,
  month int not null check (month between 1 and 12),
  status text not null default 'pending',
  markdown_title text not null default '',
  xhs_draft text not null default '',
  requested_by_name text not null default '',
  requested_by_email text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.generation_jobs (
  id uuid primary key default gen_random_uuid(),
  query_id uuid not null references public.queries(id) on delete cascade,
  status text not null default 'pending',
  progress int not null default 0 check (progress between 0 and 100),
  current_step text not null default '等待开始',
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.property_reports (
  id uuid primary key default gen_random_uuid(),
  query_id uuid references public.queries(id) on delete set null,
  query_key text not null unique,
  slug text not null unique,
  title text not null,
  publish_month text not null,
  markdown text not null default '',
  xhs_content text not null default '',
  rental jsonb not null default '[]'::jsonb,
  sale jsonb not null default '[]'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  images jsonb not null default '[]'::jsonb,
  data_sources jsonb not null default '[]'::jsonb,
  raw_record jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.data_sources (
  id uuid primary key default gen_random_uuid(),
  query_id uuid references public.queries(id) on delete cascade,
  source_name text not null,
  source_url text not null,
  source_role text not null,
  status text not null default 'pending',
  error_message text,
  fetched_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_queries_location on public.queries(prefecture, city, ward, asset_type, year, month);
create index if not exists idx_queries_lookup on public.queries(query_key, status);
create index if not exists idx_queries_status on public.queries(status);
create index if not exists idx_queries_created_at on public.queries(created_at desc);
create index if not exists idx_queries_requested_email on public.queries(requested_by_email);
create index if not exists idx_jobs_query_status on public.generation_jobs(query_id, status);
create index if not exists idx_jobs_created_at on public.generation_jobs(created_at desc);
create index if not exists idx_reports_query_key on public.property_reports(query_key);
create index if not exists idx_reports_slug on public.property_reports(slug);
create index if not exists idx_reports_publish_month on public.property_reports(publish_month);
create index if not exists idx_reports_created_at on public.property_reports(created_at desc);
create index if not exists idx_reports_title on public.property_reports using gin(to_tsvector('simple', title || ' ' || markdown));
create index if not exists idx_reports_title_trgm on public.property_reports using gin(title gin_trgm_ops);
create index if not exists idx_reports_markdown_trgm on public.property_reports using gin(markdown gin_trgm_ops);
create index if not exists idx_reports_raw_record_gin on public.property_reports using gin(raw_record);
create index if not exists idx_reports_summary_gin on public.property_reports using gin(summary);
create index if not exists idx_sources_query_status on public.data_sources(query_id, status);
create index if not exists idx_sources_created_at on public.data_sources(created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_queries_updated_at on public.queries;
create trigger set_queries_updated_at
before update on public.queries
for each row execute function public.set_updated_at();

drop trigger if exists set_jobs_updated_at on public.generation_jobs;
create trigger set_jobs_updated_at
before update on public.generation_jobs
for each row execute function public.set_updated_at();

drop trigger if exists set_reports_updated_at on public.property_reports;
create trigger set_reports_updated_at
before update on public.property_reports
for each row execute function public.set_updated_at();

alter table public.queries enable row level security;
alter table public.generation_jobs enable row level security;
alter table public.property_reports enable row level security;
alter table public.data_sources enable row level security;

drop policy if exists "public can read queries" on public.queries;
create policy "public can read queries"
on public.queries for select
to anon
using (true);

drop policy if exists "public can insert queries" on public.queries;
create policy "public can insert queries"
on public.queries for insert
to anon
with check (true);

drop policy if exists "public can update queries" on public.queries;
create policy "public can update queries"
on public.queries for update
to anon
using (true)
with check (true);

drop policy if exists "public can read jobs" on public.generation_jobs;
create policy "public can read jobs"
on public.generation_jobs for select
to anon
using (true);

drop policy if exists "public can insert jobs" on public.generation_jobs;
create policy "public can insert jobs"
on public.generation_jobs for insert
to anon
with check (true);

drop policy if exists "public can read reports" on public.property_reports;
create policy "public can read reports"
on public.property_reports for select
to anon
using (true);

drop policy if exists "public can read data sources" on public.data_sources;
create policy "public can read data sources"
on public.data_sources for select
to anon
using (true);
