-- The MLIT Real Estate Information Library is an official government API.
-- Keep the published-report guard intact: within this one transaction the
-- source changes first, then every report bound to that source is relabelled
-- to the same value before the migration commits.
begin;

update public.sources
   set data_class = 'verified_observation'::public.data_class,
       -- This registry row represents the recurring API, not a particular
       -- transaction period.  Region metrics derive their period from
       -- mlit_transactions.trade_quarter.
       source_period = 'quarterly',
       updated_at = now()
 where url like '%reinfolib.mlit.go.jp%';

update public.property_reports as report
   set data_class = source.data_class,
       updated_at = now()
  from public.sources as source
 where report.source_id = source.id
   and source.url like '%reinfolib.mlit.go.jp%'
   and report.data_class is distinct from source.data_class;

do $$
begin
  if exists (
    select 1
      from public.property_reports as report
      join public.sources as source on source.id = report.source_id
     where source.url like '%reinfolib.mlit.go.jp%'
       and report.data_class is distinct from source.data_class
  ) then
    raise exception 'MLIT property_reports data_class relabel did not match its source';
  end if;
end
$$;

commit;
