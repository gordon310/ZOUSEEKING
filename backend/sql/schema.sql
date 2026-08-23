create extension if not exists pgcrypto;

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  username text not null unique,
  email text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now()
);

create table if not exists queries (
  id uuid primary key default gen_random_uuid(),
  query_key text not null unique,
  prefecture text not null,
  city text not null,
  ward text,
  asset_type text not null,
  year int not null,
  month int not null,
  status text not null default 'pending',
  requested_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists generation_jobs (
  id uuid primary key default gen_random_uuid(),
  query_id uuid not null references queries(id) on delete cascade,
  status text not null default 'pending',
  progress int not null default 0,
  current_step text not null default '等待开始',
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists property_reports (
  id uuid primary key default gen_random_uuid(),
  query_id uuid not null unique references queries(id) on delete cascade,
  slug text not null unique,
  title text not null,
  publish_month text not null,
  markdown text not null,
  xhs_content text not null,
  rental jsonb not null default '[]'::jsonb,
  sale jsonb not null default '[]'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  images jsonb not null default '[]'::jsonb,
  data_sources jsonb not null default '[]'::jsonb,
  raw_record jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists data_sources (
  id uuid primary key default gen_random_uuid(),
  query_id uuid references queries(id) on delete cascade,
  source_name text not null,
  source_url text not null,
  source_role text not null,
  status text not null default 'pending',
  error_message text,
  fetched_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_queries_location on queries(prefecture, city, ward, asset_type, year, month);
create index if not exists idx_queries_status on queries(status);
create index if not exists idx_jobs_query_status on generation_jobs(query_id, status);
create index if not exists idx_reports_title on property_reports using gin(to_tsvector('simple', title || ' ' || markdown));

