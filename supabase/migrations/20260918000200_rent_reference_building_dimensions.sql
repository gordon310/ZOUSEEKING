-- Additive forward migration for 122-5 building and structure dimensions.
alter table public.rent_reference_stats
  add column if not exists building_type text,
  add column if not exists structure_type text;

drop index if exists public.uq_rent_reference_stats_natural_key;
create unique index uq_rent_reference_stats_natural_key
  on public.rent_reference_stats(
    source_key, prefecture, city, ward, scope_label,
    building_type, structure_type, survey_year, coalesce(observed_month, '')
  );

comment on column public.rent_reference_stats.building_type is
  'Official 122-5 住宅の建て方 dimension, normalized from e-Stat; NULL for sources without this dimension.';
comment on column public.rent_reference_stats.structure_type is
  'Official 122-5 建物の構造 dimension, normalized from e-Stat; NULL for sources without this dimension.';
