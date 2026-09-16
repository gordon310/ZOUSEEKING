do $$
declare
  rls_enabled boolean;
  anon_select bigint;
  authenticated_select bigint;
begin
  if to_regclass('public.mlit_transactions') is null then
    raise exception 'mlit_transactions table missing';
  end if;
  if not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='mlit_transactions'
      and column_name in ('source_id','asset_kind','asset_type','price_jpy','area_sqm','unit_price_jpy_per_sqm','trade_quarter','raw')
    group by table_name having count(*)=8
  ) then raise exception 'required MLIT columns missing'; end if;
  select c.relrowsecurity into rls_enabled
  from pg_class c join pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relname='mlit_transactions';
  if not rls_enabled then raise exception 'MLIT table RLS disabled'; end if;
  select count(*) into anon_select from information_schema.role_table_grants
    where table_schema='public' and table_name='mlit_transactions' and grantee='anon' and privilege_type='SELECT';
  if anon_select <> 0 then raise exception 'anon SELECT must be denied'; end if;
  select count(*) into authenticated_select from information_schema.role_table_grants
    where table_schema='public' and table_name='mlit_transactions' and grantee='authenticated' and privilege_type='SELECT';
  if authenticated_select <> 1 then raise exception 'authenticated SELECT grant missing'; end if;
end $$;
