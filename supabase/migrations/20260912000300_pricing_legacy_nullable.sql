-- Allow unconfigured legacy entitlement columns to be represented as NULL.
-- Forward-only migration. Do not run this file from application startup.

do $$
begin
  if exists (
    select 1
      from information_schema.columns
     where table_schema = 'public'
       and table_name = 'pricing_plans'
       and column_name = 'monthly_query_limit'
       and is_nullable = 'NO'
  ) then
    alter table public.pricing_plans
      alter column monthly_query_limit drop not null;
  end if;

  if exists (
    select 1
      from information_schema.columns
     where table_schema = 'public'
       and table_name = 'pricing_plans'
       and column_name = 'monthly_report_quota'
       and is_nullable = 'NO'
  ) then
    alter table public.pricing_plans
      alter column monthly_report_quota drop not null;
  end if;

  if exists (
    select 1
      from information_schema.columns
     where table_schema = 'public'
       and table_name = 'pricing_plans'
       and column_name = 'subscription_slots'
       and is_nullable = 'NO'
  ) then
    alter table public.pricing_plans
      alter column subscription_slots drop not null;
  end if;

  if exists (
    select 1
      from information_schema.columns
     where table_schema = 'public'
       and table_name = 'pricing_plans'
       and column_name = 'export_rows_monthly'
       and is_nullable = 'NO'
  ) then
    alter table public.pricing_plans
      alter column export_rows_monthly drop not null;
  end if;
end
$$;
