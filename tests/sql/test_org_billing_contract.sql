\set ON_ERROR_STOP 1
begin;

do $$
declare
  missing text[];
  org_id uuid := gen_random_uuid();
  owner_id uuid := gen_random_uuid();
  month_key text := to_char(now() at time zone 'Asia/Shanghai', 'YYYY-MM');
  rows_count integer;
begin
  select array_agg(x.table_name || '.' || x.column_name order by 1) into missing
  from (values
    ('usage_quotas','id'), ('usage_quotas','scope_key'), ('usage_quotas','usage_kind'), ('usage_quotas','period_key'), ('usage_quotas','limit_units'), ('usage_quotas','consumed_units'), ('usage_quotas','reserved_units'), ('usage_quotas','reset_at'), ('usage_quotas','updated_at'),
    ('payment_orders','id'), ('payment_orders','order_no'), ('payment_orders','owner_user_id'), ('payment_orders','organization_id'), ('payment_orders','product_code'), ('payment_orders','price_version'), ('payment_orders','currency'), ('payment_orders','amount_minor'), ('payment_orders','status'), ('payment_orders','provider'), ('payment_orders','provider_session_id'), ('payment_orders','provider_payment_intent_id'), ('payment_orders','paid_at'), ('payment_orders','created_at'), ('payment_orders','updated_at'), ('payment_orders','subject_id'),
    ('subscriptions','id'), ('subscriptions','user_id'), ('subscriptions','organization_id'), ('subscriptions','product_code'), ('subscriptions','price_version'), ('subscriptions','currency'), ('subscriptions','amount_minor'), ('subscriptions','stripe_customer_id'), ('subscriptions','stripe_subscription_id'), ('subscriptions','status'), ('subscriptions','current_period_start'), ('subscriptions','current_period_end'), ('subscriptions','cancel_at_period_end'), ('subscriptions','created_at'), ('subscriptions','updated_at'),
    ('exports','id'), ('exports','owner_user_id'), ('exports','organization_id'), ('exports','status'), ('exports','row_count'), ('exports','csv_content'), ('exports','created_at'),
    ('plan_entitlements','plan_code'), ('plan_entitlements','metric'), ('plan_entitlements','period'), ('plan_entitlements','limit_units'), ('plan_entitlements','active'),
    ('pricing_plans','plan_code'), ('pricing_plans','audience'), ('pricing_plans','active'),
    ('organization_members','id'), ('organization_members','organization_id'), ('organization_members','user_id'), ('organization_members','role'), ('organization_members','status'), ('organization_members','created_at'), ('organization_members','updated_at'),
    ('organizations','id'), ('organizations','name'), ('organizations','partner_status'), ('organizations','created_by_user_id'), ('organizations','created_at'), ('organizations','updated_at')
  ) as x(table_name, column_name)
  where not exists (select 1 from information_schema.columns c where c.table_schema='public' and c.table_name=x.table_name and c.column_name=x.column_name);
  if missing is not null then raise exception 'missing M-B2 columns: %', missing; end if;

  insert into auth.users(id, aud, role, email, encrypted_password, raw_app_meta_data, raw_user_meta_data)
    values(owner_id, 'authenticated', 'authenticated', 'mb2-contract@example.com', '', '{}'::jsonb, '{}'::jsonb);
  insert into public.organizations(id, name, created_by_user_id) values(org_id, 'M-B2 contract org', owner_id);
  insert into public.organization_members(organization_id, user_id, role, status) values(org_id, owner_id, 'owner', 'active');
  insert into public.pricing_plans(plan_code, name, audience, active) values('free_b', 'B Free', 'b', true) on conflict (plan_code) do nothing;
  insert into public.plan_entitlements(plan_code, metric, period, limit_units, active) values('free_b', 'query', 'month', 10, true) on conflict do nothing;
  insert into public.usage_quotas(scope_key, usage_kind, period_key, limit_units, consumed_units) values('org:' || org_id, 'query', month_key, 10, 2);
  insert into public.payment_orders(order_no, organization_id, product_code, price_version, currency, amount_minor, status, provider)
    values('mb2-contract-' || replace(org_id::text, '-', ''), org_id, 'b_data_pro_monthly', 1, 'JPY', 399900, 'paid', 'stripe');
  insert into public.subscriptions(organization_id, product_code, price_version, currency, amount_minor, status, current_period_start, current_period_end)
    values(org_id, 'b_data_pro_monthly', 1, 'JPY', 399900, 'active', now(), now() + interval '1 month');

  select count(*) into rows_count from public.usage_quotas where scope_key='org:' || org_id and period_key=month_key and usage_kind='query';
  if rows_count <> 1 then raise exception 'usage query mismatch: %', rows_count; end if;
  select count(*) into rows_count from public.payment_orders where organization_id=org_id and amount_minor=399900 and currency='JPY' and status='paid';
  if rows_count <> 1 then raise exception 'billing query mismatch: %', rows_count; end if;
  select count(*) into rows_count from public.subscriptions where organization_id=org_id and product_code='b_data_pro_monthly' and status='active';
  if rows_count <> 1 then raise exception 'subscription query mismatch: %', rows_count; end if;
  if array['账期','用量类型','已用','上限','订单金额(最小单位)','币种','订单状态'] <> array['账期','用量类型','已用','上限','订单金额(最小单位)','币种','订单状态'] then raise exception 'CSV allowlist mismatch'; end if;
  raise notice 'test_org_billing_contract: all assertions passed (columns=73, usage=1, orders=1, subscriptions=1, rollback=yes)';
end $$;

rollback;
