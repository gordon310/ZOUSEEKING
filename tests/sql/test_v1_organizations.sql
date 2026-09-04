-- V1 organizations schema assertions (psql DO block).
-- Run against a disposable Supabase/PostgreSQL database only.
-- This gate is catalog-only: tables, columns, defaults, RLS enablement,
-- check/unique/foreign-key constraints, the 5-seat trigger and its function,
-- the single-active-owner partial unique index, and the minimal policy/grant
-- contract (anon zero, authenticated read own scope + owner name column
-- update, service_role full write).
-- The four-identity behavior matrix (anonymous / org owner / other
-- authenticated user / service_role worker) is added once the baseline gate
-- allows applying this migration group to a live stack.

do $$
declare
  missing_columns text[];
  active_owner_index boolean;
begin
  -- Tables exist.
  if to_regclass('public.organizations') is null
     or to_regclass('public.organization_members') is null then
    raise exception 'missing v1 organization tables';
  end if;

  -- Required columns exist (information_schema).
  select array_agg(t || '.' || c order by 1)
    into missing_columns
  from (
    values
      ('organizations', 'id'),
      ('organizations', 'name'),
      ('organizations', 'partner_status'),
      ('organizations', 'created_by_user_id'),
      ('organizations', 'created_at'),
      ('organizations', 'updated_at'),
      ('organization_members', 'id'),
      ('organization_members', 'organization_id'),
      ('organization_members', 'user_id'),
      ('organization_members', 'role'),
      ('organization_members', 'status'),
      ('organization_members', 'created_at'),
      ('organization_members', 'updated_at')
  ) as required(t, c)
  where not exists (
    select 1
    from information_schema.columns actual
    where actual.table_schema = 'public'
      and actual.table_name = required.t
      and actual.column_name = required.c
  );

  if missing_columns is not null then
    raise exception 'missing v1 organization columns: %', missing_columns;
  end if;

  -- Non-null / server-managed defaults.
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organizations'
      and column_name = 'name'
      and is_nullable = 'NO'
  ) then
    raise exception 'organizations.name must be NOT NULL';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organizations'
      and column_name = 'partner_status'
      and is_nullable = 'NO'
      and column_default = '''none''::text'
  ) then
    raise exception 'organizations.partner_status must be NOT NULL default none';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organization_members'
      and column_name = 'role'
      and is_nullable = 'NO'
  ) then
    raise exception 'organization_members.role must be NOT NULL';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organization_members'
      and column_name = 'status'
      and is_nullable = 'NO'
      and column_default = '''active''::text'
  ) then
    raise exception 'organization_members.status must be NOT NULL default active';
  end if;

  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organization_members'
      and column_name = 'organization_id'
      and is_nullable = 'NO'
  ) or not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organization_members'
      and column_name = 'user_id'
      and is_nullable = 'NO'
  ) then
    raise exception 'organization_members FKs must be NOT NULL';
  end if;

  -- RLS enabled on both tables (pg_tables).
  if exists (
    select 1
    from pg_tables
    where schemaname = 'public'
      and tablename in ('organizations', 'organization_members')
      and not rowsecurity
  ) then
    raise exception 'RLS must be enabled on both v1 organization tables';
  end if;

  -- CHECK constraints (pg_get_constraintdef).
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organizations'::regclass
      and conname = 'organizations_partner_status_check'
      and pg_get_constraintdef(oid) like '%''none''%'
      and pg_get_constraintdef(oid) like '%''pending''%'
      and pg_get_constraintdef(oid) like '%''certified''%'
      and pg_get_constraintdef(oid) like '%''suspended''%'
  ) then
    raise exception 'organizations partner_status check must allow none/pending/certified/suspended';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organizations'::regclass
      and conname = 'organizations_name_length_check'
      and pg_get_constraintdef(oid) like '%120%'
  ) then
    raise exception 'organizations name length check is missing';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organization_members'::regclass
      and conname = 'organization_members_role_allowed'
      and pg_get_constraintdef(oid) like '%''owner''%'
      and pg_get_constraintdef(oid) like '%''member''%'
  ) then
    raise exception 'organization_members role check must allow owner/member';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organization_members'::regclass
      and conname = 'organization_members_status_allowed'
      and pg_get_constraintdef(oid) like '%''active''%'
      and pg_get_constraintdef(oid) like '%''inactive''%'
  ) then
    raise exception 'organization_members status check must allow active/inactive';
  end if;

  -- Unique membership pair (organization_id, user_id).
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organization_members'::regclass
      and conname = 'organization_members_unique_membership'
      and contype = 'u'
      and pg_get_constraintdef(oid) like '%(organization_id, user_id)%'
  ) then
    raise exception 'organization_members unique (organization_id, user_id) is missing';
  end if;

  -- Foreign keys: member -> organization and member/user -> auth.users cascade;
  -- organization.created_by_user_id is provenance (SET NULL, no cascade).
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organization_members'::regclass
      and conname = 'organization_members_organization_id_fkey'
      and contype = 'f'
      and confrelid = 'public.organizations'::regclass
      and confdeltype = 'c'
  ) then
    raise exception 'organization_members -> organizations cascade FK is missing';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organization_members'::regclass
      and conname = 'organization_members_user_id_fkey'
      and contype = 'f'
      and confrelid = 'auth.users'::regclass
      and confdeltype = 'c'
  ) then
    raise exception 'organization_members.user_id -> auth.users cascade FK is missing';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.organizations'::regclass
      and conname = 'organizations_created_by_user_id_fkey'
      and contype = 'f'
      and confrelid = 'auth.users'::regclass
      and confdeltype = 'n'
  ) then
    raise exception 'organizations.created_by_user_id must be SET NULL on user delete';
  end if;

  -- Single active owner: partial unique index (role=owner, status=active).
  select exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and tablename = 'organization_members'
      and indexname = 'uq_organization_members_active_owner'
      and indexdef ilike '%unique%'
      and indexdef ilike '%where%'
      and indexdef like '%(organization_id)%'
  )
  into active_owner_index;

  if not active_owner_index then
    raise exception 'single-active-owner partial unique index is missing';
  end if;

  -- 5-seat trigger, its SECURITY DEFINER function, and updated_at triggers.
  if to_regprocedure('public.enforce_organization_member_active_seat_cap()') is null then
    raise exception 'seat-cap function is missing';
  end if;

  if not exists (
    select 1
    from pg_trigger
    where tgrelid = 'public.organization_members'::regclass
      and tgname = 'enforce_organization_member_active_seat_cap'
      and not tgisinternal
  ) then
    raise exception 'seat-cap trigger is missing on organization_members';
  end if;

  if not exists (
    select 1
    from pg_trigger
    where tgrelid = 'public.organizations'::regclass
      and tgname = 'set_organizations_updated_at'
      and not tgisinternal
  ) then
    raise exception 'updated_at trigger is missing on organizations';
  end if;

  if not exists (
    select 1
    from pg_trigger
    where tgrelid = 'public.organization_members'::regclass
      and tgname = 'set_organization_members_updated_at'
      and not tgisinternal
  ) then
    raise exception 'updated_at trigger is missing on organization_members';
  end if;

  -- Policy contract: anon zero; authenticated read own scope; no
  -- INSERT/UPDATE/DELETE/ALL policy on organization_members (writes are
  -- service_role only); organizations has one owner-scoped UPDATE policy.
  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename in ('organizations', 'organization_members')
      and roles::text like '%anon%'
  ) then
    raise exception 'anonymous policies exist on v1 organization tables';
  end if;

  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'organizations'
      and policyname = 'members can read organizations they belong to'
      and cmd = 'SELECT'
      and roles = array['authenticated']::name[]
  ) then
    raise exception 'organizations self-scope SELECT policy is missing';
  end if;

  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'organizations'
      and policyname = 'active owners can update their organization profile'
      and cmd = 'UPDATE'
      and roles = array['authenticated']::name[]
  ) then
    raise exception 'organizations owner-scoped UPDATE policy is missing';
  end if;

  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'organization_members'
      and policyname = 'members can read their own memberships'
      and cmd = 'SELECT'
      and roles = array['authenticated']::name[]
  ) then
    raise exception 'organization_members self-scope SELECT policy is missing';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'organization_members'
      and cmd in ('INSERT', 'UPDATE', 'DELETE', 'ALL')
  ) then
    raise exception 'organization_members must expose no write policy (service_role only)';
  end if;

  if exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'organizations'
      and cmd in ('INSERT', 'DELETE', 'ALL')
  ) then
    raise exception 'organizations must expose no INSERT/DELETE/ALL policy';
  end if;

  -- Grants: anon zero; authenticated SELECT on both plus column-scoped
  -- UPDATE on organizations.name only; service_role full write.
  if exists (
    select 1
    from information_schema.role_table_grants
    where grantee = 'anon'
      and table_schema = 'public'
      and table_name in ('organizations', 'organization_members')
  ) then
    raise exception 'anon must hold zero grants on v1 organization tables';
  end if;

  if not exists (
    select 1
    from information_schema.role_table_grants
    where grantee = 'authenticated'
      and table_schema = 'public'
      and table_name = 'organizations'
      and privilege_type = 'SELECT'
  ) or not exists (
    select 1
    from information_schema.role_table_grants
    where grantee = 'authenticated'
      and table_schema = 'public'
      and table_name = 'organization_members'
      and privilege_type = 'SELECT'
  ) then
    raise exception 'authenticated must hold SELECT on both v1 organization tables';
  end if;

  if exists (
    select 1
    from information_schema.role_table_grants
    where grantee = 'authenticated'
      and table_schema = 'public'
      and table_name = 'organization_members'
      and privilege_type in ('INSERT', 'UPDATE', 'DELETE')
  ) then
    raise exception 'authenticated must not write organization_members';
  end if;

  if not exists (
    select 1
    from information_schema.role_column_grants
    where grantee = 'authenticated'
      and table_schema = 'public'
      and table_name = 'organizations'
      and column_name = 'name'
      and privilege_type = 'UPDATE'
  ) then
    raise exception 'authenticated must hold UPDATE only on organizations.name';
  end if;

  if exists (
    select 1
    from information_schema.role_column_grants
    where grantee = 'authenticated'
      and table_schema = 'public'
      and table_name = 'organizations'
      and column_name <> 'name'
      and privilege_type = 'UPDATE'
  ) then
    raise exception 'authenticated column UPDATE must be restricted to organizations.name';
  end if;

  if not exists (
    select 1
    from information_schema.role_table_grants
    where grantee = 'service_role'
      and table_schema = 'public'
      and table_name = 'organizations'
      and privilege_type = 'INSERT'
  ) or not exists (
    select 1
    from information_schema.role_table_grants
    where grantee = 'service_role'
      and table_schema = 'public'
      and table_name = 'organization_members'
      and privilege_type = 'INSERT'
  ) then
    raise exception 'service_role must hold full write grants on v1 organization tables';
  end if;

  -- Migration ledger entry exists (applied through the Supabase CLI).
  if not exists (
    select 1
    from supabase_migrations.schema_migrations
    where version = '20260905000100'
  ) then
    raise exception 'missing v1 organizations migration ledger entry';
  end if;
end
$$;
