-- Consumer pre-release invitation gate. Additive: existing accounts are untouched.
create table public.invite_codes (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check (code = lower(btrim(code)) and length(code) between 4 and 128),
  label text not null check (length(btrim(label)) between 1 and 160), note text,
  max_uses integer check (max_uses is null or max_uses > 0),
  used_count integer not null default 0 check (used_count >= 0), expires_at timestamptz,
  enabled boolean not null default true, created_at timestamptz not null default now(),
  created_by uuid references auth.users(id) on delete set null, last_used_at timestamptz,
  constraint invite_codes_usage_check check (max_uses is null or used_count <= max_uses)
);
create table public.invite_redemptions (
  id uuid primary key default gen_random_uuid(),
  invite_code_id uuid not null references public.invite_codes(id) on delete restrict,
  email_hash char(64) not null unique check (email_hash ~ '^[0-9a-f]{64}$'),
  user_id uuid unique references auth.users(id) on delete restrict, ip_hash char(64) check (ip_hash is null or ip_hash ~ '^[0-9a-f]{64}$'),
  reserved_at timestamptz not null default now(), redeemed_at timestamptz,
  constraint invite_redemptions_completion_check check ((user_id is null and redeemed_at is null) or (user_id is not null and redeemed_at is not null))
);
create index invite_codes_active_lookup on public.invite_codes(code) where enabled;
create index invite_redemptions_code_audit on public.invite_redemptions(invite_code_id, reserved_at desc);
alter table public.invite_codes enable row level security;
alter table public.invite_redemptions enable row level security;
revoke all on public.invite_codes, public.invite_redemptions from anon, authenticated;
grant all privileges on public.invite_codes, public.invite_redemptions to service_role;
-- This CTE UPDATE is the concurrency boundary. A code cannot exceed max_uses.
create function public.reserve_invite_code(p_code text, p_email_hash char(64), p_ip_hash char(64) default null)
returns table(redemption_id uuid, state text) language plpgsql security definer set search_path = public as $$
begin
  return query with claimed as (
    update public.invite_codes c set used_count=c.used_count+1, last_used_at=now()
    where c.code=lower(btrim(p_code)) and c.enabled and (c.expires_at is null or c.expires_at>now())
      and (c.max_uses is null or c.used_count<c.max_uses)
      and not exists (select 1 from public.invite_redemptions r where r.email_hash=p_email_hash)
    returning c.id
  ), reserved as (
    insert into public.invite_redemptions(invite_code_id,email_hash,ip_hash)
    select id,p_email_hash,p_ip_hash from claimed returning id
  ) select id,'reserved'::text from reserved;
  if not found then return query select null::uuid,'unavailable'::text; end if;
end; $$;
create function public.complete_invite_redemption(p_redemption_id uuid, p_user_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin update public.invite_redemptions set user_id=p_user_id,redeemed_at=now() where id=p_redemption_id and user_id is null; return found; end; $$;
create function public.release_invite_reservation(p_redemption_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare code_id uuid; begin
 delete from public.invite_redemptions where id=p_redemption_id and user_id is null returning invite_code_id into code_id;
 if code_id is null then return false; end if;
 update public.invite_codes set used_count=used_count-1 where id=code_id and used_count>0; return true;
end; $$;
revoke all on function public.reserve_invite_code(text,char(64),char(64)) from public,anon,authenticated;
revoke all on function public.complete_invite_redemption(uuid,uuid) from public,anon,authenticated;
revoke all on function public.release_invite_reservation(uuid) from public,anon,authenticated;
grant execute on function public.reserve_invite_code(text,char(64),char(64)) to service_role;
grant execute on function public.complete_invite_redemption(uuid,uuid) to service_role;
grant execute on function public.release_invite_reservation(uuid) to service_role;
