-- Forward-only audience classification for entitlement selection.

alter table public.user_profiles
  add column if not exists audience text not null default 'c';

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.user_profiles'::regclass
      and conname = 'user_profiles_audience_check'
  ) then
    alter table public.user_profiles
      add constraint user_profiles_audience_check check (audience in ('c', 'b'));
  end if;
end;
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  signup_audience text;
begin
  signup_audience := coalesce(nullif(new.raw_user_meta_data->>'audience', ''), 'c');
  if signup_audience not in ('c', 'b') then
    signup_audience := 'c';
  end if;
  insert into public.user_profiles (user_id, email, audience)
  values (new.id, coalesce(new.email, ''), signup_audience)
  on conflict (user_id) do nothing;
  return new;
end;
$$;
