-- V1 service-task marketplace and contact-consent domain (20260905000400).
--
-- Four tables:
--   public.service_tasks        C-side public service-request listings.
--   public.task_applications    B-organization applications, each naming one
--                               responsible member; single-match guarantee.
--   public.task_status_history  Append-only transition log for every task.
--   public.contact_consents     One row per task match. Holds the consent
--                               state machine and, ONLY after mutual grant,
--                               the verified counterparty email addresses.
--
-- State machine (frozen by the V1 contract, enforced at CHECK level and
-- stepped only by the trusted backend):
--   draft -> open -> matched_pending_consent -> in_progress ->
--   completion_pending -> completed
--   plus the exception leaves: cancelled (creator before match), expired
--   (deadline reached with no match), closed_unconfirmed (completion
--   request unconfirmed by C for 7 days), suspended (policy violation).
--   'completed' is NEVER settable by a client: it is driven server-side
--   only after the C user confirms completion (no automatic completion).
--   Every transition is recorded in public.task_status_history.
--
-- Privacy/authorization contract (per AGENTS.md: frontend hiding is not an
-- access control; contact information is least-visible):
--   * service_tasks stores public listing content ONLY. No name, email,
--     phone, ID, exact address, contract, or attachment column may ever be
--     added here.
--   * Verified email addresses live exclusively in public.contact_consents,
--     are NULL until both sides grant, and are NOT readable through table
--     SELECT by anon or authenticated (column-level privileges revoked).
--     The sole client channel is public.get_task_contact_email(), a
--     SECURITY DEFINER check that re-verifies party identity, mutual grant,
--     and the 30-day display window before returning the counterparty email.
--   * All four tables are RLS-protected, anon holds zero privileges,
--     authenticated holds SELECT only (rows scoped by policy), and every
--     write - task lifecycle, applications, consent transitions, email
--     population/clearing - is performed by the trusted backend under
--     service_role. No authenticated INSERT/UPDATE policies exist.

do $$
begin
  if to_regclass('auth.users') is null then
    raise exception 'missing prerequisite table: auth.users';
  end if;
  if to_regclass('public.organizations') is null then
    raise exception 'missing prerequisite table: public.organizations (20260905000100)';
  end if;
  if to_regclass('public.organization_members') is null then
    raise exception 'missing prerequisite table: public.organization_members (20260905000100)';
  end if;
  if to_regprocedure('public.set_updated_at()') is null then
    raise exception 'missing prerequisite function: public.set_updated_at()';
  end if;
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'organization_members'
      and column_name in ('organization_id', 'user_id', 'role', 'status')
    group by table_schema, table_name
    having count(*) = 4
  ) then
    raise exception 'incompatible prerequisite columns: public.organization_members';
  end if;
end $$;

-- Guard against re-running this forward migration over live data (same
-- convention as 20260905000100_v1_organizations.sql).
do $$
declare
  required_table text;
begin
  foreach required_table in array array[
    'public.service_tasks', 'public.task_applications',
    'public.task_status_history', 'public.contact_consents'
  ] loop
    if to_regclass(required_table) is not null then
      raise exception 'v1 service-task migration already applied: %', required_table;
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- public.service_tasks
-- ---------------------------------------------------------------------------
create table if not exists public.service_tasks (
  id uuid primary key default gen_random_uuid(),
  creator_user_id uuid not null references auth.users(id),
  purpose text not null,
  region_pref text,
  -- Kept aligned with the asset_type value set already used by
  -- public.analysis_sessions so downstream filtering stays consistent.
  asset_type text,
  compensation text not null,
  -- Public listing copy: strict length bounds force real, non-empty copy and
  -- keep listing payloads bounded; char_length is byte-independent.
  public_description text not null,
  apply_deadline timestamptz,
  status text not null default 'draft',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint service_tasks_asset_type_check check (
    asset_type is null or asset_type in ('apartment', 'tower', 'detached_house', 'other')
  ),
  constraint service_tasks_compensation_check check (
    compensation in ('paid', 'unpaid', 'negotiable')
  ),
  constraint service_tasks_public_description_check check (
    char_length(public_description) between 10 and 2000
  ),
  -- Full V1 status machine; transitions are stepped by the trusted backend
  -- and logged in task_status_history. 'completed' is reachable only after
  -- the C user confirms completion server-side; no client can write it
  -- because authenticated holds no UPDATE grant on this table.
  constraint service_tasks_status_check check (
    status in (
      'draft', 'open', 'matched_pending_consent', 'in_progress',
      'completion_pending', 'completed', 'cancelled', 'expired',
      'closed_unconfirmed', 'suspended'
    )
  )
);

