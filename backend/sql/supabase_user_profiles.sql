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
create policy "users can update own profile"
on public.user_profiles for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
