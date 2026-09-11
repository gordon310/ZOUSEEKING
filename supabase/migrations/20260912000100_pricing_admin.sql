-- Pricing catalog managed by the back office.
-- Forward-only migration. Do not run this file from the application startup path.

create table if not exists public.pricing_products (
  product_code text primary key,
  name text not null,
  checkout_mode text not null check (checkout_mode in ('payment', 'subscription')),
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.pricing_prices (
  id uuid primary key default gen_random_uuid(),
  product_code text not null references public.pricing_products(product_code),
  currency text not null check (currency in ('CNY', 'HKD', 'TWD', 'MOP', 'JPY', 'USD', 'SGD')),
  amount_minor bigint not null check (amount_minor > 0),
  stripe_price_id text not null default '',
  price_version integer not null check (price_version > 0),
  active boolean not null default true,
  effective_from timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  note text
);

create index if not exists idx_pricing_prices_latest
  on public.pricing_prices(product_code, currency, active, price_version desc, effective_from desc);

create table if not exists public.pricing_regions (
  region_code text primary key,
  currency text not null check (currency in ('CNY', 'HKD', 'TWD', 'MOP', 'JPY', 'USD', 'SGD')),
  active boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.pricing_plans (
  plan_code text primary key,
  name text not null,
  monthly_query_limit integer not null check (monthly_query_limit >= 0),
  monthly_report_quota integer not null check (monthly_report_quota >= 0),
  subscription_slots integer not null check (subscription_slots >= 0),
  export_rows_monthly integer not null check (export_rows_monthly >= 0),
  plan_version integer not null default 1 check (plan_version > 0),
  active boolean not null default true,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

do $$
declare
  table_name text;
begin
  foreach table_name in array array['pricing_products', 'pricing_prices', 'pricing_regions', 'pricing_plans'] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on public.%I from anon, authenticated', table_name);
    execute format('grant all privileges on table public.%I to service_role', table_name);
  end loop;
end $$;

comment on table public.pricing_prices is
  'Append-only local price versions. Orders retain the selected price_version.';
comment on table public.pricing_plans is
  'Server-owned entitlement defaults. plan_version increments on every admin change.';
