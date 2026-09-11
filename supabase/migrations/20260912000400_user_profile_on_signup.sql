-- Create a public profile for every Auth user and backfill existing users.
-- This is intentionally a forward migration: existing profile guards and
-- timestamp triggers remain unchanged.

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.user_profiles (user_id, email)
  values (new.id, coalesce(new.email, ''))
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

insert into public.user_profiles (user_id, email)
select u.id, coalesce(u.email, '')
from auth.users u
on conflict (user_id) do nothing;
