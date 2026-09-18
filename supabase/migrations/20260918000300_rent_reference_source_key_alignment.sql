-- Correct the 122-5 source key to match the established e-Stat naming convention.
update public.rent_reference_stats
   set source_key = 'estat_housing_land_122_5'
 where source_key = 'estate_housing_land_122_5';

comment on column public.rent_reference_stats.source_key is
  'Canonical source identifier; the 122-5 e-Stat key follows the established estat_ naming convention.';
