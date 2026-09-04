-- V1 products/prices/subscriptions schema assertions.
-- Run against a disposable Supabase/PostgreSQL database only, after
-- 20260905000100_v1_organizations.sql and
-- 20260905000200_v1_products_subscriptions.sql are applied in order.
--
-- Four-identity behavior tests (anon / personal C user / B org member /
-- member of another org / service role) are appended once the staging
-- migration baseline reconciliation gate passes, per
-- docs/superpowers/plans/2026-09-05-b2-v1-business-migrations.md.
do $$
declare
  required_table text;
  required_column text;
  required_constraint text;
  required_index text;
begin
  foreach required_table in array array[
    'product_prices', 'billing_customers', 'subscriptions'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing table: public.%', required_table;
    end if;
    if not exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = required_table
        and c.relrowsecurity
    ) then
      raise exception 'RLS disabled for %', required_table;
    end if;
  end loop;

  foreach required_column in array array[
    'product_code', 'mode', 'currency', 'amount_minor', 'price_version',
    'stripe_price_id', 'effective_from', 'effective_until'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'product_prices'
        and column_name = required_column
    ) then
      raise exception 'missing product_prices.% column', required_column;
    end if;
  end loop;

  foreach required_column in array array[
    'owner_user_id', 'organization_id', 'stripe_customer_id',
    'created_at', 'updated_at'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'billing_customers'
        and column_name = required_column
    ) then
      raise exception 'missing billing_customers.% column', required_column;
    end if;
  end loop;

  foreach required_column in array array[
    'user_id', 'organization_id', 'product_code', 'price_version',
    'currency', 'amount_minor', 'stripe_customer_id',
    'stripe_subscription_id', 'status', 'current_period_start',
    'current_period_end', 'cancel_at_period_end', 'created_at', 'updated_at'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = 'subscriptions'
        and column_name = required_column
    ) then
      raise exception 'missing subscriptions.% column', required_column;
    end if;
  end loop;

  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'product_prices'
      and column_name = 'amount_minor'
      and data_type <> 'integer'
  ) then
    raise exception 'product_prices.amount_minor must be integer';
  end if;
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'product_prices'
      and column_name = 'currency'
      and (data_type <> 'character' or character_maximum_length <> 3)
  ) then
    raise exception 'product_prices.currency must be char(3)';
  end if;
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'subscriptions'
      and column_name = 'amount_minor'
      and data_type <> 'integer'
  ) then
    raise exception 'subscriptions.amount_minor must be integer';
  end if;

  foreach required_constraint in array array[
    'product_prices_product_code_allowed',
    'product_prices_mode_allowed',
    'product_prices_currency_allowed',
    'product_prices_amount_minor_positive',
    'product_prices_price_version_positive',
    'product_prices_mode_matches_code',
    'product_prices_effective_window',
    'product_prices_code_currency_version_unique'
  ] loop
    if not exists (
      select 1 from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'product_prices'
        and c.conname = required_constraint
    ) then
      raise exception 'missing product_prices constraint: %', required_constraint;
    end if;
  end loop;

  foreach required_constraint in array array[
    'billing_customers_single_scope',
    'billing_customers_stripe_customer_unique'
  ] loop
    if not exists (
      select 1 from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'billing_customers'
        and c.conname = required_constraint
    ) then
      raise exception 'missing billing_customers constraint: %', required_constraint;
    end if;
  end loop;

  foreach required_constraint in array array[
    'subscriptions_single_scope',
    'subscriptions_product_allowed',
    'subscriptions_scope_matches_product',
    'subscriptions_price_version_positive',
    'subscriptions_currency_allowed',
    'subscriptions_amount_minor_positive',
    'subscriptions_status_allowed',
    'subscriptions_stripe_subscription_unique'
  ] loop
    if not exists (
      select 1 from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      where n.nspname = 'public'
        and t.relname = 'subscriptions'
        and c.conname = required_constraint
    ) then
      raise exception 'missing subscriptions constraint: %', required_constraint;
    end if;
  end loop;

  foreach required_index in array array[
    'uq_billing_customers_owner_user_id',
    'uq_billing_customers_organization_id'
  ] loop
    if not exists (
      select 1 from pg_indexes
      where schemaname = 'public'
        and tablename = 'billing_customers'
        and indexname = required_index
    ) then
      raise exception 'missing billing_customers index: %', required_index;
    end if;
  end loop;

  foreach required_index in array array[
    'idx_subscriptions_user_status',
    'idx_subscriptions_organization_status'
  ] loop
    if not exists (
      select 1 from pg_indexes
      where schemaname = 'public'
        and tablename = 'subscriptions'
        and indexname = required_index
    ) then
      raise exception 'missing subscriptions index: %', required_index;
    end if;
  end loop;

  -- Anonymous must have no REST policies on any of the three tables.
  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('product_prices', 'billing_customers', 'subscriptions')
      and roles::text like '%anon%'
  ) then
    raise exception 'anonymous REST policy exists on v1 billing tables';
  end if;

  -- Authenticated may only SELECT (never INSERT/UPDATE/DELETE) on the three
  -- tables, and must have no policy at all on the customer mirror.
  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename in ('product_prices', 'billing_customers', 'subscriptions')
      and roles::text like '%authenticated%'
      and cmd <> 'SELECT'
  ) then
    raise exception 'authenticated write policy exists on v1 billing tables';
  end if;
  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'billing_customers'
      and roles::text like '%authenticated%'
  ) then
    raise exception 'authenticated policy exists on billing_customers';
  end if;

  -- Required scope-scoped read policies are present.
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'subscriptions'
      and policyname = 'users can read own subscriptions'
      and cmd = 'SELECT'
      and roles::text like '%authenticated%'
  ) then
    raise exception 'missing subscriptions read policy';
  end if;
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'product_prices'
      and policyname = 'authenticated can read effective prices'
      and cmd = 'SELECT'
      and roles::text like '%authenticated%'
  ) then
    raise exception 'missing product_prices effective-read policy';
  end if;

  -- Grant surface: no anonymous grants; authenticated has SELECT only;
  -- service_role is fully privileged on every table.
  if exists (
    select 1 from information_schema.role_table_grants
    where grantee = 'anon'
      and table_schema = 'public'
      and table_name in ('product_prices', 'billing_customers', 'subscriptions')
  ) then
    raise exception 'anonymous table grant exists on v1 billing tables';
  end if;
  if exists (
    select 1 from information_schema.role_table_grants
    where grantee = 'authenticated'
      and table_schema = 'public'
      and table_name in ('product_prices', 'billing_customers', 'subscriptions')
      and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER')
  ) then
    raise exception 'authenticated write grant exists on v1 billing tables';
  end if;
  if exists (
    select 1
    from (select unnest(array['product_prices', 'billing_customers', 'subscriptions']) as t) x
    where not exists (
      select 1 from information_schema.role_table_grants
      where grantee = 'service_role'
        and table_schema = 'public'
        and table_name = x.t
        and privilege_type = 'SELECT'
    )
  ) then
    raise exception 'service_role lacks privileges on v1 billing tables';
  end if;
end $$;
