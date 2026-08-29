create table if not exists public.user_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null default '',
  username text not null default '',
  display_name text not null default '',
  city text not null default '',
  favorite_area text not null default '',
  favorite_asset_type text not null default '',
  bio text not null default '',
  membership_tier text not null default 'free',
  daily_query_limit int not null default 3,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_user_profiles_email
on public.user_profiles(email);

drop trigger if exists set_user_profiles_updated_at on public.user_profiles;
create trigger set_user_profiles_updated_at
before update on public.user_profiles
for each row execute function public.set_updated_at();

alter table public.user_profiles enable row level security;

create or replace function public.is_service_role()
returns boolean
language sql
stable
set search_path = public
as $$
  select current_user in ('postgres', 'service_role', 'supabase_admin')
      or coalesce(current_setting('request.jwt.claim.role', true), '')
         in ('service_role', 'supabase_admin');
$$;

create or replace function public.prevent_client_membership_change()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if not public.is_service_role()
     and (
       (tg_op = 'INSERT'
        and (new.membership_tier <> 'free' or new.daily_query_limit <> 3))
       or (tg_op = 'UPDATE'
           and (
             new.membership_tier is distinct from old.membership_tier
             or new.daily_query_limit is distinct from old.daily_query_limit
           ))
     ) then
    raise exception 'membership fields are server-managed';
  end if;
  return new;
end;
$$;

drop trigger if exists protect_membership_fields on public.user_profiles;
create trigger protect_membership_fields
before insert or update on public.user_profiles
for each row execute function public.prevent_client_membership_change();

revoke all on public.user_profiles from public;
revoke all on public.user_profiles from anon, authenticated;
grant select, insert, update on public.user_profiles to authenticated;

drop policy if exists "users can read own profile" on public.user_profiles;
create policy "users can read own profile"
on public.user_profiles for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "users can insert own profile" on public.user_profiles;
create policy "users can insert own profile"
on public.user_profiles for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "users can update own profile" on public.user_profiles;
drop policy if exists "users can update own profile preferences" on public.user_profiles;
create policy "users can update own profile preferences"
on public.user_profiles for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
