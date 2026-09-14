-- Register the authorised source used by the market report generation path.
-- The deterministic id lets the application bind published reports to this
-- registry row without discovering or fabricating a source at write time.
insert into public.sources (
  id,
  name,
  source_type,
  url,
  permission_status,
  update_frequency,
  parser_version,
  source_period,
  limitations,
  data_class,
  observed_at,
  transformation_version
)
values (
  'bf4b6d56-f7ed-4e66-b599-3900e22001d6'::uuid,
  '国土交通省 土地総合情報システム(取引価格情報)',
  'government_open_data',
  'https://www.mlit.go.jp/',
  'rights_confirmed',
  'quarterly',
  'market-engine-v1',
  'source registry entry verified 2026-09-15',
  'Government open data with source attribution; the report is a ward-level aggregate of closed transaction prices and is not a listing price or single-property valuation.',
  'scraped_aggregate'::public.data_class,
  '2026-09-15T00:00:00+00:00'::timestamptz,
  'market-engine-v1'
)
on conflict (url) do nothing;