comment on table public.service_tasks is
  'C-side service request listing. Public listing fields only; contact or
   identifying columns are forbidden here by the V1 privacy contract and live
   exclusively in public.contact_consents once a match is authorized.';

-- Traced queries: open marketplace feed (status + recency) and the C-side
-- "my tasks" dashboard (creator + recency).
create index if not exists idx_service_tasks_open_feed
  on public.service_tasks(status, created_at desc)
  where status = 'open';
create index if not exists idx_service_tasks_creator
  on public.service_tasks(creator_user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- public.task_applications
-- ---------------------------------------------------------------------------
create table if not exists public.task_applications (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.service_tasks(id) on delete cascade,
  organization_id uuid not null references public.organizations(id),
  assigned_member_user_id uuid not null references auth.users(id),
  status text not null default 'pending',
  applied_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint task_applications_status_check check (
    status in ('pending', 'withdrawn', 'rejected', 'matched', 'match_expired')
  ),
  -- One application per organization per task. A new application after a
  -- terminal outcome (withdrawn/rejected/match_expired) requires an explicit
  -- backend decision; history is never silently rewritten.
  constraint task_applications_one_per_org unique (task_id, organization_id)
);

comment on table public.task_applications is
  'B-side application for a task. The application belongs to the applying
   organization and always names one responsible member. The trusted backend
   validates that the assigned member is an active member of the
   organization and that applications are only accepted while the task is
   open. B may withdraw before acceptance; C may cancel before matching.
   Withdrawn/rejected/match_expired are terminal application states.';

-- Single-match guarantee: at most one application per task may ever be
-- 'matched' (a task is engaged with exactly one B organization).
create unique index if not exists uq_task_applications_single_match
  on public.task_applications(task_id)
  where status = 'matched';

-- Traced queries: per-task application review by the C creator, and the
-- B-side organization application dashboard.
create index if not exists idx_task_applications_task
  on public.task_applications(task_id, applied_at);
create index if not exists idx_task_applications_organization
  on public.task_applications(organization_id, applied_at desc);

-- ---------------------------------------------------------------------------
-- public.task_status_history
-- ---------------------------------------------------------------------------
create table if not exists public.task_status_history (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.service_tasks(id) on delete cascade,
  from_status text,
  to_status text not null,
  -- NULL for system-driven transitions (e.g. deadline expiry, the 7-day
  -- unconfirmed completion close); otherwise the acting user.
  changed_by_user_id uuid references auth.users(id),
  changed_at timestamptz not null default now(),
  note text,
  constraint task_status_history_from_status_check check (
    from_status is null or from_status in (
      'draft', 'open', 'matched_pending_consent', 'in_progress',
      'completion_pending', 'completed', 'cancelled', 'expired',
      'closed_unconfirmed', 'suspended'
    )
  ),
  constraint task_status_history_to_status_check check (
    to_status in (
      'draft', 'open', 'matched_pending_consent', 'in_progress',
      'completion_pending', 'completed', 'cancelled', 'expired',
      'closed_unconfirmed', 'suspended'
    )
  ),
  -- A history row must describe an actual status change; no-op entries are
  -- not recorded.
  constraint task_status_history_from_differs_to_check check (
    from_status is null or from_status <> to_status
  )
);

comment on table public.task_status_history is
  'Append-only transition log for public.service_tasks. The trusted backend
   appends one row per status transition in the same transaction that changes
   service_tasks.status; notes may carry server-side reasons (expiry, policy
   suspension, cancellation, completion confirmation) but never raw email
   addresses or credentials.';

-- Traced query: per-task transition timeline.
create index if not exists idx_task_status_history_task
  on public.task_status_history(task_id, changed_at);

-- ---------------------------------------------------------------------------
-- public.contact_consents
-- ---------------------------------------------------------------------------
create table if not exists public.contact_consents (
  id uuid primary key default gen_random_uuid(),
  -- One consent record per task; the record is created when the match is
  -- made (task -> matched_pending_consent) and cascades with the task. If a
  -- match lapses (match_expired) and the task re-opens and is later matched
  -- again, the trusted service resets this single record for the new match
  -- (new b-side parties, statuses back to pending, emails cleared, fresh
  -- match_expires_at); the unique(task_id) guard keeps evidence in one row
  -- per task instead of accumulating stale consent rows.
  task_id uuid not null references public.service_tasks(id) on delete cascade,
  c_user_id uuid not null references auth.users(id),
  b_organization_id uuid not null references public.organizations(id),
  b_member_user_id uuid not null references auth.users(id),
  -- Version of the consent wording shown to each side at grant time; the
  -- wording itself is versioned and rendered by the trusted service.
  consent_version text not null,
  c_status text not null default 'pending',
  b_status text not null default 'pending',
  -- Filled in when BOTH sides have granted (consent completes mutually).
  granted_at timestamptz,
  -- Match creation + 72 hours: the window in which both sides must grant.
  -- If it passes without mutual grant the match lapses (application ->
  -- match_expired) and the task returns to open.
  match_expires_at timestamptz not null default now() + interval '72 hours',
  -- Computed by the trusted service as mutual-grant time + 30 days; after
  -- this instant emails stop being disclosed (window enforced by the RPC
  -- below, not by the client).
  emails_visible_until timestamptz,
  -- Evidence floor: consent and match records are retained for 3 years.
  retention_until timestamptz not null default now() + interval '3 years',
  -- Verified counterparty email addresses. NULL until BOTH sides grant;
  -- written and cleared only by the trusted service. Column-level SELECT is
  -- revoked from anon/authenticated; the only disclosure channel is
  -- public.get_task_contact_email() below. Never log or export these.
  c_email_verified text,
  b_email_verified text,
  updated_at timestamptz not null default now(),
  constraint contact_consents_one_per_task unique (task_id),
  constraint contact_consents_c_status_check check (
    c_status in ('pending', 'granted', 'withdrawn')
  ),
  constraint contact_consents_b_status_check check (
    b_status in ('pending', 'granted', 'withdrawn')
  ),
  -- Mutual-grant invariant: granted_at is only meaningful once both sides
  -- have granted.
  constraint contact_consents_granted_at_required_check check (
    not (c_status = 'granted' and b_status = 'granted') or granted_at is not null
  ),
  -- Emails may only exist while the mutual grant is in force. A withdrawal
  -- must clear both addresses and the display window in the same statement,
  -- which stops disclosure immediately (matching the contract: withdrawal
  -- after exchange stops display and notifies).
  constraint contact_consents_emails_only_when_granted_check check (
    (c_email_verified is null and b_email_verified is null)
    or (c_status = 'granted' and b_status = 'granted')
  )
);

comment on table public.contact_consents is
  'Contact-consent record for a matched task: dual independent authorization
   (C user and B organization owner/assigned member each tick their own
   unchecked-by-default checkbox). No contact column is visible until the
   mutual grant completes; verified emails live here and only here, guarded
   by revoked column privileges plus the get_task_contact_email() RPC which
   re-checks identity, mutual grant, and the 30-day display window.';

-- ---------------------------------------------------------------------------
-- RLS: enable, revoke everything, then grant the minimum.
-- ---------------------------------------------------------------------------
alter table public.service_tasks enable row level security;
alter table public.task_applications enable row level security;
alter table public.task_status_history enable row level security;
alter table public.contact_consents enable row level security;

revoke all on public.service_tasks,
  public.task_applications,
  public.task_status_history,
  public.contact_consents
from anon, authenticated;

-- Read-only for authenticated clients, scoped further by the policies below.
grant select on public.service_tasks,
  public.task_applications,
  public.task_status_history
to authenticated;

-- contact_consents: column-level grant so the two email columns are never
-- readable through table SELECT by anon or authenticated (they were revoked
-- above and are not re-granted). PostgREST/CLI clients see the consent
-- record without the email columns; email disclosure goes through
-- public.get_task_contact_email().
grant select (id, task_id, c_user_id, b_organization_id, b_member_user_id,
  consent_version, c_status, b_status, granted_at, match_expires_at,
  emails_visible_until, retention_until, updated_at)
  on public.contact_consents
to authenticated;

-- Trusted backend/worker writes; RLS stays enforced for the other roles.
grant all privileges on public.service_tasks,
  public.task_applications,
  public.task_status_history,
  public.contact_consents
to service_role;

-- updated_at maintenance (function provided by the 20260824000100 baseline).
drop trigger if exists set_service_tasks_updated_at on public.service_tasks;
create trigger set_service_tasks_updated_at
before update on public.service_tasks
for each row execute function public.set_updated_at();

drop trigger if exists set_task_applications_updated_at on public.task_applications;
create trigger set_task_applications_updated_at
before update on public.task_applications
for each row execute function public.set_updated_at();

drop trigger if exists set_contact_consents_updated_at on public.contact_consents;
create trigger set_contact_consents_updated_at
before update on public.contact_consents
for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- SECURITY DEFINER membership helpers used by RLS policies.
-- Each helper resolves membership for the CALLING user (auth.uid()) only and
-- returns a boolean; no row data crosses the definer boundary. Definer
-- execution keeps policy evaluation free of cross-table RLS recursion while
-- leaking nothing beyond the caller's own membership facts. search_path is
-- pinned; anon cannot execute.
-- ---------------------------------------------------------------------------

-- True when the caller is an active member (owner or member) of the org.
create or replace function public.is_active_org_member(p_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members om
    where om.organization_id = p_organization_id
      and om.user_id = auth.uid()
      and om.status = 'active'
  );
$$;

-- True when the caller is the org's active owner OR the named assigned
-- (responsible) member of that org.
create or replace function public.is_org_owner_or_assigned_member(
  p_organization_id uuid,
  p_assigned_member_user_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.organization_members om
    where om.organization_id = p_organization_id
      and om.user_id = auth.uid()
      and om.status = 'active'
      and (om.role = 'owner' or om.user_id = p_assigned_member_user_id)
  );
$$;

-- True when the caller created the task.
create or replace function public.is_task_creator(p_task_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.service_tasks st
    where st.id = p_task_id
      and st.creator_user_id = auth.uid()
  );
$$;

-- True when the caller is the owner or the assigned member of the B
-- organization whose application currently holds the task's single match.
create or replace function public.is_matched_task_b_participant(p_task_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.task_applications ta
    where ta.task_id = p_task_id
      and ta.status = 'matched'
      and public.is_org_owner_or_assigned_member(
            ta.organization_id, ta.assigned_member_user_id)
  );
$$;

revoke all on function public.is_active_org_member(uuid),
  public.is_org_owner_or_assigned_member(uuid, uuid),
  public.is_task_creator(uuid),
  public.is_matched_task_b_participant(uuid)
from public, anon;

grant execute on function public.is_active_org_member(uuid),
  public.is_org_owner_or_assigned_member(uuid, uuid),
  public.is_task_creator(uuid),
  public.is_matched_task_b_participant(uuid)
to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Row-level policies (SELECT only; no authenticated write policies exist).
-- ---------------------------------------------------------------------------

-- service_tasks: a task row is visible when the caller is its creator (any
-- status), when the task is publicly listed ('open'), or when the caller is
-- the owner/assigned member of the organization holding the current match.
-- The table carries no contact columns, so row disclosure never leaks PII.
create policy "creators can read their own service tasks"
on public.service_tasks
for select to authenticated
using (creator_user_id = auth.uid());

create policy "authenticated users can read open task listings"
on public.service_tasks
for select to authenticated
using (status = 'open');

create policy "matched org owner or assigned member can read task"
on public.service_tasks
for select to authenticated
using (public.is_matched_task_b_participant(id));

-- task_applications: the C creator reviews applications on their own tasks;
-- active members of the applying organization see their organization's
-- applications. No contact information lives on this table.
create policy "task creators and applying org members can read applications"
on public.task_applications
for select to authenticated
using (
  public.is_task_creator(task_id)
  or public.is_active_org_member(organization_id)
);

-- task_status_history: mirrors task visibility. The task creator reads the
-- full timeline; the matched org's owner/assigned member reads history for
-- the task their organization holds the match on. Notes may carry
-- server-side reasons, so non-participants (including rejected applicants)
-- are excluded.
create policy "task creators can read status history"
on public.task_status_history
for select to authenticated
using (public.is_task_creator(task_id));

create policy "matched org owner or assigned member can read status history"
on public.task_status_history
for select to authenticated
using (public.is_matched_task_b_participant(task_id));

-- contact_consents: the consent record (statuses and timestamps, no email
-- values - those need the RPC below) is visible only to the consenting C
-- user and to the B organization's owner or assigned responsible member.
create policy "consent parties can read their consent record"
on public.contact_consents
for select to authenticated
using (
  c_user_id = auth.uid()
  or public.is_org_owner_or_assigned_member(b_organization_id, b_member_user_id)
);

-- ---------------------------------------------------------------------------
-- Verified-email disclosure channel (sole exposure path, server-checked).
-- Returns ONLY the counterparty email and ONLY when every condition holds:
--   * caller is the C user, or the B organization's owner/assigned member;
--   * both sides granted (c_status = b_status = 'granted');
--   * the 30-day display window (emails_visible_until) is still open.
-- The window check runs in the database, so a stale client or a missed
-- cleanup job can never extend disclosure; after withdrawal or expiry the
-- function returns NULL even though the consent record remains retained
-- (3 years) for evidence.
-- ---------------------------------------------------------------------------
create or replace function public.get_task_contact_email(p_task_id uuid)
returns text
language plpgsql
stable
security definer
set search_path = public
as $$
declare
  v_caller uuid := auth.uid();
  v_c_user_id uuid;
  v_b_organization_id uuid;
  v_b_member_user_id uuid;
  v_c_status text;
  v_b_status text;
  v_visible_until timestamptz;
  v_c_email text;
  v_b_email text;
begin
  if v_caller is null then
    return null;
  end if;

  select cc.c_user_id, cc.b_organization_id, cc.b_member_user_id,
         cc.c_status, cc.b_status, cc.emails_visible_until,
         cc.c_email_verified, cc.b_email_verified
    into v_c_user_id, v_b_organization_id, v_b_member_user_id,
         v_c_status, v_b_status, v_visible_until,
         v_c_email, v_b_email
  from public.contact_consents cc
  where cc.task_id = p_task_id;

  if not found then
    return null;
  end if;

  -- Mutual grant completed and the 30-day display window still open.
  if v_c_status <> 'granted'
     or v_b_status <> 'granted'
     or v_visible_until is null
     or v_visible_until <= now() then
    return null;
  end if;

  -- C side sees the B responsible member's verified email.
  if v_caller = v_c_user_id then
    return v_b_email;
  end if;

  -- B org owner / assigned member sees the C user's verified email.
  if public.is_org_owner_or_assigned_member(v_b_organization_id, v_b_member_user_id) then
    return v_c_email;
  end if;

  return null;
end;
$$;

revoke all on function public.get_task_contact_email(uuid)
from public, anon;

grant execute on function public.get_task_contact_email(uuid)
to authenticated, service_role;
