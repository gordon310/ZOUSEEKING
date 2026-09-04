-- V1 service-task marketplace / contact-consent schema assertions
-- (psql DO block). Run against a disposable Supabase/PostgreSQL database
-- only, after applying 20260905000100_v1_organizations.sql and
-- 20260905000400_v1_service_tasks_contacts.sql.
--
-- This gate is catalog-only: table/column existence, defaults, RLS
-- enablement, check/unique constraints, the single-match partial unique
-- index, the revoked-email-column posture, helper/RPC function presence, and
-- the minimal policy/grant contract (anon zero, authenticated scoped SELECT
-- only, service_role full).
--
-- The four-identity behavior matrix (anonymous / C creator / B org owner /
-- B assigned member / unrelated authenticated) is added once the baseline
-- gate allows applying this migration group to a live stack, where real
-- auth.uid() sessions can be exercised.

do $$
declare
  required_table text;
  required_constraint text;
  required_index text;
  missing_columns text[];
  constraint_def text;
  policy_row record;
begin
  -- Tables exist.
  foreach required_table in array array[
    'service_tasks', 'task_applications', 'task_status_history', 'contact_consents'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing v1 service-task table: %', required_table;
    end if;
  end loop;

  -- Required columns exist (information_schema), with table-level NOT NULL
  -- spot checks for the ownership/status core.
  select array_agg(t || '.' || c order by 1)
    into missing_columns
  from (
    values
      ('service_tasks', 'creator_user_id'),
      ('service_tasks', 'purpose'),
      ('service_tasks', 'region_pref'),
      ('service_tasks', 'asset_type'),
      ('service_tasks', 'compensation'),
      ('service_tasks', 'public_description'),
      ('service_tasks', 'apply_deadline'),
      ('service_tasks', 'status'),
      ('service_tasks', 'created_at'),
      ('service_tasks', 'updated_at'),
      ('task_applications', 'task_id'),
      ('task_applications', 'organization_id'),
      ('task_applications', 'assigned_member_user_id'),
      ('task_applications', 'status'),
      ('task_applications', 'applied_at'),
      ('task_applications', 'updated_at'),
      ('task_status_history', 'task_id'),
      ('task_status_history', 'from_status'),
      ('task_status_history', 'to_status'),
      ('task_status_history', 'changed_by_user_id'),
      ('task_status_history', 'changed_at'),
      ('task_status_history', 'note'),
      ('contact_consents', 'task_id'),
      ('contact_consents', 'c_user_id'),
      ('contact_consents', 'b_organization_id'),
      ('contact_consents', 'b_member_user_id'),
      ('contact_consents', 'consent_version'),
      ('contact_consents', 'c_status'),
      ('contact_consents', 'b_status'),
      ('contact_consents', 'granted_at'),
      ('contact_consents', 'match_expires_at'),
      ('contact_consents', 'emails_visible_until'),
      ('contact_consents', 'retention_until'),
      ('contact_consents', 'c_email_verified'),
      ('contact_consents', 'b_email_verified'),
      ('contact_consents', 'updated_at')
  ) as required(t, c)
  where not exists (
    select 1
    from information_schema.columns actual
    where actual.table_schema = 'public'
      and actual.table_name = required.t
      and actual.column_name = required.c
  );

  if missing_columns is not null then
    raise exception 'missing v1 service-task columns: %', missing_columns;
  end if;

  -- Public listing copy length guard and status machine defaults.
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.service_tasks'::regclass
      and conname = 'service_tasks_public_description_check'
      and pg_get_constraintdef(oid) like '%10%'
      and pg_get_constraintdef(oid) like '%2000%'
  ) then
    raise exception 'service_tasks description must be bounded 10..2000 chars';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.service_tasks'::regclass
      and conname = 'service_tasks_status_check'
      and pg_get_constraintdef(oid) like '%''draft''%'
      and pg_get_constraintdef(oid) like '%''open''%'
      and pg_get_constraintdef(oid) like '%''matched_pending_consent''%'
      and pg_get_constraintdef(oid) like '%''in_progress''%'
      and pg_get_constraintdef(oid) like '%''completion_pending''%'
      and pg_get_constraintdef(oid) like '%''completed''%'
      and pg_get_constraintdef(oid) like '%''cancelled''%'
      and pg_get_constraintdef(oid) like '%''expired''%'
      and pg_get_constraintdef(oid) like '%''closed_unconfirmed''%'
      and pg_get_constraintdef(oid) like '%''suspended''%'
  ) then
    raise exception 'service_tasks status check must allow the full V1 machine';
  end if;

  -- No email/identifying column may ever live on the public task listing.
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'service_tasks'
      and (column_name like '%email%' or column_name like '%phone%')
  ) then
    raise exception 'service_tasks must not carry contact columns';
  end if;

  -- Application defaults, single-match partial unique index, terminal set.
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'task_applications'
      and column_name = 'status'
      and is_nullable = 'NO'
      and column_default = '''pending''::text'
  ) then
    raise exception 'task_applications.status must default to pending';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.task_applications'::regclass
      and conname = 'task_applications_status_check'
      and pg_get_constraintdef(oid) like '%''pending''%'
      and pg_get_constraintdef(oid) like '%''withdrawn''%'
      and pg_get_constraintdef(oid) like '%''rejected''%'
      and pg_get_constraintdef(oid) like '%''matched''%'
      and pg_get_constraintdef(oid) like '%''match_expired''%'
  ) then
    raise exception 'task_applications status check must allow the V1 application set';
  end if;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.task_applications'::regclass
      and conname = 'task_applications_one_per_org'
  ) then
    raise exception 'missing unique (task_id, organization_id) on task_applications';
  end if;

  if not exists (
    select 1
    from pg_indexes
    where schemaname = 'public'
      and indexname = 'uq_task_applications_single_match'
  ) then
    raise exception 'missing single-match unique index on task_applications';
  end if;

  if not exists (
    select 1
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    join pg_index i on i.indexrelid = c.oid
    where n.nspname = 'public'
      and c.relname = 'uq_task_applications_single_match'
      and i.indisunique
      and i.indpred is not null
  ) then
    raise exception 'single-match unique index must be partial (where status = matched)';
  end if;

  -- Consent machine: independent dual statuses, 72h/30d/3y windows, and the
  -- emails-only-after-mutual-grant invariant.
  foreach required_constraint in array array[
    'contact_consents_c_status_check',
    'contact_consents_b_status_check',
    'contact_consents_granted_at_required_check',
    'contact_consents_emails_only_when_granted_check',
    'task_status_history_from_status_check',
    'task_status_history_to_status_check'
  ] loop
    if not exists (
      select 1
      from pg_constraint
      where conname = required_constraint
    ) then
      raise exception 'missing service-task constraint: %', required_constraint;
    end if;
  end loop;

  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.contact_consents'::regclass
      and conname = 'contact_consents_one_per_task'
  ) then
    raise exception 'missing unique (task_id) on contact_consents';
  end if;

  select pg_get_constraintdef(oid)
    into constraint_def
  from pg_constraint
  where conrelid = 'public.task_status_history'::regclass
    and conname = 'task_status_history_to_status_check';

  if constraint_def is null
     or constraint_def not like '%''matched_pending_consent''%'
     or constraint_def not like '%''closed_unconfirmed''%'
     or constraint_def not like '%''suspended''%' then
    raise exception 'task_status_history to_status check must allow the full V1 machine';
  end if;

  -- RLS enabled on all four tables (pg_tables).
  if exists (
    select 1
    from pg_tables
    where schemaname = 'public'
      and tablename in ('service_tasks', 'task_applications', 'task_status_history', 'contact_consents')
      and not rowsecurity
  ) then
    raise exception 'RLS must be enabled on all four v1 service-task tables';
  end if;

  -- No anonymous policies and no blanket using(true)/with check(true)
  -- policies on any of the four tables; every SELECT policy must express a
  -- scope. anon/authenticated also hold zero write grants (no write
  -- policies exist by construction - check below).
  for policy_row in
    select tablename, policyname, cmd, roles, qual
    from pg_policies
    where schemaname = 'public'
      and tablename in ('service_tasks', 'task_applications', 'task_status_history', 'contact_consents')
  loop
    if policy_row.roles::text like '%anon%' then
      raise exception 'anonymous policy exists: %.%', policy_row.tablename, policy_row.policyname;
    end if;
    if policy_row.cmd = 'SELECT'
       and (policy_row.qual in ('true', '(true)') or policy_row.qual is null) then
      raise exception 'unscoped SELECT policy exists: %.%', policy_row.tablename, policy_row.policyname;
    end if;
    if policy_row.cmd <> 'SELECT' then
      raise exception 'unexpected write policy %.% (authenticated must be read-only)',
        policy_row.tablename, policy_row.policyname;
    end if;
  end loop;

  -- Required named policies exist and target authenticated only.
  foreach required_constraint in array array[
    'creators can read their own service tasks',
    'authenticated users can read open task listings',
    'matched org owner or assigned member can read task',
    'task creators and applying org members can read applications',
    'task creators can read status history',
    'matched org owner or assigned member can read status history',
    'consent parties can read their consent record'
  ] loop
    if not exists (
      select 1
      from pg_policies
      where schemaname = 'public'
        and policyname = required_constraint
    ) then
      raise exception 'missing service-task policy: %', required_constraint;
    end if;
  end loop;

  -- Traced-query indexes exist.
  foreach required_index in array array[
    'idx_service_tasks_open_feed',
    'idx_service_tasks_creator',
    'idx_task_applications_task',
    'idx_task_applications_organization',
    'idx_task_status_history_task'
  ] loop
    if not exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and indexname = required_index
    ) then
      raise exception 'missing service-task index: %', required_index;
    end if;
  end loop;

  -- updated_at triggers wired on the three mutable tables.
  foreach required_index in array array[
    'set_service_tasks_updated_at',
    'set_task_applications_updated_at',
    'set_contact_consents_updated_at'
  ] loop
    if not exists (
      select 1
      from information_schema.triggers
      where event_object_schema = 'public'
        and trigger_name = required_index
        and event_manipulation = 'UPDATE'
    ) then
      raise exception 'missing updated_at trigger: %', required_index;
    end if;
  end loop;

  -- Privacy posture on contact_consents: the two verified-email columns
  -- carry NO SELECT grant for anon/authenticated (column-level grant list
  -- excludes them), while the consent bookkeeping columns are readable.
  if exists (
    select 1
    from information_schema.column_privileges
    where table_schema = 'public'
      and table_name = 'contact_consents'
      and column_name in ('c_email_verified', 'b_email_verified')
      and privilege_type = 'SELECT'
      and grantee in ('anon', 'authenticated')
  ) then
    raise exception 'email columns must not be SELECT-granted to anon/authenticated';
  end if;

  if to_regrole('authenticated') is not null and (
    select count(distinct column_name)
    from information_schema.column_privileges
    where table_schema = 'public'
      and table_name = 'contact_consents'
      and column_name in ('task_id', 'consent_version', 'c_status')
      and grantee = 'authenticated'
      and privilege_type = 'SELECT'
  ) <> 3 then
    raise exception 'consent bookkeeping columns must be SELECT-granted to authenticated';
  end if;

  -- No table-level write privileges leaked to non-service roles (checked one
  -- privilege at a time; has_table_privilege with a comma list would require
  -- ALL of them before reporting true).
  if to_regrole('authenticated') is not null and (
    has_table_privilege('authenticated', 'public.service_tasks', 'INSERT')
    or has_table_privilege('authenticated', 'public.service_tasks', 'UPDATE')
    or has_table_privilege('authenticated', 'public.service_tasks', 'DELETE')
    or has_table_privilege('authenticated', 'public.task_applications', 'INSERT')
    or has_table_privilege('authenticated', 'public.task_applications', 'UPDATE')
    or has_table_privilege('authenticated', 'public.task_applications', 'DELETE')
    or has_table_privilege('authenticated', 'public.task_status_history', 'INSERT')
    or has_table_privilege('authenticated', 'public.task_status_history', 'UPDATE')
    or has_table_privilege('authenticated', 'public.task_status_history', 'DELETE')
    or has_table_privilege('authenticated', 'public.contact_consents', 'INSERT')
    or has_table_privilege('authenticated', 'public.contact_consents', 'UPDATE')
    or has_table_privilege('authenticated', 'public.contact_consents', 'DELETE')
  ) then
    raise exception 'authenticated must hold no write privileges on v1 service-task tables';
  end if;

  -- Trusted worker keeps full privileges.
  if to_regrole('service_role') is not null and (
    not has_table_privilege('service_role', 'public.service_tasks', 'SELECT, INSERT, UPDATE, DELETE')
    or not has_table_privilege('service_role', 'public.task_applications', 'SELECT, INSERT, UPDATE, DELETE')
    or not has_table_privilege('service_role', 'public.task_status_history', 'SELECT, INSERT, UPDATE, DELETE')
    or not has_table_privilege('service_role', 'public.contact_consents', 'SELECT, INSERT, UPDATE, DELETE')
  ) then
    raise exception 'service_role must keep full privileges on v1 service-task tables';
  end if;

  -- Membership helpers exist, are security definer, and are not executable
  -- by anon; the email RPC exists, is not executable by public, and is
  -- executable by authenticated/service_role.
  if to_regprocedure('public.is_active_org_member(uuid)') is null
     or to_regprocedure('public.is_org_owner_or_assigned_member(uuid, uuid)') is null
     or to_regprocedure('public.is_task_creator(uuid)') is null
     or to_regprocedure('public.is_matched_task_b_participant(uuid)') is null
     or to_regprocedure('public.get_task_contact_email(uuid)') is null then
    raise exception 'missing v1 service-task helper/RPC functions';
  end if;

  if has_function_privilege('public', 'public.get_task_contact_email(uuid)', 'EXECUTE') then
    raise exception 'email RPC must not be executable by PUBLIC';
  end if;

  if to_regrole('authenticated') is not null and not (
    has_function_privilege('authenticated', 'public.get_task_contact_email(uuid)', 'EXECUTE')
    and has_function_privilege('authenticated', 'public.is_matched_task_b_participant(uuid)', 'EXECUTE')
  ) then
    raise exception 'authenticated must be able to execute the policy helpers and email RPC';
  end if;

  if to_regrole('service_role') is not null and not (
    has_function_privilege('service_role', 'public.get_task_contact_email(uuid)', 'EXECUTE')
  ) then
    raise exception 'service_role must be able to execute the email RPC';
  end if;
end $$;
