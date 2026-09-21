-- The provenance contract migration added columns to existing datasets without
-- backfilling them, so every populated statistics query raised on the missing
-- metadata (production returned HTTP 500 for any region with data). Backfill the
-- existing rows from values the importer itself writes, keeping the contract
-- strict: retrieved_at is the real import time, source_period the source quarter,
-- and the class/rights/limitations text the official-source constants already in
-- scripts/import_mlit_transactions.py. Idempotent: only rows still missing metadata
-- are touched, so re-running changes nothing.

update public.mlit_transactions
   set data_class = coalesce(data_class, 'verified_observation'),
       source_url = coalesce(source_url, 'https://www.reinfolib.mlit.go.jp/realEstatePrices/'),
       retrieved_at = coalesce(retrieved_at, imported_at),
       source_period = coalesce(source_period, trade_quarter),
       transformation_version = coalesce(transformation_version, 'mlit-xit001-normalizer-v1'),
       rights_status = coalesce(rights_status, 'rights_confirmed'),
       rights_confirmed = coalesce(rights_confirmed, 'yes'),
       limitations = coalesce(limitations, 'Official closed-transaction observations; exclude incomplete or nonpositive price and area fields.'),
       missing_value_policy = coalesce(missing_value_policy, 'exclude_missing_or_nonpositive_unit_price')
 where data_class is null
    or retrieved_at is null
    or source_period is null
    or transformation_version is null
    or rights_status is null
    or rights_confirmed is null
    or limitations is null
    or missing_value_policy is null
    or source_url is null;

-- NOTE: this migration deliberately does NOT change public.sources.data_class.
-- Published reports are guarded by "published property_reports data_class must match
-- its source", and the report writer still records scraped_aggregate, so flipping the
-- source class alone breaks report generation (observed in production). Relabelling
-- the official dataset as verified_observation must therefore change the report writer
-- to read the class from its source and backfill existing reports at the same time.
-- Only the license, which no guard compares, is filled here.
update public.sources
   set license = coalesce(license, 'PDL1.0')
 where (url like '%reinfolib.mlit.go.jp%' or name ilike '%不動産情報ライブラリ%')
   and license is null;
