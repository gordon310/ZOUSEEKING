-- Key/value membership entitlements and C/B audience split.
-- Forward-only migration. Do not run this file from application startup.

alter table public.pricing_plans
  add column if not exists audience text not null default 'c'
    check (audience in ('c', 'b'));
alter table public.pricing_plans
  add column if not exists note text;

create table if not exists public.plan_entitlements (
  id uuid primary key default gen_random_uuid(),
  plan_code text not null references public.pricing_plans(plan_code) on delete cascade,
  metric text not null check (metric in ('query', 'report', 'stats_query', 'export_row', 'subscription_slot')),
  limit_units integer not null check (limit_units >= 0),
  period text not null check (period in ('day', 'month')),
  active boolean not null default true,
  effective_from timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create unique index if not exists uq_plan_entitlements_active
  on public.plan_entitlements(plan_code, metric, period) where active;
create index if not exists idx_plan_entitlements_lookup
  on public.plan_entitlements(plan_code, metric, period) where active;

alter table public.plan_entitlements enable row level security;
revoke all on public.plan_entitlements from anon, authenticated;
grant all privileges on table public.plan_entitlements to service_role;

comment on table public.plan_entitlements is
  'Versioned server-owned plan limits. Active rows are the current key/value entitlement configuration.';
