-- Forward-only replacement adds stable client-safe error states without
-- exposing the code table to browser roles.
create or replace function public.reserve_invite_code(p_code text, p_email_hash char(64), p_ip_hash char(64) default null)
returns table(redemption_id uuid, state text) language plpgsql security definer set search_path = public as $$
begin
  return query with claimed as (
    update public.invite_codes c set used_count=c.used_count+1,last_used_at=now()
    where c.code=lower(btrim(p_code)) and c.enabled and (c.expires_at is null or c.expires_at>now())
      and (c.max_uses is null or c.used_count<c.max_uses)
      and not exists (select 1 from public.invite_redemptions r where r.email_hash=p_email_hash)
    returning c.id
  ), reserved as (
    insert into public.invite_redemptions(invite_code_id,email_hash,ip_hash) select id,p_email_hash,p_ip_hash from claimed returning id
  ) select id,'reserved'::text from reserved;
  if found then return; end if;
  return query select null::uuid, case
    when not exists (select 1 from public.invite_codes where code=lower(btrim(p_code))) then 'invalid'
    when exists (select 1 from public.invite_codes where code=lower(btrim(p_code)) and not enabled) then 'disabled'
    when exists (select 1 from public.invite_codes where code=lower(btrim(p_code)) and expires_at is not null and expires_at<=now()) then 'expired'
    when exists (select 1 from public.invite_codes where code=lower(btrim(p_code)) and max_uses is not null and used_count>=max_uses) then 'exhausted'
    else 'unavailable' end;
end; $$;
