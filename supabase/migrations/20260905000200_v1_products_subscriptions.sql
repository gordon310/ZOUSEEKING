-- V1 product prices, billing customers and subscriptions.
-- Domain 3+4 of the frozen B2 plan (docs/superpowers/plans/2026-09-05-b2-v1-business-migrations.md).
-- Runs after 20260905000100_v1_organizations.sql in the same batch:
-- public.organizations and public.organization_members must already exist.
--
-- Design notes (see docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md):
-- * The price catalog supports six currencies but this file seeds no rows.
--   At launch only CNY/JPY/USD are sold: an approved, currently-effective
--   price row is inserted by the trusted service (with a Stripe price id)
--   before a billing region goes live. A region without an effective local
--   price cannot purchase; there is no client-side currency conversion.
-- * Local prices are versioned and immutable; effective_from/effective_until
--   windows supersede, never overwrite, an earlier version.
-- * C-side products (risk_report_single, c_plus_monthly) belong to a user;
--   B Data Pro (b_data_pro_monthly) belongs to an organization and its quota
--   is shared by the organization's active members.
-- * subscription rows snapshot product/price/currency/amount_minor at
--   purchase time and mirror Stripe subscription objects only
--   (subscription-mode products); one-time report purchases are recorded in
--   the finance domain, not here.
-- * Browser clients never write subscription status, ownership, price or
--   amount fields: writes happen exclusively through the service role
--   (Stripe webhooks / trusted backend).

do $$
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;
  if to_regclass('public.organizations') is null then
    raise exception 'missing prerequisite table: public.organizations';
  end if;
  if to_regclass('public.organization_members') is null then
    raise exception 'missing prerequisite table: public.organization_members';
  end if;
end $$;

-- Versioned local price catalog ---------------------------------------------
create table if not exists public.product_prices (
  id uuid primary key default gen_random_uuid(),
  product_code text not null,
  mode text not null,
  currency char(3) not null,
  amount_minor integer not null,
  price_version integer not null,
  stripe_price_id text,
  effective_from timestamptz not null,
  effective_until timestamptz,
  constraint product_prices_product_code_allowed check (product_code in (
    'risk_report_single', 'c_plus_monthly', 'b_data_pro_monthly'
  )),
  constraint product_prices_mode_allowed check (mode in ('payment', 'subscription')),
  constraint product_prices_currency_allowed check (currency in (
    'CNY', 'HKD', 'TWD', 'MOP', 'JPY', 'USD'
  )),
  constraint product_prices_amount_minor_positive check (amount_minor > 0),
  constraint product_prices_price_version_positive check (price_version >= 1),
  constraint product_prices_mode_matches_code check (
    (product_code = 'risk_report_single' and mode = 'payment')
    or (product_code in ('c_plus_monthly', 'b_data_pro_monthly') and mode = 'subscription')
  ),
  constraint product_prices_effective_window check (
    effective_until is null or effective_until > effective_from
  ),
  constraint product_prices_code_currency_version_unique
    unique (product_code, currency, price_version)
);

-- Stripe customer mirror, scoped to exactly one billing subject -------------
create table if not exists public.billing_customers (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid references auth.users(id) on delete cascade,
  organization_id uuid references public.organizations(id) on delete cascade,
  stripe_customer_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint billing_customers_single_scope check (
    (owner_user_id is null) <> (organization_id is null)
  ),
  constraint billing_customers_stripe_customer_unique unique (stripe_customer_id)
);

-- Exactly one Stripe customer per personal user and per organization.
create unique index if not exists uq_billing_customers_owner_user_id
  on public.billing_customers(owner_user_id)
  where owner_user_id is not null;
create unique index if not exists uq_billing_customers_organization_id
  on public.billing_customers(organization_id)
  where organization_id is not null;

-- Stripe-backed subscriptions (entitlements) --------------------------------
create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  organization_id uuid references public.organizations(id) on delete cascade,
  product_code text not null,
  price_version integer not null,
  currency char(3) not null,
  amount_minor integer not null,
  stripe_customer_id text,
  stripe_subscription_id text,
  status text not null,
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint subscriptions_single_scope check (
    (user_id is null) <> (organization_id is null)
  ),
  constraint subscriptions_product_allowed check (product_code in (
    'c_plus_monthly', 'b_data_pro_monthly'
  )),
  constraint subscriptions_scope_matches_product check (
    (product_code = 'c_plus_monthly' and user_id is not null and organization_id is null)
    or (product_code = 'b_data_pro_monthly' and user_id is null and organization_id is not null)
  ),
  constraint subscriptions_price_version_positive check (price_version >= 1),
  constraint subscriptions_currency_allowed check (currency in (
    'CNY', 'HKD', 'TWD', 'MOP', 'JPY', 'USD'
  )),
  constraint subscriptions_amount_minor_positive check (amount_minor > 0),
  constraint subscriptions_status_allowed check (status in (
    'trialing', 'active', 'past_due', 'canceled', 'unpaid',
    'incomplete', 'incomplete_expired'
  )),
  constraint subscriptions_stripe_subscription_unique unique (stripe_subscription_id)
);

-- Entitlement/quota resolution: active subscriptions per personal user and
-- per organization (quota is shared by the organization's active members).
create index if not exists idx_subscriptions_user_status
  on public.subscriptions(user_id, status);
create index if not exists idx_subscriptions_organization_status
  on public.subscriptions(organization_id, status);

-- Row level security ---------------------------------------------------------
alter table public.product_prices enable row level security;
alter table public.billing_customers enable row level security;
alter table public.subscriptions enable row level security;

revoke all on public.product_prices,
  public.billing_customers,
  public.subscriptions
from anon, authenticated;

-- Anonymous never touches these tables. Authenticated users may only read
-- their own subscription scope or currently-effective prices for display.
-- billing_customers is a service-internal Stripe mirror: browsers must not
-- read customer ids or write any billing state.
grant select on public.product_prices,
  public.subscriptions
to authenticated;

drop policy if exists "authenticated can read effective prices" on public.product_prices;
create policy "authenticated can read effective prices"
on public.product_prices for select to authenticated
using (
  effective_from <= now()
  and (effective_until is null or effective_until > now())
);

drop policy if exists "users can read own subscriptions" on public.subscriptions;
create policy "users can read own subscriptions"
on public.subscriptions for select to authenticated
using (
  user_id = (select auth.uid())
  or exists (
    select 1
    from public.organization_members om
    where om.organization_id = subscriptions.organization_id
      and om.user_id = (select auth.uid())
      and om.status = 'active'
  )
);

-- Trusted worker path: full access for the service role (bypasses RLS).
grant all privileges on table public.product_prices,
  public.billing_customers,
  public.subscriptions
to service_role;

-- updated_at maintenance -----------------------------------------------------
drop trigger if exists set_billing_customers_updated_at on public.billing_customers;
create trigger set_billing_customers_updated_at
before update on public.billing_customers
for each row execute function public.set_updated_at();

drop trigger if exists set_subscriptions_updated_at on public.subscriptions;
create trigger set_subscriptions_updated_at
before update on public.subscriptions
for each row execute function public.set_updated_at();
