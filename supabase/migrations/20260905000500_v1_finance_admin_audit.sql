-- V1 finance, back-office roles, and audit (20260905000500).
--
-- Payment orders and refunds (Stripe), an idempotent provider-webhook event
-- ledger that stores only payload hashes, granular internal role assignments,
-- and an append-only structured audit log. Internal domain: all tables are
-- accessed exclusively by the back-office API and trusted services under
-- service_role; anon/authenticated get zero table privileges and no policies.
--
-- Prerequisites (earlier migrations in this batch, applied before this file):
--   auth.users                          (managed Supabase schema)
--   20260905000100  public.organizations

do $$
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;
  if to_regclass('public.organizations') is null then
    raise exception 'missing prerequisite table: public.organizations (20260905000100)';
  end if;
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organizations'
      and column_name = 'id'
      and data_type = 'uuid'
  ) then
    raise exception 'incompatible prerequisite: public.organizations.id must be uuid';
  end if;
end $$;

-- Payment orders: one row per purchase attempt. A scope is exactly one of a
-- personal owner or an organization - never both, never none.
create table if not exists public.payment_orders (
  id uuid primary key default gen_random_uuid(),
  order_no text not null,
  owner_user_id uuid references auth.users(id) on delete set null,
  organization_id uuid references public.organizations(id) on delete set null,
  product_code text not null,
  price_version integer not null,
  currency varchar(3) not null,
  amount_minor integer not null,
  status text not null default 'pending',
  provider text not null,
  provider_session_id text,
  provider_payment_intent_id text,
  paid_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint payment_orders_order_no_unique unique (order_no),
  constraint payment_orders_single_scope check (
    (owner_user_id is null) <> (organization_id is null)
  ),
  constraint payment_orders_currency_allowed check (
    currency in ('CNY', 'HKD', 'TWD', 'MOP', 'JPY', 'USD')
  ),
  constraint payment_orders_amount_positive check (amount_minor > 0),
  constraint payment_orders_status_allowed check (
    status in ('pending', 'paid', 'failed', 'canceled', 'refunded', 'partially_refunded')
  ),
  constraint payment_orders_provider_allowed check (provider in ('stripe')),
  constraint payment_orders_paid_at_status_allowed check (
    paid_at is null or status in ('paid', 'refunded', 'partially_refunded')
  )
);

-- Refunds: one row per refund against a payment order. Amount/currency and
-- reason-specific business rules (unused_period, product_rule,
-- service_failure, ...) are validated by the billing service before a refund
-- row is created - see the table comment below.
create table if not exists public.refunds (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.payment_orders(id) on delete restrict,
  amount_minor integer not null,
  currency varchar(3) not null,
  reason text not null,
  status text not null default 'pending',
  provider_refund_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint refunds_currency_allowed check (
    currency in ('CNY', 'HKD', 'TWD', 'MOP', 'JPY', 'USD')
  ),
  constraint refunds_amount_positive check (amount_minor > 0),
  constraint refunds_reason_allowed check (
    reason in (
      'customer_request', 'unused_period', 'product_rule',
      'service_failure', 'duplicate', 'other'
    )
  ),
  constraint refunds_status_allowed check (
    status in ('pending', 'succeeded', 'failed')
  ),
  constraint refunds_provider_refund_id_unique unique (provider_refund_id)
);

create index if not exists idx_refunds_order_id on public.refunds (order_id);

-- payment_events: idempotency ledger for provider webhooks keyed on the
-- provider's own event id. A repeated delivery inserts nothing (unique
-- provider_event_id); unknown events are marked ignored, transient failures
-- are marked failed for retry. Only the sha256 of the raw provider payload is
-- stored, never the payload itself.
create table if not exists public.payment_events (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  provider_event_id text not null,
  event_type text not null,
  status text not null default 'received',
  payload_sha256 char(64) not null,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  constraint payment_events_provider_event_id_unique unique (provider_event_id),
  constraint payment_events_status_allowed check (
    status in ('received', 'processed', 'failed', 'ignored')
  )
);

