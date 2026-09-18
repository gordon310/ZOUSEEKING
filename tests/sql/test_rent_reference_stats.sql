do $$
declare
  required text;
begin
  if to_regclass('public.rent_reference_stats') is null then
    raise exception 'rent_reference_stats table is missing';
  end if;
  foreach required in array array['source_key','source_label','prefecture','city','ward','geo_level','scope_label','building_type','structure_type','rent_jpy_per_sqm_month','rent_jpy_per_sqm_month_excl_zero','survey_year','survey_label','observed_month','source_url','license_label','fetched_at'] loop
    if not exists (select 1 from information_schema.columns where table_schema='public' and table_name='rent_reference_stats' and column_name=required) then
      raise exception 'missing rent_reference_stats.%', required;
    end if;
  end loop;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='rent_reference_stats' and cmd='SELECT') then
    raise exception 'rent_reference_stats select policy is missing';
  end if;
  if not exists (select 1 from pg_constraint where conrelid='public.rent_reference_stats'::regclass and contype='c' and pg_get_constraintdef(oid) like '%rent_jpy_per_sqm_month%' and pg_get_constraintdef(oid) like '%0%') then
    raise exception 'positive rent constraint is missing';
  end if;
end $$;
