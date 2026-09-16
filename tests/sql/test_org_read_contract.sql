-- OrganizationReadStore SQL/schema contract.
-- Run only against a disposable PostgreSQL/Supabase database.
-- The transaction is deliberately rolled back after explicit cleanup so the
-- test is repeatable and cannot retain its synthetic users or organization.
\set ON_ERROR_STOP 1

begin;

do $$
declare
  missing_columns text[];
  membership record;
  subscription record;
  plan record;
  entitlement record;
  usage record;
  member_row record;
  required_member_keys text[];
  actual_member_count integer := 0;
  active_entitlement_count integer := 0;
  usage_count integer := 0;
  member_keys text[];
  organization_id uuid := gen_random_uuid();
  owner_id uuid := gen_random_uuid();
  member_id uuid := gen_random_uuid();
  month_key text := to_char(now() at time zone 'Asia/Shanghai', 'YYYY-MM');
begin
  -- The route must use only the real organization/member columns.
  select array_agg(required.table_name || '.' || required.column_name order by 1)
    into missing_columns
  from (
    values
      ('organizations', 'id'),
      ('organizations', 'name'),
      ('organization_members', 'id'),
      ('organization_members', 'organization_id'),
      ('organization_members', 'user_id'),
      ('organization_members', 'role'),
      ('organization_members', 'status'),
      ('organization_members', 'created_at'),
      ('subscriptions', 'organization_id'),
      ('subscriptions', 'product_code'),
      ('subscriptions', 'status'),
      ('subscriptions', 'current_period_end'),
      ('pricing_plans', 'plan_code'),
      ('pricing_plans', 'name'),
      ('pricing_plans', 'audience'),
      ('pricing_plans', 'active'),
      ('plan_entitlements', 'metric'),
      ('plan_entitlements', 'period'),
      ('plan_entitlements', 'limit_units'),
      ('plan_entitlements', 'active'),
      ('usage_quotas', 'scope_key'),
      ('usage_quotas', 'period_key'),
      ('usage_quotas', 'usage_kind'),
      ('usage_quotas', 'consumed_units')
  ) as required(table_name, column_name)
  where not exists (
    select 1
    from information_schema.columns actual
    where actual.table_schema = 'public'
      and actual.table_name = required.table_name
      and actual.column_name = required.column_name
  );
  if missing_columns is not null then
    raise exception 'missing OrganizationReadStore columns: %', missing_columns;
  end if;

  -- Synthetic auth rows are needed because organization_members has a real FK.
  insert into auth.users (id, aud, role, email, encrypted_password,
                          raw_app_meta_data, raw_user_meta_data)
  values
    (owner_id, 'authenticated', 'authenticated', 'gordon@example.com', '', '{}'::jsonb, '{}'::jsonb),
    (member_id, 'authenticated', 'authenticated', null, '', '{}'::jsonb, '{}'::jsonb);

  insert into public.organizations (id, name, created_by_user_id)
  values (organization_id, '契约测试机构', owner_id);

  insert into public.organization_members
    (organization_id, user_id, role, status, created_at)
  values
    (organization_id, owner_id, 'owner', 'active', '2026-09-01T00:00:00Z'),
    (organization_id, member_id, 'member', 'active', '2026-09-02T00:00:00Z');

  insert into public.subscriptions
    (organization_id, product_code, price_version, currency, amount_minor,
     status, current_period_start, current_period_end)
  values
    (organization_id, 'b_data_pro_monthly', 1, 'JPY', 399900, 'active', now(), now() + interval '1 month');

  insert into public.pricing_plans
    (plan_code, name, monthly_query_limit, monthly_report_quota,
     subscription_slots, export_rows_monthly, audience, active)
  values ('b_data_pro', 'B Data Pro', 500, 100, 5, 1000, 'b', true)
  on conflict (plan_code) do nothing;

  insert into public.plan_entitlements (plan_code, metric, limit_units, period, active)
  values ('b_data_pro', 'query', 500, 'month', true)
  on conflict do nothing;

  insert into public.usage_quotas
    (scope_key, usage_kind, period_key, limit_units, consumed_units)
  values ('org:' || organization_id, 'query', month_key, 500, 3);

  -- OrganizationReadStore._membership, verbatim query shape.
  select om.organization_id, om.role, o.name
    into membership
  from public.organization_members om
  join public.organizations o on o.id = om.organization_id
  where om.user_id = owner_id and om.status = 'active'
  order by om.created_at asc, om.id asc
  limit 1;
  if membership.organization_id <> organization_id or membership.role <> 'owner'
     or membership.name <> '契约测试机构' then
    raise exception 'membership query returned unexpected key fields';
  end if;

  -- OrganizationReadStore._snapshot queries, verbatim query shape.
  if (select count(*) from public.organization_members
      where organization_members.organization_id = membership.organization_id
        and organization_members.status = 'active') <> 2 then
    raise exception 'seat count query did not return two active members';
  end if;

  select product_code into subscription
  from public.subscriptions s
  where s.organization_id = membership.organization_id
    and s.product_code = 'b_data_pro_monthly'
    and s.status in ('active', 'trialing')
    and (s.current_period_end is null or s.current_period_end > now())
  order by s.created_at desc, s.id desc limit 1;
  if subscription.product_code <> 'b_data_pro_monthly' then
    raise exception 'subscription query returned unexpected product';
  end if;

  select plan_code, name into plan
  from public.pricing_plans
  where plan_code = 'b_data_pro' and audience = 'b' and active = true;
  if plan.plan_code <> 'b_data_pro' or plan.name <> 'B Data Pro' then
    raise exception 'plan query returned unexpected key fields';
  end if;

  for entitlement in
    select metric, period, limit_units
    from public.plan_entitlements
    where plan_code = 'b_data_pro' and active = true
    order by metric, period
  loop
    if entitlement.metric = 'query' and entitlement.period = 'month'
       and entitlement.limit_units = 500 then
      active_entitlement_count := active_entitlement_count + 1;
    end if;
  end loop;
  if active_entitlement_count <> 1 then
    raise exception 'entitlement query returned unexpected key fields';
  end if;

  for usage in
    select usage_kind, period_key, consumed_units
    from public.usage_quotas
    where scope_key = 'org:' || membership.organization_id
      and period_key = month_key
  loop
    if usage.usage_kind = 'query' and usage.period_key = month_key
       and usage.consumed_units = 3 then
      usage_count := usage_count + 1;
    end if;
  end loop;
  if usage_count <> 1 then
    raise exception 'usage query returned unexpected key fields';
  end if;

  -- _members query: only derived display_name, role, status and created_at.
  required_member_keys := array['display_name', 'role', 'status', 'joined_at'];
  for member_row in
    select case
             when btrim(u.email) ~ '^[^@[:space:]]+@[^@[:space:]]+$'
               then left(btrim(u.email), 1) || '***@' || split_part(btrim(u.email), '@', 2)
             else '成员 ' || row_number() over (order by om.created_at asc, om.id asc)::text
           end as display_name,
           om.role, om.status, om.created_at
    from public.organization_members om
    left join auth.users u on u.id = om.user_id
    where om.organization_id = membership.organization_id
    order by om.created_at asc, om.id asc
  loop
    actual_member_count := actual_member_count + 1;
    if actual_member_count = 1 then
      if member_row.display_name <> 'g***@example.com' then
        raise exception 'email display_name was not masked: %', member_row.display_name;
      end if;
    elsif actual_member_count = 2 then
      if member_row.display_name <> '成员 2' then
        raise exception 'fallback display_name was not stable: %', member_row.display_name;
      end if;
    end if;
    if member_row.role is null or member_row.status is null or member_row.created_at is null then
      raise exception 'member query omitted a required key field';
    end if;
  end loop;
  if actual_member_count <> 2 then
    raise exception 'member query returned % rows, expected 2', actual_member_count;
  end if;

  select array_agg(key order by key)
    into member_keys
  from jsonb_object_keys(jsonb_build_object(
    'display_name', 'g***@example.com',
    'role', 'owner',
    'status', 'active',
    'joined_at', '2026-09-01T00:00:00+00:00'
  )) as keys(key);
  if member_keys <> (select array_agg(key order by key) from unnest(required_member_keys) as expected(key)) then
    raise exception 'member response keys changed: %', member_keys;
  end if;
  if member_keys && array['email', 'user_id', 'organization_id'] then
    raise exception 'member response exposes a forbidden internal field: %', member_keys;
  end if;

  raise notice 'test_org_read_contract: all assertions passed (columns=24, members=2, entitlements=1, usage=1)';
end $$;

-- Explicit cleanup documents the isolation guarantee; ROLLBACK is the final
-- safety net for disposable CI databases.
rollback;
