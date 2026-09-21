# Published data provenance contract

`backend/app/services/provenance.py` is the sole authoritative definition for
published property statistics and data responses. Its `DATA_CLASSES`,
`REQUIRED_STATISTIC_FIELDS`, `statistic_provenance`, and
`assert_statistic_provenance` must be used rather than copied vocabularies.

## Classes and required metadata

The only allowed classes are `verified_observation`, `scraped_aggregate`,
`modeled_estimate`, and `synthetic_fixture`. Modeled estimates and fixtures
must never be presented as collected market facts.

Every published metric response carries: `data_class`, `source_url`,
`retrieved_at`, `source_period`, `transformation_version`, `rights_status`,
`rights_confirmed`, `sample_size`, `aggregation_method`,
`missing_value_policy`, `limitations`, and `unit`. Non-synthetic records need
an actual source URL, retrieval/verification time, source period,
transformation version, and rights status. The authorized manual-data path
requires `rights_confirmed=yes`.

The enforcement points are `DbRegionStatsStore` and `/api/org/region-stats`,
`aggregate_rows` and `/api/analysis`, report serialization, the renovation
estimate response model, and CSV export rows. `tests/api/test_provenance_endpoint_contract.py`
iterates the region-statistics and analysis responses; the contract unit test
asserts explicit missing-field failures. The forward migration
`20260920000400_dataset_provenance_contract.sql` installs a precise missing
field trigger for new MLIT/e-Stat writes while preserving a nullable,
backfillable rollout.

Adding a class is a breaking governance change: document why the four classes
cannot express it, provide a compatibility mapping for existing records,
update this one module and its tests, add a forward migration if stored data
is affected, and obtain an approved contract review. Do not add a local enum.

## 2026-09-20 label audit

| Location before change | Old | New | Basis |
| --- | --- | --- | --- |
| `backend/app/region_stats_routes.py:100` | `scraped_aggregate` | `verified_observation` | MLIT API rows and e-Stat references are official public observations, not a scrape. |
| `tests/api/test_region_stats_routes.py:23` | `scraped_aggregate` | `verified_observation` | Fixture must mirror the corrected official endpoint. |
| `backend/app/intake/market_engine.py:249` | `scraped_aggregate` | unchanged | Authorized aggregated snapshot path; it is not the MLIT/e-Stat direct API path. |
| `backend/app/intake/market_engine.py:299` | `scraped_aggregate` | unchanged | Report-source label for the same aggregate snapshot. |
| `backend/app/renovation/pricing.py:356` | `modeled_estimate` | unchanged | Deterministic price-rule estimate, explicitly not a contractor quote. |
| `scripts/staging_m1_acceptance.py:277` | `synthetic_fixture` | unchanged | Staging fixture. |
| `scripts/staging_m1_acceptance.py:367` | `synthetic_fixture` | unchanged | Staging fixture payload. |
| `scripts/staging_m1_acceptance.py:796` | `synthetic_fixture` | unchanged | Staging fixture. |
| `scripts/staging_m1_acceptance.py:803` | `synthetic_fixture` | unchanged | Staging fixture. |
| `scripts/staging_m1_acceptance.py:1055` | `synthetic_fixture` | unchanged | Staging fixture. |
| `tests/unit/test_data_pipeline_cli.py:80` | `synthetic_fixture` | unchanged | Test-only fixture. |
| `tests/unit/test_cli.py:79` | `synthetic_fixture` | unchanged | Test-only fixture. |
| `tests/unit/test_cli.py:88` | `verified_observation` | unchanged | Explicit verified-observation validation case. |
| `tests/unit/test_analysis.py:61` | `scraped_aggregate` | unchanged | Aggregate analysis fixture. |
| `tests/unit/test_analysis.py:64` | `scraped_aggregate` | unchanged | Nested source metadata for that fixture. |
| `tests/unit/test_analysis.py:74` | `scraped_aggregate` | unchanged | Aggregate analysis fixture. |
| `tests/unit/test_analysis.py:77` | `scraped_aggregate` | unchanged | Nested source metadata for that fixture. |
| `tests/unit/test_analysis.py:87` | `synthetic_fixture` | unchanged | Synthetic input excluded from factual aggregation. |
| `tests/unit/test_analysis.py:113` | `scraped_aggregate` | unchanged | Aggregate insufficient-sample fixture. |

No item is `NEEDS_DECISION`: the only direct official-source mislabel was the
MLIT/e-Stat region-stat response; the rest are either explicit fixtures,
explicit model output, or an authorized aggregate path.
