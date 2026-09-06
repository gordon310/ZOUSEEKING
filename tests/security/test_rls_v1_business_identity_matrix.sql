-- V1 business-domain RLS identity behavior matrix.
-- Covers the 20260905000100..00601 batch: organizations, products/
-- subscriptions, usage ledger, service tasks/contacts, finance/admin/audit,
-- member-status column fence (00600) and collection_runs (00601).
--
-- The catalog-only assertions for these tables live in tests/sql/test_v1_*.sql
-- and tests/sql/test_{member_status,collection_runs}.sql.  This file adds the
-- behavioural half promised there ("four-identity behavior matrix is added
-- once the baseline gate allows applying this migration group to a live
-- stack"): fixtures are inserted, then each of the four identities
-- (anonymous / unrelated authenticated user / scoped owner / service_role
-- worker) is SET LOCAL and probed with real DML.  The whole file runs in one
-- transaction and rolls back, so a disposable database stays untouched.
--
-- Identity fixtures (transaction-scoped synthetic UUIDs):
--   U1 owner-401 : active owner of ORG-411; creator of draft_task;
--                  personal subscription + personal usage quota.
--   U2 other-402 : unrelated authenticated user; creator of open_task.
--   ORG-411      : single-owner organization (owner U1, active).
--
-- Expected access contract (from the migrations):
--   anon          -> zero table privileges on every V1 business table.
--   authenticated -> SELECT-only grants, row visibility scoped by RLS
--                    (own scope / membership / open task listing); no write
--                    grant anywhere except the user_profiles preference
--                    column allowlist (00600) and organizations.name
--                    (active owner only).
--   service_role  -> full table privileges (bypasses RLS); append-only
--                    triggers still reject UPDATE/DELETE on usage_events and
--                    audit_events.

begin;

-- ---------------------------------------------------------------------------
-- 0. Fixtures (inserted as the maintenance superuser; RLS is bypassed).
-- ---------------------------------------------------------------------------
insert into auth.users (
  id, aud, role, raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
  ('00000000-0000-0000-0000-000000000401', 'authenticated', 'authenticated', '{}'::jsonb, '{}'::jsonb, now(), now()),
  ('00000000-0000-0000-0000-000000000402', 'authenticated', 'authenticated', '{}'::jsonb, '{}'::jsonb, now(), now());

insert into public.user_profiles (user_id, bio, membership_tier, daily_query_limit) values
  ('00000000-0000-0000-0000-000000000401', 'owner fixture', 'free', 3),
  ('00000000-0000-0000-0000-000000000402', 'other fixture', 'free', 3);

insert into public.organizations (id, name, partner_status, created_by_user_id) values
  ('00000000-0000-0000-0000-000000000411', 'fixture org', 'none', '00000000-0000-0000-0000-000000000401');

insert into public.organization_members (
  id, organization_id, user_id, role, status
) values (
  '00000000-0000-0000-0000-000000000421',
  '00000000-0000-0000-0000-000000000411',
  '00000000-0000-0000-0000-000000000401',
  'owner', 'active'
);

-- Currently-effective local price (readable) and a future-version price
-- (must stay invisible to authenticated users).
insert into public.product_prices (
  id, product_code, mode, currency, amount_minor, price_version,
  effective_from, effective_until
) values
  ('00000000-0000-0000-0000-000000000431', 'risk_report_single', 'payment', 'JPY', 5000, 1,
   now() - interval '1 day', null),
  ('00000000-0000-0000-0000-000000000432', 'risk_report_single', 'payment', 'JPY', 6000, 2,
   now() + interval '1 day', null);

-- Billing customer mirror for ORG (service-internal: not readable by browser).
insert into public.billing_customers (
  id, organization_id, stripe_customer_id
) values (
  '00000000-0000-0000-0000-000000000441',
  '00000000-0000-0000-0000-000000000411',
  'cus_fixture_org'
);

-- One personal (C) subscription for U1 and one organization (B) subscription
-- for ORG, both active.  U1 may read both (owner + active member); U2 reads
-- neither.
insert into public.subscriptions (
  id, user_id, organization_id, product_code, price_version,
  currency, amount_minor, status
) values
  ('00000000-0000-0000-0000-000000000451',
   '00000000-0000-0000-0000-000000000401', null,
   'c_plus_monthly', 1, 'JPY', 990, 'active'),
  ('00000000-0000-0000-0000-000000000452',
   null, '00000000-0000-0000-0000-000000000411',
   'b_data_pro_monthly', 1, 'JPY', 3990, 'active');

-- Usage counters/events for the personal scope user:U1 and the org scope
-- org:ORG-411 (member-shared quota).
insert into public.usage_quotas (
  id, scope_key, usage_kind, period_key, limit_units, consumed_units
) values
  ('00000000-0000-0000-0000-000000000461',
   'user:00000000-0000-0000-0000-000000000401', 'query', '2026-09', 10, 2),
  ('00000000-0000-0000-0000-000000000462',
   'org:00000000-0000-0000-0000-000000000411', 'query', '2026-09', 100, 5);

insert into public.usage_events (
  id, scope_key, usage_kind, operation, units, period_key, actor_user_id
) values (
  '00000000-0000-0000-0000-000000000471',
  'user:00000000-0000-0000-0000-000000000401',
  'query', 'consume', 1, '2026-09', '00000000-0000-0000-0000-000000000401'
);

-- Service task pool: a private draft owned by U1 and an open listing created
-- by U2 that ORG-411 has applied to (pending).
insert into public.service_tasks (
  id, creator_user_id, purpose, compensation, public_description, status
) values
  ('00000000-0000-0000-0000-000000000481',
   '00000000-0000-0000-0000-000000000401',
   'fixture draft', 'paid', 'private draft fixture task body', 'draft'),
  ('00000000-0000-0000-0000-000000000482',
   '00000000-0000-0000-0000-000000000402',
   'fixture open task', 'paid', 'public open fixture task body', 'open');

insert into public.task_applications (
  id, task_id, organization_id, assigned_member_user_id, status
) values (
  '00000000-0000-0000-0000-000000000491',
  '00000000-0000-0000-0000-000000000482',
  '00000000-0000-0000-0000-000000000411',
  '00000000-0000-0000-0000-000000000401',
  'pending'
);

insert into public.task_status_history (
  id, task_id, from_status, to_status, changed_by_user_id
) values (
  '00000000-0000-0000-0000-0000000004a1',
  '00000000-0000-0000-0000-000000000482',
  null, 'open', '00000000-0000-0000-0000-000000000402'
);

-- Consent record on the open task: C side is U2 (creator), B side is ORG-411
-- with U1 as the responsible member/owner.  Emails stay NULL (no mutual grant).
insert into public.contact_consents (
  id, task_id, c_user_id, b_organization_id, b_member_user_id,
  consent_version, c_status, b_status
) values (
  '00000000-0000-0000-0000-0000000004b1',
  '00000000-0000-0000-0000-000000000482',
  '00000000-0000-0000-0000-000000000402',
  '00000000-0000-0000-0000-000000000411',
  '00000000-0000-0000-0000-000000000401',
  'fixture-v1', 'pending', 'pending'
);

-- ---------------------------------------------------------------------------
-- 1. Anonymous: every V1 business table denies even a SELECT at the
--    privilege layer (revoke all ... from anon; no anon grants/policies).
-- ---------------------------------------------------------------------------
set local role anon;
do $$
declare t text;
begin
  foreach t in array array[
    'organizations', 'organization_members',
    'product_prices', 'billing_customers', 'subscriptions',
    'usage_quotas', 'usage_events', 'usage_idempotency',
    'service_tasks', 'task_applications', 'task_status_history', 'contact_consents',
    'payment_orders', 'refunds', 'payment_events',
    'internal_role_assignments', 'audit_events', 'collection_runs'
  ] loop
    begin
      execute format('select * from public.%I limit 1', t);
      raise exception 'anonymous selected from %', t;
    exception when insufficient_privilege then null; end;
  end loop;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- 2. U2 (authenticated, unrelated to ORG-411): own-scope reads only.
-- ---------------------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000402', true);
select set_config('request.jwt.claim.role', 'authenticated', true);

-- 2a. RLS filters other users'/other orgs' rows to zero (grants exist).
do $$
declare v integer;
begin
  select count(*) into v from public.organizations
   where id = '00000000-0000-0000-0000-000000000411';
  if v <> 0 then raise exception 'U2 saw an organization they do not belong to (%)', v; end if;

  select count(*) into v from public.organization_members
   where user_id = '00000000-0000-0000-0000-000000000401';
  if v <> 0 then raise exception 'U2 saw another user membership (%)', v; end if;

  select count(*) into v from public.subscriptions
   where id in ('00000000-0000-0000-0000-000000000451',
                '00000000-0000-0000-0000-000000000452');
  if v <> 0 then raise exception 'U2 saw foreign subscriptions (%)', v; end if;

  select count(*) into v from public.usage_quotas
   where id in ('00000000-0000-0000-0000-000000000461',
                '00000000-0000-0000-0000-000000000462');
  if v <> 0 then raise exception 'U2 saw foreign usage quotas (%)', v; end if;

  select count(*) into v from public.usage_events
   where id = '00000000-0000-0000-0000-000000000471';
  if v <> 0 then raise exception 'U2 saw a foreign usage event (%)', v; end if;

  select count(*) into v from public.service_tasks
   where id = '00000000-0000-0000-0000-000000000481';
  if v <> 0 then raise exception 'U2 saw someone else draft task (%)', v; end if;

  -- U2 is the creator of the open task, so the creator policy admits the
  -- application/history rows; the unrelated-draft rows above stay hidden.
  select count(*) into v from public.task_applications
   where id = '00000000-0000-0000-0000-000000000491';
  if v <> 1 then raise exception 'U2 creator could not read own task application (%)', v; end if;

  select count(*) into v from public.task_status_history
   where id = '00000000-0000-0000-0000-0000000004a1';
  if v <> 1 then raise exception 'U2 creator could not read own task history (%)', v; end if;

  -- Contact consent: U2 is the C party -> record visible, but the verified
  -- email columns are column-revoked from authenticated.
  select count(*) into v from public.contact_consents
   where task_id = '00000000-0000-0000-0000-000000000482';
  if v <> 1 then raise exception 'U2 (C party) could not read consent record (%)', v; end if;
end $$;

do $$
declare v integer;
begin
  begin
    select c_email_verified into v from public.contact_consents
     where task_id = '00000000-0000-0000-0000-000000000482';
    raise exception 'U2 read a revoked email column';
  exception when insufficient_privilege then null; end;
end $$;

-- Open listings are readable by any authenticated user; future-versioned
-- prices are not.
do $$
declare v integer;
begin
  select count(*) into v from public.service_tasks
   where id = '00000000-0000-0000-0000-000000000482';
  if v <> 1 then raise exception 'U2 could not read open task listing (%)', v; end if;

  select count(*) into v from public.product_prices
   where id = '00000000-0000-0000-0000-000000000431';
  if v <> 1 then raise exception 'U2 could not read effective price (%)', v; end if;

  select count(*) into v from public.product_prices
   where id = '00000000-0000-0000-0000-000000000432';
  if v <> 0 then raise exception 'U2 read a future-version price (%)', v; end if;
end $$;

-- 2b. No write grant exists for any V1 business table; the user_profiles
--     column fence keeps server-managed fields out of browser reach.
do $$
declare v integer;
begin
  -- organizations.name carries a column-level UPDATE grant, so a non-owner
  -- update succeeds at the privilege layer and RLS filters it to zero rows.
  update public.organizations set name = 'hijack'
   where id = '00000000-0000-0000-0000-000000000411';
  get diagnostics v = row_count;
  if v <> 0 then raise exception 'U2 updated an organization they do not own (%)', v; end if;

  begin insert into public.organization_members (organization_id, user_id, role, status)
    values ('00000000-0000-0000-0000-000000000411', '00000000-0000-0000-0000-000000000402', 'member', 'active');
    raise exception 'U2 inserted a membership'; exception when insufficient_privilege then null; end;
  begin update public.subscriptions set status = 'canceled' where id = '00000000-0000-0000-0000-000000000452';
    raise exception 'U2 updated a subscription'; exception when insufficient_privilege then null; end;
  begin insert into public.usage_quotas (scope_key, usage_kind, period_key, limit_units)
    values ('user:00000000-0000-0000-0000-000000000402', 'query', '2026-09', 10);
    raise exception 'U2 inserted a usage quota'; exception when insufficient_privilege then null; end;
  begin update public.usage_events set units = 99 where id = '00000000-0000-0000-0000-000000000471';
    raise exception 'U2 updated a usage event'; exception when insufficient_privilege then null; end;
  begin insert into public.service_tasks (creator_user_id, purpose, compensation, public_description)
    values ('00000000-0000-0000-0000-000000000402', 'x', 'paid', 'another task body');
    raise exception 'U2 inserted a service task'; exception when insufficient_privilege then null; end;
  begin update public.task_applications set status = 'matched' where id = '00000000-0000-0000-0000-000000000491';
    raise exception 'U2 updated a task application'; exception when insufficient_privilege then null; end;
  begin update public.contact_consents set c_status = 'granted' where task_id = '00000000-0000-0000-0000-000000000482';
    raise exception 'U2 updated a consent record'; exception when insufficient_privilege then null; end;
  begin insert into public.collection_runs (source_key, source_type)
    values ('fixture-key', 'authorized_csv');
    raise exception 'U2 inserted a collection run'; exception when insufficient_privilege then null; end;
  begin insert into public.payment_orders (order_no, product_code, price_version, currency, amount_minor, provider, organization_id)
    values ('fixture-order-x', 'b_data_pro_monthly', 1, 'JPY', 100, 'stripe',
            '00000000-0000-0000-0000-000000000411');
    raise exception 'U2 inserted a payment order'; exception when insufficient_privilege then null; end;

  -- user_profiles: preference columns stay writable on the own row; the
  -- server-managed columns (status/membership_tier/daily_query_limit) are
  -- fenced at the column-privilege layer and by the 00600 trigger.
  update public.user_profiles set bio = 'other preference write'
   where user_id = '00000000-0000-0000-0000-000000000402';
  get diagnostics v = row_count;
  if v <> 1 then raise exception 'U2 preference update affected % rows', v; end if;

  update public.user_profiles set bio = 'cross-user write'
   where user_id = '00000000-0000-0000-0000-000000000401';
  get diagnostics v = row_count;
  if v <> 0 then raise exception 'U2 cross-user profile update affected % rows', v; end if;

  begin update public.user_profiles set status = 'suspended'
    where user_id = '00000000-0000-0000-0000-000000000402';
    raise exception 'U2 changed own member status'; exception when insufficient_privilege then null; end;
  begin update public.user_profiles set membership_tier = 'c_plus'
    where user_id = '00000000-0000-0000-0000-000000000402';
    raise exception 'U2 changed own membership tier'; exception when insufficient_privilege then null; end;
end $$;

-- 2c. Internal-domain tables (finance/admin/audit/collection) expose no
--     table privilege to authenticated at all.
do $$
declare t text;
begin
  foreach t in array array[
    'billing_customers', 'usage_idempotency',
    'payment_orders', 'refunds', 'payment_events',
    'internal_role_assignments', 'audit_events', 'collection_runs'
  ] loop
    begin
      execute format('select * from public.%I limit 1', t);
      raise exception 'authenticated selected from internal table %', t;
    exception when insufficient_privilege then null; end;
  end loop;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- 3. U1 (authenticated, active owner of ORG-411 + personal subscription):
--    own-scope and membership-scope reads work; writes stay denied except
--    the org display name and own profile preferences.
-- ---------------------------------------------------------------------------
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000401', true);
select set_config('request.jwt.claim.role', 'authenticated', true);

do $$
declare v integer;
begin
  select count(*) into v from public.organizations
   where id = '00000000-0000-0000-0000-000000000411';
  if v <> 1 then raise exception 'owner could not read own organization (%)', v; end if;

  select count(*) into v from public.organization_members
   where user_id = '00000000-0000-0000-0000-000000000401';
  if v <> 1 then raise exception 'owner could not read own membership (%)', v; end if;

  select count(*) into v from public.subscriptions
   where id = '00000000-0000-0000-0000-000000000451';
  if v <> 1 then raise exception 'owner could not read own subscription (%)', v; end if;

  -- Active members read the org-shared B subscription and org usage rows.
  select count(*) into v from public.subscriptions
   where id = '00000000-0000-0000-0000-000000000452';
  if v <> 1 then raise exception 'active member could not read org subscription (%)', v; end if;

  select count(*) into v from public.usage_quotas
   where id = '00000000-0000-0000-0000-000000000461';
  if v <> 1 then raise exception 'owner could not read own usage quota (%)', v; end if;
  select count(*) into v from public.usage_quotas
   where id = '00000000-0000-0000-0000-000000000462';
  if v <> 1 then raise exception 'active member could not read org usage quota (%)', v; end if;
  select count(*) into v from public.usage_events
   where id = '00000000-0000-0000-0000-000000000471';
  if v <> 1 then raise exception 'owner could not read own usage event (%)', v; end if;

  -- Creator reads own draft; open listing stays readable; the org member
  -- reads the ORG application but not the status history of a task the ORG
  -- does not (yet) hold a match on.
  select count(*) into v from public.service_tasks
   where id = '00000000-0000-0000-0000-000000000481';
  if v <> 1 then raise exception 'creator could not read own draft task (%)', v; end if;
  select count(*) into v from public.service_tasks
   where id = '00000000-0000-0000-0000-000000000482';
  if v <> 1 then raise exception 'owner could not read open listing (%)', v; end if;
  select count(*) into v from public.task_applications
   where id = '00000000-0000-0000-0000-000000000491';
  if v <> 1 then raise exception 'org member could not read own application (%)', v; end if;
  select count(*) into v from public.task_status_history
   where id = '00000000-0000-0000-0000-0000000004a1';
  if v <> 0 then raise exception 'non-participant read matched-only history (%)', v; end if;

  -- Consent record: B-side owner reads it, but never through the email
  -- columns (checked below at column level).
  select count(*) into v from public.contact_consents
   where task_id = '00000000-0000-0000-0000-000000000482';
  if v <> 1 then raise exception 'B owner could not read consent record (%)', v; end if;
end $$;

do $$
declare v integer;
begin
  select count(*) into v from public.contact_consents
   where task_id = '00000000-0000-0000-0000-000000000482'
     and c_email_verified is not null;
  raise exception 'owner read a revoked email column';
exception when insufficient_privilege then null;
end $$;

do $$
declare v integer; t text;
begin
  -- Active owner updates the org display name (column grant + RLS policy).
  update public.organizations set name = 'owner renamed'
   where id = '00000000-0000-0000-0000-000000000411';
  get diagnostics v = row_count;
  if v <> 1 then raise exception 'owner rename affected % rows', v; end if;

  -- Server-managed org columns are not browser-writable.
  begin update public.organizations set partner_status = 'certified'
    where id = '00000000-0000-0000-0000-000000000411';
    raise exception 'owner wrote partner_status'; exception when insufficient_privilege then null; end;
  begin update public.organization_members set status = 'inactive'
    where user_id = '00000000-0000-0000-0000-000000000401';
    raise exception 'owner wrote membership status'; exception when insufficient_privilege then null; end;
  begin insert into public.organizations (name) values ('second org');
    raise exception 'authenticated inserted an organization'; exception when insufficient_privilege then null; end;
  begin update public.subscriptions set status = 'canceled'
    where id = '00000000-0000-0000-0000-000000000451';
    raise exception 'owner wrote subscription status'; exception when insufficient_privilege then null; end;
  begin insert into public.usage_events (scope_key, usage_kind, operation, units, period_key)
    values ('user:00000000-0000-0000-0000-000000000401', 'query', 'consume', 1, '2026-09');
    raise exception 'owner inserted a usage event'; exception when insufficient_privilege then null; end;

  -- Internal-domain tables stay closed to every authenticated role.
  foreach t in array array[
    'payment_orders', 'refunds', 'payment_events',
    'internal_role_assignments', 'audit_events', 'collection_runs'
  ] loop
    begin
      execute format('select * from public.%I limit 1', t);
      raise exception 'owner selected internal table %', t;
    exception when insufficient_privilege then null; end;
  end loop;
end $$;
reset role;

-- ---------------------------------------------------------------------------
-- 4. service_role worker: full table access; append-only triggers still
--    reject UPDATE/DELETE on the event ledgers.
-- ---------------------------------------------------------------------------
set local role service_role;

do $$
declare v integer;
begin
  -- Worker writes flow (representative, not exhaustive).
  insert into public.organizations (id, name) values
    ('00000000-0000-0000-0000-0000000004c1', 'worker org');
  insert into public.organization_members (organization_id, user_id, role, status) values
    ('00000000-0000-0000-0000-0000000004c1',
     '00000000-0000-0000-0000-000000000402', 'owner', 'active');
  insert into public.audit_events (actor_user_id, action, target_type, summary) values
    ('00000000-0000-0000-0000-000000000401', 'test.worker.write', 'fixture', '{}'::jsonb);
  insert into public.collection_runs (source_key, source_type, status, rows_collected) values
    ('fixture-key', 'authorized_csv', 'succeeded', 3);
  insert into public.usage_events (
    id, scope_key, usage_kind, operation, units, period_key, actor_user_id
  ) values (
    '00000000-0000-0000-0000-0000000004d1',
    'user:00000000-0000-0000-0000-000000000402', 'query', 'consume', 1, '2026-09',
    '00000000-0000-0000-0000-000000000402'
  );
  insert into public.payment_orders (
    order_no, owner_user_id, product_code, price_version, currency, amount_minor, provider
  ) values (
    'fixture-worker-order', '00000000-0000-0000-0000-000000000402',
    'risk_report_single', 1, 'JPY', 5000, 'stripe'
  );

  -- Member status flip is a back-office (service) write: column fence and
  -- the 00600 trigger both let service_role through.
  update public.user_profiles set status = 'suspended'
   where user_id = '00000000-0000-0000-0000-000000000402';
  get diagnostics v = row_count;
  if v <> 1 then raise exception 'worker status flip affected % rows', v; end if;
  update public.user_profiles set status = 'active'
   where user_id = '00000000-0000-0000-0000-000000000402';
end $$;

do $$
declare v integer;
begin
  begin
    update public.usage_events set units = 999
     where id = '00000000-0000-0000-0000-0000000004d1';
    raise exception 'worker updated an append-only usage event';
  exception when raise_exception then null; end;

  begin
    delete from public.usage_events
     where id = '00000000-0000-0000-0000-0000000004d1';
    raise exception 'worker deleted an append-only usage event';
  exception when raise_exception then null; end;

  begin
    update public.audit_events set action = 'rewritten'
     where action = 'test.worker.write';
    raise exception 'worker updated an append-only audit row';
  exception when raise_exception then null; end;

  begin
    delete from public.audit_events where action = 'test.worker.write';
    raise exception 'worker deleted an append-only audit row';
  exception when raise_exception then null; end;
end $$;
reset role;

rollback;
