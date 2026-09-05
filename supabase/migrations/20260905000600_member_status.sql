-- Member account status (20260905000600) - 增补 A (approved 2026-09-05).
--
-- Adds ``public.user_profiles.status`` (the member-level active/suspended
-- state machine) with a named CHECK, then closes the browser write path so
-- only the trusted back office (admin API / service_role) can flip it:
--
--   * 20260829000100 granted table-level UPDATE on user_profiles to
--     authenticated and the "users can update own profile preferences" RLS
--     policy lets a member update their own row.  A bare column-level
--     ``revoke update (status)`` would NOT remove the ability to write the
--     column while the table-level UPDATE grant survives (verified against
--     PostgreSQL 17: has_column_privilege(...) stays true).  The UPDATE grant
--     is therefore converted into an explicit per-column allowlist of the
--     client-editable preference columns, keeping the profile-update feature
--     while membership_tier / daily_query_limit / status stay out of browser
--     reach at the privilege layer.
--   * The existing server-managed-field guard (prevent_client_membership_change
--     / protect_membership_fields, first defined in 20260824000300 and
--     20260827000500) is extended to cover ``status`` as a second line of
--     defence: a non-service client can neither UPDATE status nor INSERT a row
--     whose status is not the 'active' default.
--   * service_role (and postgres/supabase_admin) keep full table privileges,
--     so the admin API's trusted transaction can write status directly.
--
-- No new RLS policy is added; the existing self-row profile policy is
-- unchanged and remains safe because column grants + the trigger now fence
-- every server-managed field.
--
-- Prerequisites (applied before this file):
--   auth.users + public.user_profiles   (20260824000100 legacy baseline)
--   public.prevent_client_membership_change() trigger (24000300/27000500)

do $$
begin
  if to_regclass('public.user_profiles') is null then
    raise exception 'missing prerequisite table: public.user_profiles';
  end if;
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'user_profiles'
      and column_name = 'status'
  ) then
    raise exception '20260905000600 already applied: public.user_profiles.status exists';
  end if;
end $$;

-- Member account status: default active; suspended members are blocked at the
-- service layer (admin API refuses their member surface).  Columns other than
-- 'active'/'suspended' are rejected by the named CHECK below.
alter table public.user_profiles
  add column status text not null default 'active';

alter table public.user_profiles
  add constraint user_profiles_status_allowed
  check (status in ('active', 'suspended'));

comment on column public.user_profiles.status is
  'Member account state: active or suspended. Server-managed - only the trusted'
  ' back office (admin API / service_role) may change it. A suspended member'
  ' loses the member surface; see backend admin service member status writes.';

-- Privilege fence.  The table-level UPDATE grant from 20260829000100 is
-- replaced by an explicit column allowlist of the preference fields a member
-- may edit on their own profile (kept identical to the columns the profile
-- update UI writes).  status, membership_tier, daily_query_limit and the
-- identity/timestamp columns are therefore not updatable by authenticated;
-- UPDATE through the "users can update own profile preferences" RLS policy
-- cannot touch them.
revoke update on public.user_profiles from authenticated;

grant update (email, username, display_name, city, favorite_area, favorite_asset_type, bio)
  on public.user_profiles to authenticated;

-- Fold ``status`` into the existing server-managed-field trigger.  A client
-- cannot reach it through UPDATE any more (column grant removed above) and an
-- INSERT must keep the 'active' default; this trigger is the second line of
-- defence for any future grant drift.  service_role (postgres / supabase_admin)
-- bypasses it via public.is_service_role(), so the admin API transaction and
-- the seed/test harness can write status directly.
create or replace function public.prevent_client_membership_change()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if public.is_service_role() then
    return new;
  end if;
  if tg_op = 'INSERT'
     and (new.membership_tier <> 'free' or new.daily_query_limit <> 3) then
    raise exception 'membership fields are server-managed';
  end if;
  if tg_op = 'UPDATE'
     and (new.membership_tier is distinct from old.membership_tier
          or new.daily_query_limit is distinct from old.daily_query_limit) then
    raise exception 'membership fields are server-managed';
  end if;
  if tg_op = 'INSERT' and new.status is distinct from 'active' then
    raise exception 'member status is server-managed';
  end if;
  if tg_op = 'UPDATE' and new.status is distinct from old.status then
    raise exception 'member status is server-managed';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_membership_fields on public.user_profiles;
create trigger protect_membership_fields
before insert or update on public.user_profiles
for each row execute function public.prevent_client_membership_change();
