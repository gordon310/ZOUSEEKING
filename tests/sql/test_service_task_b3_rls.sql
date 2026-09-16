-- M-B3 RLS assertions against the frozen V1 tables only.
do $$
declare t text; p record;
begin
  foreach t in array array['service_tasks','task_applications','task_status_history','contact_consents'] loop
    if exists (select 1 from pg_tables where schemaname='public' and tablename=t and not rowsecurity) then raise exception 'RLS disabled on %', t; end if;
    if has_table_privilege('anon','public.'||t,'SELECT') then raise exception 'anon SELECT grant remains on %', t; end if;
    if has_table_privilege('authenticated','public.'||t,'INSERT') or has_table_privilege('authenticated','public.'||t,'UPDATE') or has_table_privilege('authenticated','public.'||t,'DELETE') then raise exception 'authenticated write grant remains on %', t; end if;
  end loop;
  for p in select tablename, policyname, cmd, roles, qual from pg_policies where schemaname='public' and tablename in ('service_tasks','task_applications','task_status_history','contact_consents') loop
    if p.roles::text like '%anon%' then raise exception 'anon policy exists on %.%', p.tablename, p.policyname; end if;
    if p.cmd <> 'SELECT' then raise exception 'write policy exists on %.%', p.tablename, p.policyname; end if;
    if p.qual is null or p.qual in ('true','(true)') then raise exception 'unscoped policy exists on %.%', p.tablename, p.policyname; end if;
  end loop;
end $$;
