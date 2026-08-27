-- 通过 psql 执行的基础 schema 回归断言。
do $$
declare
  required_table text;
begin
  foreach required_table in array array[
    'sources', 'properties', 'residential_details', 'new_build_details',
    'commercial_investment_details', 'evidences', 'analysis_metrics',
    'risk_findings', 'policy_documents', 'product_events'
  ] loop
    if to_regclass('public.' || required_table) is null then
      raise exception 'missing required table: %', required_table;
    end if;
  end loop;

  if not exists (
    select 1 from pg_constraint
    where conname = 'properties_project_type_check'
  ) then
    raise exception 'properties project type constraint is missing';
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'properties_data_class_not_null'
       or (conrelid = 'public.properties'::regclass and contype = 'c' and pg_get_constraintdef(oid) like '%data_class%')
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'properties'
      and column_name = 'data_class' and is_nullable = 'NO'
  ) then
    raise exception 'properties data_class must be non-null';
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'analysis_metrics'
      and column_name = 'calculation_version'
  ) then
    raise exception 'analysis_metrics calculation_version is missing';
  end if;
end $$;