-- Internal back-office roles. Permissions are granted per role per action and
-- one user may hold several roles; there is deliberately no omnipotent admin
-- boolean. Only super_admin may grant roles - enforced by the service layer.
create table if not exists public.internal_role_assignments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null,
  granted_by_user_id uuid references auth.users(id) on delete set null,
  granted_at timestamptz not null default now(),
  expires_at timestamptz,
  note text,
  constraint internal_role_assignments_user_role_unique unique (user_id, role),
  constraint internal_role_assignments_role_allowed check (
    role in ('member_ops', 'data_ops', 'task_dispatcher', 'reviewer', 'finance', 'super_admin')
  ),
  constraint internal_role_assignments_expiry_after_grant check (
    expires_at is null or expires_at > granted_at
  )
);

-- Structured audit log (append-only). summary carries a redacted digest only:
-- never full email addresses, tokens, payment credentials, raw provider
-- payloads, or exception stacks.
create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid references auth.users(id) on delete set null,
  action text not null,
  target_type text not null,
  target_id text,
  summary jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now()
);

create index if not exists idx_audit_events_occurred_at
  on public.audit_events (occurred_at desc);
create index if not exists idx_audit_events_actor_user_id
  on public.audit_events (actor_user_id);

-- Append-only enforcement for audit_events: UPDATE, DELETE and TRUNCATE are
-- rejected by triggers.
create or replace function public.audit_events_append_only()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  raise exception 'audit_events is append-only: % is forbidden', tg_op;
end;
$$;

drop trigger if exists audit_events_no_update on public.audit_events;
create trigger audit_events_no_update
  before update on public.audit_events
  for each row execute function public.audit_events_append_only();

drop trigger if exists audit_events_no_delete on public.audit_events;
create trigger audit_events_no_delete
  before delete on public.audit_events
  for each row execute function public.audit_events_append_only();

drop trigger if exists audit_events_no_truncate on public.audit_events;
create trigger audit_events_no_truncate
  before truncate on public.audit_events
  for each statement execute function public.audit_events_append_only();

-- updated_at maintenance for mutable finance tables.
create or replace function public.set_finance_updated_at()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_payment_orders_updated_at on public.payment_orders;
create trigger set_payment_orders_updated_at
  before update on public.payment_orders
  for each row execute function public.set_finance_updated_at();

drop trigger if exists set_refunds_updated_at on public.refunds;
create trigger set_refunds_updated_at
  before update on public.refunds
  for each row execute function public.set_finance_updated_at();

-- Row level security: internal domain only - service_role bypasses RLS via
-- table grants; anon/authenticated have no table privileges and no policies.
alter table public.payment_orders enable row level security;
alter table public.refunds enable row level security;
alter table public.payment_events enable row level security;
alter table public.internal_role_assignments enable row level security;
alter table public.audit_events enable row level security;

revoke all on table
  public.payment_orders,
  public.refunds,
  public.payment_events,
  public.internal_role_assignments,
  public.audit_events
from anon, authenticated;

grant all privileges on table
  public.payment_orders,
  public.refunds,
  public.payment_events,
  public.internal_role_assignments,
  public.audit_events
to service_role;

comment on table public.refunds is
  'Refunds against payment orders. Server-side (billing service) rules: refund'
  'amount must be positive and <= remaining refundable amount of the order,'
  'refund currency must equal the order currency, status may only move'
  'pending -> succeeded/failed, and reason-specific policies apply'
  '(unused_period, product_rule, service_failure).';

comment on table public.payment_events is
  'Provider webhook idempotency ledger. provider_event_id unique guarantees a'
  'duplicate delivery is not processed twice; raw payloads are never stored.';

comment on column public.payment_events.payload_sha256 is
  'Lowercase hex sha256 of the raw provider payload; raw payload is discarded.';

comment on column public.audit_events.summary is
  'Redacted structured digest. Must never contain full emails, tokens, payment'
  'credentials, raw provider payloads, or exception stacks.';

comment on column public.audit_events.actor_user_id is
  'Null when the actor is a service (webhook/system) rather than a user.';
