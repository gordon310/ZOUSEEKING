-- Contract assertions for the additive report-generation outbox migration.
do $$
declare
  required text;
begin
  foreach required in array array[
    'id', 'generation_job_id', 'query_id', 'idempotency_key', 'payload', 'status',
    'attempts', 'max_attempts', 'next_attempt_at', 'claim_token', 'claimed_at',
    'completed_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'
  ] loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='report_generation_outbox' and column_name=required
    ) then
      raise exception 'missing report_generation_outbox column: %', required;
    end if;
  end loop;
  if not exists (
    select 1 from pg_constraint
    where conrelid='public.report_generation_outbox'::regclass
      and contype='u' and pg_get_constraintdef(oid) like '%generation_job_id%'
  ) then
    raise exception 'missing one-outbox-row-per-generation-job uniqueness';
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid='public.report_generation_outbox'::regclass
      and contype='u' and pg_get_constraintdef(oid) like '%idempotency_key%'
  ) then
    raise exception 'missing outbox idempotency uniqueness';
  end if;
  if not exists (
    select 1 from pg_class where oid='public.report_generation_outbox'::regclass and relrowsecurity
  ) then
    raise exception 'outbox RLS must be enabled';
  end if;
end $$;

select 'report_generation_outbox_schema=pass' as result;
