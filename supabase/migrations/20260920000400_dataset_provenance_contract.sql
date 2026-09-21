-- Shared dataset provenance fields for the official MLIT and e-Stat tables.
-- Columns intentionally start nullable: existing rows are backfilled by the
-- controlled import job, while the trigger rejects incomplete new writes.

alter table public.mlit_transactions
  add column if not exists data_class public.data_class,
  add column if not exists source_url text,
  add column if not exists retrieved_at timestamptz,
  add column if not exists source_period text,
  add column if not exists transformation_version text,
  add column if not exists rights_status text,
  add column if not exists rights_confirmed text,
  add column if not exists limitations text,
  add column if not exists missing_value_policy text;

alter table public.rent_reference_stats
  add column if not exists data_class public.data_class,
  add column if not exists retrieved_at timestamptz,
  add column if not exists source_period text,
  add column if not exists transformation_version text,
  add column if not exists rights_status text,
  add column if not exists rights_confirmed text,
  add column if not exists limitations text,
  add column if not exists missing_value_policy text;

comment on column public.mlit_transactions.data_class is 'Shared provenance class; import backfill sets verified_observation for MLIT official rows.';
comment on column public.mlit_transactions.source_period is 'Official source coverage period; import backfill uses trade_quarter.';
comment on column public.rent_reference_stats.data_class is 'Shared provenance class; import backfill sets verified_observation for e-Stat official rows.';
comment on column public.rent_reference_stats.source_period is 'Official source coverage period; import backfill uses observed_month or survey_year.';

create or replace function public.provenance_missing_fields(record jsonb)
returns text[]
language sql
immutable
set search_path = public
as $$
  select array_agg(field order by field)
  from unnest(array['data_class', 'source_url', 'retrieved_at', 'source_period',
                    'transformation_version', 'rights_status', 'rights_confirmed',
                    'limitations', 'missing_value_policy']) as field
  where nullif(btrim(coalesce(record ->> field, '')), '') is null
$$;

create or replace function public.enforce_dataset_provenance()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  missing text[];
begin
  if new.data_class = 'synthetic_fixture' then
    return new;
  end if;
  missing := public.provenance_missing_fields(to_jsonb(new));
  if coalesce(array_length(missing, 1), 0) > 0 then
    raise exception 'provenance contract missing: %', array_to_string(missing, ', ');
  end if;
  if new.data_class not in ('verified_observation', 'scraped_aggregate', 'modeled_estimate') then
    raise exception 'provenance contract invalid data_class: %', new.data_class;
  end if;
  if new.rights_confirmed not in ('yes', 'no') then
    raise exception 'provenance contract invalid rights_confirmed: %', new.rights_confirmed;
  end if;
  return new;
end;
$$;

drop trigger if exists enforce_mlit_transactions_provenance on public.mlit_transactions;
create trigger enforce_mlit_transactions_provenance
before insert or update on public.mlit_transactions
for each row execute function public.enforce_dataset_provenance();

drop trigger if exists enforce_rent_reference_stats_provenance on public.rent_reference_stats;
create trigger enforce_rent_reference_stats_provenance
before insert or update on public.rent_reference_stats
for each row execute function public.enforce_dataset_provenance();

revoke all on function public.provenance_missing_fields(jsonb) from public, anon, authenticated;
revoke all on function public.enforce_dataset_provenance() from public, anon, authenticated;

-- Backfill is deliberately performed by the trusted importer in bounded batches:
-- MLIT => verified_observation, source_url from sources.url, retrieved_at from
-- imported_at, source_period=trade_quarter; e-Stat => verified_observation,
-- retrieved_at=fetched_at, source_period=observed_month/survey_year.  Do not
-- fabricate values in this migration for rows whose historical evidence is absent.
