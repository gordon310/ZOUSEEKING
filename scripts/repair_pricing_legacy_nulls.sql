-- One-time operator repair for legacy pricing columns.
-- Do not run this file from application startup or as part of the seed.
-- Apply the nullable forward migration before running this repair.
-- The update is idempotent: after the first run, a repeat finds no zeroes.
begin;

do $$
declare
    not_nullable text;
begin
    select string_agg(column_name, ', ' order by column_name)
      into not_nullable
      from information_schema.columns
     where table_schema = 'public'
       and table_name = 'pricing_plans'
       and column_name in (
           'monthly_query_limit', 'monthly_report_quota',
           'subscription_slots', 'export_rows_monthly'
       )
       and is_nullable = 'NO';
    if not_nullable is not null then
        raise exception 'pricing_plans legacy columns must allow NULL before repair: %', not_nullable;
    end if;
end $$;

update public.pricing_plans
   set monthly_query_limit = nullif(monthly_query_limit, 0),
       monthly_report_quota = nullif(monthly_report_quota, 0),
       subscription_slots = nullif(subscription_slots, 0),
       export_rows_monthly = nullif(export_rows_monthly, 0)
 where monthly_query_limit = 0
    or monthly_report_quota = 0
    or subscription_slots = 0
    or export_rows_monthly = 0;

commit;
