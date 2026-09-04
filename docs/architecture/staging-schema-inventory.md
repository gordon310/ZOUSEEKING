# Staging schema metadata inventory

## Current status after M1（2026-09-02）

- `inventory_status=complete`
- `migration_baseline_status=canonical_staging_reconciled_production_pending`
- `staging_reconciliation=pass`
- `production_inventory=not_executed`
- 最终计数：22 public tables、300 columns、75 indexes、16 policies、0 张 RLS
  disabled application table、170 selected-role table grants、5 migration IDs。
- 最终 ledger：`20260825000400`、`20260827000500`、`20260828000100`、
  `20260902000100`、`20260902000200`。七条早期 fresh-install migration
  没有被伪造到 staging ledger。
- 最终清理：Auth users `0`、public rows `0`、Storage objects `0`。

以下是 reconciliation 前的 2026-08-30 只读 inventory，保留用于 drift 和恢复
对照；其中的 `reconciliation_required`、263 columns、20 policies 和 3 migration
IDs 是历史快照，不是当前 staging 状态。

## Pre-M1 inventory（2026-08-30）

- `inventory_status=complete`
- `migration_inventory_status=complete`
- `migration_baseline_status=reconciliation_required`
- `read_method=supabase_sql_editor_read_only`
- `live_write_status=not_attempted`
- 采集日期：2026-08-30（JST）。
- 目标：Supabase 项目 `zoubeacon-staging`（ref `fnogxuytbabxmqousifh`）。
- 不包含客户行数据。
- 不包含 access token、Storage 对象、邮箱、姓名或数据库 URL。
- 范围仅限 `public` 表、列、约束、索引、RLS 状态、policy 名称/角色/命令、trigger/function/extension、enum、所选数据库角色的表级 grants 和 migration ID 元数据。
- SQL Editor 可能自动保存查询文本；本次只输入并运行 `information_schema`、`pg_catalog`、`pg_policies` 与 `supabase_migrations.schema_migrations` 的只读 `SELECT`。

## Counts

| Object | Count |
| --- | ---: |
| public tables | 22 |
| columns | 263 |
| constraints | 97 |
| indexes | 72 |
| policies | 20 |
| trigger events | 18 |
| application functions | 8 |
| extensions | 6 |
| enum labels | 5 |
| selected role table grants | 315 |
| migration IDs | 3 |

## Table and RLS summary

| Table | RLS | Columns | Constraints | Indexes | Policies |
| --- | --- | ---: | ---: | ---: | ---: |
| `analysis_metrics` | enabled | 9 | 3 | 2 | 1 |
| `analysis_sessions` | enabled | 22 | 12 | 4 | 0 |
| `commercial_investment_details` | enabled | 9 | 3 | 1 | 1 |
| `data_sources` | enabled | 10 | 3 | 4 | 1 |
| `evidences` | enabled | 10 | 3 | 2 | 1 |
| `free_previews` | enabled | 8 | 4 | 2 | 0 |
| `generation_jobs` | enabled | 8 | 3 | 3 | 1 |
| `intake_rate_limits` | enabled | 5 | 2 | 2 | 0 |
| `new_build_details` | enabled | 10 | 2 | 1 | 1 |
| `policy_documents` | enabled | 16 | 4 | 3 | 1 |
| `product_events` | enabled | 12 | 2 | 3 | 1 |
| `project_field_evidence` | enabled | 11 | 7 | 3 | 0 |
| `project_fields` | enabled | 10 | 6 | 3 | 0 |
| `project_inputs` | enabled | 12 | 6 | 2 | 0 |
| `properties` | enabled | 28 | 13 | 6 | 4 |
| `property_reports` | enabled | 17 | 5 | 14 | 1 |
| `queries` | enabled | 16 | 4 | 8 | 1 |
| `query_field_options` | enabled | 9 | 2 | 3 | 1 |
| `residential_details` | enabled | 8 | 6 | 1 | 1 |
| `risk_findings` | enabled | 10 | 3 | 1 | 1 |
| `sources` | enabled | 11 | 2 | 2 | 0 |
| `user_profiles` | enabled | 12 | 2 | 2 | 3 |

全部 22 张表均为 `rls_enabled=true`、`rls_forced=false`。没有发现 RLS disabled 表。

## Columns

格式：`column_name:udt_name:not-null|nullable`。

| Table | Column inventory |
| --- | --- |
| `analysis_metrics` | `id:uuid:not-null`<br>`property_id:uuid:nullable`<br>`metric_name:text:not-null`<br>`metric_value:numeric:nullable`<br>`unit:text:not-null`<br>`currency:bpchar:nullable`<br>`calculation_version:text:not-null`<br>`assumption_set:jsonb:not-null`<br>`calculated_at:timestamptz:not-null` |
| `analysis_sessions` | `id:uuid:not-null`<br>`token_hash:bpchar:not-null`<br>`owner_user_id:uuid:nullable`<br>`property_id:uuid:nullable`<br>`purpose:text:not-null`<br>`consent_version:text:not-null`<br>`status:text:not-null`<br>`purpose_locked_at:timestamptz:nullable`<br>`expires_at:timestamptz:not-null`<br>`converted_at:timestamptz:nullable`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null`<br>`project_name:text:not-null`<br>`latitude:numeric:nullable`<br>`longitude:numeric:nullable`<br>`location_accuracy_m:numeric:nullable`<br>`location_source:text:not-null`<br>`location_captured_at:timestamptz:nullable`<br>`location_consent_version:text:not-null`<br>`address_candidate:text:not-null`<br>`address_source:text:not-null`<br>`address_precision:text:not-null` |
| `commercial_investment_details` | `property_id:uuid:not-null`<br>`tenant_status:text:not-null`<br>`monthly_rent_jpy:numeric:nullable`<br>`lease_start:date:nullable`<br>`lease_end:date:nullable`<br>`rent_guarantee:text:not-null`<br>`management_company:text:not-null`<br>`operating_permit_status:text:not-null`<br>`details:jsonb:not-null` |
| `data_sources` | `id:uuid:not-null`<br>`query_id:uuid:nullable`<br>`source_name:text:not-null`<br>`source_url:text:not-null`<br>`source_role:text:not-null`<br>`status:text:not-null`<br>`error_message:text:nullable`<br>`fetched_at:timestamptz:nullable`<br>`created_at:timestamptz:not-null`<br>`owner_user_id:uuid:nullable` |
| `evidences` | `id:uuid:not-null`<br>`property_id:uuid:nullable`<br>`source_id:uuid:nullable`<br>`snapshot_id:uuid:nullable`<br>`field_name:text:not-null`<br>`locator:text:not-null`<br>`extracted_value:jsonb:not-null`<br>`extraction_method:text:not-null`<br>`observed_at:timestamptz:nullable`<br>`created_at:timestamptz:not-null` |
| `free_previews` | `id:uuid:not-null`<br>`session_id:uuid:not-null`<br>`completeness:jsonb:not-null`<br>`acquisition_costs:jsonb:not-null`<br>`risk_summary:jsonb:not-null`<br>`comparable_status:text:not-null`<br>`calculation_version:text:not-null`<br>`created_at:timestamptz:not-null` |
| `generation_jobs` | `id:uuid:not-null`<br>`query_id:uuid:not-null`<br>`status:text:not-null`<br>`progress:int4:not-null`<br>`current_step:text:not-null`<br>`error_message:text:nullable`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null` |
| `intake_rate_limits` | `abuse_key_hash:bpchar:not-null`<br>`action:text:not-null`<br>`window_started_at:timestamptz:not-null`<br>`request_count:int4:not-null`<br>`expires_at:timestamptz:not-null` |
| `new_build_details` | `property_id:uuid:not-null`<br>`developer_name:text:not-null`<br>`contractor_name:text:not-null`<br>`project_status:text:not-null`<br>`launch_date:date:nullable`<br>`expected_completion_date:date:nullable`<br>`handover_date:date:nullable`<br>`phase_name:text:not-null`<br>`payment_schedule:jsonb:not-null`<br>`details:jsonb:not-null` |
| `policy_documents` | `id:uuid:not-null`<br>`policy_key:text:not-null`<br>`title:text:not-null`<br>`jurisdiction:text:not-null`<br>`authority:text:not-null`<br>`source_url:text:not-null`<br>`published_at:date:nullable`<br>`effective_from:date:not-null`<br>`effective_to:date:nullable`<br>`status:text:not-null`<br>`scope:text:not-null`<br>`summary:text:not-null`<br>`impact_categories:jsonb:not-null`<br>`source_snapshot_id:uuid:nullable`<br>`reviewed_by:uuid:nullable`<br>`reviewed_at:timestamptz:nullable` |
| `product_events` | `id:uuid:not-null`<br>`user_id:uuid:nullable`<br>`workspace_id:uuid:nullable`<br>`event_name:text:not-null`<br>`project_type:text:nullable`<br>`prefecture:text:nullable`<br>`city:text:nullable`<br>`budget_band:text:nullable`<br>`risk_topics:jsonb:not-null`<br>`outcome:text:nullable`<br>`consent_scope:text:not-null`<br>`occurred_at:timestamptz:not-null` |
| `project_field_evidence` | `id:uuid:not-null`<br>`session_id:uuid:not-null`<br>`source_input_id:uuid:nullable`<br>`field_name:text:not-null`<br>`raw_value:jsonb:not-null`<br>`normalized_value:jsonb:not-null`<br>`unit:text:nullable`<br>`locator:text:not-null`<br>`extraction_method:text:not-null`<br>`confidence:text:not-null`<br>`created_at:timestamptz:not-null` |
| `project_fields` | `id:uuid:not-null`<br>`session_id:uuid:not-null`<br>`field_name:text:not-null`<br>`selected_evidence_id:uuid:nullable`<br>`confirmed_value:jsonb:nullable`<br>`unit:text:nullable`<br>`confirmation_status:text:not-null`<br>`confirmed_at:timestamptz:nullable`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null` |
| `project_inputs` | `id:uuid:not-null`<br>`session_id:uuid:not-null`<br>`input_type:text:not-null`<br>`source_url:text:nullable`<br>`storage_path:text:nullable`<br>`original_name:text:nullable`<br>`media_type:text:nullable`<br>`size_bytes:int8:nullable`<br>`content_hash:bpchar:nullable`<br>`raw_text:text:nullable`<br>`processing_status:text:not-null`<br>`created_at:timestamptz:not-null` |
| `properties` | `id:uuid:not-null`<br>`owner_user_id:uuid:nullable`<br>`workspace_id:uuid:nullable`<br>`project_type:text:not-null`<br>`prefecture:text:not-null`<br>`city:text:not-null`<br>`ward:text:not-null`<br>`station:text:not-null`<br>`address_normalized:text:not-null`<br>`building_name:text:not-null`<br>`building_year:int4:nullable`<br>`area_sqm:numeric:nullable`<br>`asking_price:numeric:nullable`<br>`price_currency:bpchar:not-null`<br>`data_class:data_class:not-null`<br>`confidence:text:not-null`<br>`observed_at:timestamptz:nullable`<br>`source_id:uuid:nullable`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null`<br>`project_name:text:not-null`<br>`latitude:numeric:nullable`<br>`longitude:numeric:nullable`<br>`location_accuracy_m:numeric:nullable`<br>`location_source:text:not-null`<br>`location_captured_at:timestamptz:nullable`<br>`address_source:text:not-null`<br>`address_precision:text:not-null` |
| `property_reports` | `id:uuid:not-null`<br>`query_id:uuid:nullable`<br>`query_key:text:not-null`<br>`slug:text:not-null`<br>`title:text:not-null`<br>`publish_month:text:not-null`<br>`markdown:text:not-null`<br>`xhs_content:text:not-null`<br>`rental:jsonb:not-null`<br>`sale:jsonb:not-null`<br>`summary:jsonb:not-null`<br>`images:jsonb:not-null`<br>`data_sources:jsonb:not-null`<br>`raw_record:jsonb:not-null`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null`<br>`owner_user_id:uuid:nullable` |
| `queries` | `id:uuid:not-null`<br>`query_key:text:not-null`<br>`prefecture:text:not-null`<br>`city:text:not-null`<br>`ward:text:not-null`<br>`asset_type:text:not-null`<br>`year:int4:not-null`<br>`month:int4:not-null`<br>`status:text:not-null`<br>`markdown_title:text:not-null`<br>`xhs_draft:text:not-null`<br>`requested_by_name:text:not-null`<br>`requested_by_email:text:not-null`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null`<br>`owner_user_id:uuid:nullable` |
| `query_field_options` | `id:uuid:not-null`<br>`option_type:text:not-null`<br>`parent_value:text:not-null`<br>`value:text:not-null`<br>`label:text:not-null`<br>`sort_order:int4:not-null`<br>`is_active:bool:not-null`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null` |
| `residential_details` | `property_id:uuid:not-null`<br>`layout:text:not-null`<br>`floor:text:not-null`<br>`management_fee_jpy:numeric:nullable`<br>`repair_reserve_jpy:numeric:nullable`<br>`monthly_rent_jpy:numeric:nullable`<br>`fixed_asset_tax_jpy:numeric:nullable`<br>`details:jsonb:not-null` |
| `risk_findings` | `id:uuid:not-null`<br>`property_id:uuid:nullable`<br>`category:text:not-null`<br>`severity:text:not-null`<br>`basis:text:not-null`<br>`required_evidence:jsonb:not-null`<br>`action:text:not-null`<br>`confidence:text:not-null`<br>`calculation_version:text:not-null`<br>`created_at:timestamptz:not-null` |
| `sources` | `id:uuid:not-null`<br>`name:text:not-null`<br>`source_type:text:not-null`<br>`url:text:not-null`<br>`permission_status:text:not-null`<br>`update_frequency:text:not-null`<br>`parser_version:text:not-null`<br>`last_success_at:timestamptz:nullable`<br>`last_error_at:timestamptz:nullable`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null` |
| `user_profiles` | `user_id:uuid:not-null`<br>`email:text:not-null`<br>`username:text:not-null`<br>`display_name:text:not-null`<br>`city:text:not-null`<br>`favorite_area:text:not-null`<br>`favorite_asset_type:text:not-null`<br>`bio:text:not-null`<br>`membership_tier:text:not-null`<br>`daily_query_limit:int4:not-null`<br>`created_at:timestamptz:not-null`<br>`updated_at:timestamptz:not-null` |

## Constraints

| Table | Constraint inventory |
| --- | --- |
| `analysis_metrics` | `analysis_metrics_pkey` (PRIMARY KEY)<br>`analysis_metrics_property_id_fkey` (FOREIGN KEY)<br>`analysis_metrics_property_id_metric_name_calculation_versio_key` (UNIQUE) |
| `analysis_sessions` | `analysis_sessions_address_source_allowed` (CHECK)<br>`analysis_sessions_expires_after_creation` (CHECK)<br>`analysis_sessions_location_accuracy_positive` (CHECK)<br>`analysis_sessions_location_latitude_range` (CHECK)<br>`analysis_sessions_location_longitude_range` (CHECK)<br>`analysis_sessions_location_source_allowed` (CHECK)<br>`analysis_sessions_owner_user_id_fkey` (FOREIGN KEY)<br>`analysis_sessions_pkey` (PRIMARY KEY)<br>`analysis_sessions_property_id_fkey` (FOREIGN KEY)<br>`analysis_sessions_purpose_check` (CHECK)<br>`analysis_sessions_status_check` (CHECK)<br>`analysis_sessions_token_hash_key` (UNIQUE) |
| `commercial_investment_details` | `commercial_investment_details_monthly_rent_jpy_check` (CHECK)<br>`commercial_investment_details_pkey` (PRIMARY KEY)<br>`commercial_investment_details_property_id_fkey` (FOREIGN KEY) |
| `data_sources` | `data_sources_owner_user_id_fkey` (FOREIGN KEY)<br>`data_sources_pkey` (PRIMARY KEY)<br>`data_sources_query_id_fkey` (FOREIGN KEY) |
| `evidences` | `evidences_pkey` (PRIMARY KEY)<br>`evidences_property_id_fkey` (FOREIGN KEY)<br>`evidences_source_id_fkey` (FOREIGN KEY) |
| `free_previews` | `free_previews_comparable_status_check` (CHECK)<br>`free_previews_pkey` (PRIMARY KEY)<br>`free_previews_session_id_fkey` (FOREIGN KEY)<br>`free_previews_session_id_key` (UNIQUE) |
| `generation_jobs` | `generation_jobs_pkey` (PRIMARY KEY)<br>`generation_jobs_progress_check` (CHECK)<br>`generation_jobs_query_id_fkey` (FOREIGN KEY) |
| `intake_rate_limits` | `intake_rate_limits_pkey` (PRIMARY KEY)<br>`intake_rate_limits_request_count_check` (CHECK) |
| `new_build_details` | `new_build_details_pkey` (PRIMARY KEY)<br>`new_build_details_property_id_fkey` (FOREIGN KEY) |
| `policy_documents` | `policy_documents_effective_dates_check` (CHECK)<br>`policy_documents_pkey` (PRIMARY KEY)<br>`policy_documents_policy_key_effective_from_key` (UNIQUE)<br>`policy_documents_reviewed_by_fkey` (FOREIGN KEY) |
| `product_events` | `product_events_pkey` (PRIMARY KEY)<br>`product_events_user_id_fkey` (FOREIGN KEY) |
| `project_field_evidence` | `project_field_evidence_confidence_check` (CHECK)<br>`project_field_evidence_extraction_method_check` (CHECK)<br>`project_field_evidence_field_name_allowed` (CHECK)<br>`project_field_evidence_pkey` (PRIMARY KEY)<br>`project_field_evidence_session_id_fkey` (FOREIGN KEY)<br>`project_field_evidence_session_id_source_input_id_field_nam_key` (UNIQUE)<br>`project_field_evidence_source_input_id_fkey` (FOREIGN KEY) |
| `project_fields` | `project_fields_confirmation_status_check` (CHECK)<br>`project_fields_field_name_allowed` (CHECK)<br>`project_fields_pkey` (PRIMARY KEY)<br>`project_fields_selected_evidence_id_fkey` (FOREIGN KEY)<br>`project_fields_session_id_field_name_key` (UNIQUE)<br>`project_fields_session_id_fkey` (FOREIGN KEY) |
| `project_inputs` | `project_inputs_check` (CHECK)<br>`project_inputs_input_type_check` (CHECK)<br>`project_inputs_pkey` (PRIMARY KEY)<br>`project_inputs_processing_status_check` (CHECK)<br>`project_inputs_session_id_fkey` (FOREIGN KEY)<br>`project_inputs_size_bytes_check` (CHECK) |
| `properties` | `properties_address_source_allowed` (CHECK)<br>`properties_area_sqm_check` (CHECK)<br>`properties_asking_price_check` (CHECK)<br>`properties_building_year_check` (CHECK)<br>`properties_confidence_check` (CHECK)<br>`properties_location_accuracy_positive` (CHECK)<br>`properties_location_latitude_range` (CHECK)<br>`properties_location_longitude_range` (CHECK)<br>`properties_location_source_allowed` (CHECK)<br>`properties_owner_user_id_fkey` (FOREIGN KEY)<br>`properties_pkey` (PRIMARY KEY)<br>`properties_project_type_check` (CHECK)<br>`properties_source_id_fkey` (FOREIGN KEY) |
| `property_reports` | `property_reports_owner_user_id_fkey` (FOREIGN KEY)<br>`property_reports_pkey` (PRIMARY KEY)<br>`property_reports_query_id_fkey` (FOREIGN KEY)<br>`property_reports_query_key_key` (UNIQUE)<br>`property_reports_slug_key` (UNIQUE) |
| `queries` | `queries_month_check` (CHECK)<br>`queries_owner_user_id_fkey` (FOREIGN KEY)<br>`queries_pkey` (PRIMARY KEY)<br>`queries_query_key_key` (UNIQUE) |
| `query_field_options` | `query_field_options_option_type_parent_value_value_key` (UNIQUE)<br>`query_field_options_pkey` (PRIMARY KEY) |
| `residential_details` | `residential_details_fixed_asset_tax_jpy_check` (CHECK)<br>`residential_details_management_fee_jpy_check` (CHECK)<br>`residential_details_monthly_rent_jpy_check` (CHECK)<br>`residential_details_pkey` (PRIMARY KEY)<br>`residential_details_property_id_fkey` (FOREIGN KEY)<br>`residential_details_repair_reserve_jpy_check` (CHECK) |
| `risk_findings` | `risk_findings_pkey` (PRIMARY KEY)<br>`risk_findings_property_id_fkey` (FOREIGN KEY)<br>`risk_findings_severity_check` (CHECK) |
| `sources` | `sources_pkey` (PRIMARY KEY)<br>`sources_url_key` (UNIQUE) |
| `user_profiles` | `user_profiles_pkey` (PRIMARY KEY)<br>`user_profiles_user_id_fkey` (FOREIGN KEY) |

## Indexes

| Table | Index inventory |
| --- | --- |
| `analysis_metrics` | `analysis_metrics_pkey`<br>`analysis_metrics_property_id_metric_name_calculation_versio_key` |
| `analysis_sessions` | `analysis_sessions_pkey`<br>`analysis_sessions_token_hash_key`<br>`idx_analysis_sessions_expiry`<br>`idx_analysis_sessions_owner` |
| `commercial_investment_details` | `commercial_investment_details_pkey` |
| `data_sources` | `data_sources_pkey`<br>`idx_data_sources_owner_user_id`<br>`idx_sources_created_at`<br>`idx_sources_query_status` |
| `evidences` | `evidences_pkey`<br>`idx_evidences_property_field` |
| `free_previews` | `free_previews_pkey`<br>`free_previews_session_id_key` |
| `generation_jobs` | `generation_jobs_pkey`<br>`idx_jobs_created_at`<br>`idx_jobs_query_status` |
| `intake_rate_limits` | `idx_intake_rate_limits_expiry`<br>`intake_rate_limits_pkey` |
| `new_build_details` | `new_build_details_pkey` |
| `policy_documents` | `idx_policy_documents_active_scope`<br>`policy_documents_pkey`<br>`policy_documents_policy_key_effective_from_key` |
| `product_events` | `idx_product_events_occurred_at`<br>`idx_product_events_segment`<br>`product_events_pkey` |
| `project_field_evidence` | `idx_project_field_evidence_session`<br>`project_field_evidence_pkey`<br>`project_field_evidence_session_id_source_input_id_field_nam_key` |
| `project_fields` | `idx_project_fields_session`<br>`project_fields_pkey`<br>`project_fields_session_id_field_name_key` |
| `project_inputs` | `idx_project_inputs_session`<br>`project_inputs_pkey` |
| `properties` | `idx_properties_location_type`<br>`idx_properties_observed_at`<br>`idx_properties_owner`<br>`idx_properties_owner_address`<br>`idx_properties_owner_project_name`<br>`properties_pkey` |
| `property_reports` | `idx_reports_created_at`<br>`idx_reports_markdown_trgm`<br>`idx_reports_owner_user_id`<br>`idx_reports_publish_month`<br>`idx_reports_query_key`<br>`idx_reports_raw_record_gin`<br>`idx_reports_slug`<br>`idx_reports_summary_gin`<br>`idx_reports_title`<br>`idx_reports_title_trgm`<br>`property_reports_pkey`<br>`property_reports_query_key_key`<br>`property_reports_slug_key`<br>`uq_property_reports_query_id` |
| `queries` | `idx_queries_created_at`<br>`idx_queries_location`<br>`idx_queries_lookup`<br>`idx_queries_owner_user_id`<br>`idx_queries_requested_email`<br>`idx_queries_status`<br>`queries_pkey`<br>`queries_query_key_key` |
| `query_field_options` | `idx_field_options_type_parent`<br>`query_field_options_option_type_parent_value_value_key`<br>`query_field_options_pkey` |
| `residential_details` | `residential_details_pkey` |
| `risk_findings` | `risk_findings_pkey` |
| `sources` | `sources_pkey`<br>`sources_url_key` |
| `user_profiles` | `idx_user_profiles_email`<br>`user_profiles_pkey` |

## RLS policies

| Table | Policy | Role | Command |
| --- | --- | --- | --- |
| `analysis_metrics` | `owners can read own metrics` | `authenticated` | `SELECT` |
| `commercial_investment_details` | `owners can read own commercial details` | `authenticated` | `SELECT` |
| `data_sources` | `owners can read own sources` | `authenticated` | `SELECT` |
| `evidences` | `owners can read own evidence` | `authenticated` | `SELECT` |
| `generation_jobs` | `owners can read own jobs` | `authenticated` | `SELECT` |
| `new_build_details` | `owners can read own new build details` | `authenticated` | `SELECT` |
| `policy_documents` | `service can manage policies` | `authenticated` | `ALL` |
| `product_events` | `owners can read own events` | `authenticated` | `SELECT` |
| `properties` | `owners can create own properties` | `authenticated` | `INSERT` |
| `properties` | `owners can delete own properties` | `authenticated` | `DELETE` |
| `properties` | `owners can read own properties` | `authenticated` | `SELECT` |
| `properties` | `owners can update own properties` | `authenticated` | `UPDATE` |
| `property_reports` | `owners can read own reports` | `authenticated` | `SELECT` |
| `queries` | `owners can read own queries` | `authenticated` | `SELECT` |
| `query_field_options` | `public can read field options` | `anon` | `SELECT` |
| `residential_details` | `owners can read own residential details` | `authenticated` | `SELECT` |
| `risk_findings` | `owners can read own risks` | `authenticated` | `SELECT` |
| `user_profiles` | `users can insert own profile` | `authenticated` | `INSERT` |
| `user_profiles` | `users can read own profile` | `authenticated` | `SELECT` |
| `user_profiles` | `users can update own profile preferences` | `authenticated` | `UPDATE` |

没有 policy 的表仍然保持 RLS enabled；该事实只表示普通客户端默认无法通过 policy 访问，不能替代四身份行为测试。

## Enum and selected role table grants

The `public.data_class` enum has the same five ordered labels as the local
candidate:

1. `verified_observation`
2. `scraped_aggregate`
3. `modeled_estimate`
4. `synthetic_fixture`
5. `user_submitted`

`information_schema.role_table_grants` returned the following counts for the
three application roles:

| Role | Grant rows |
| --- | ---: |
| `anon` | 77 |
| `authenticated` | 84 |
| `service_role` | 154 |

The 77 `anon` rows are all seven table privileges (`SELECT`, `INSERT`,
`UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`) on these 11 tables:

- `analysis_metrics`
- `commercial_investment_details`
- `evidences`
- `new_build_details`
- `policy_documents`
- `product_events`
- `properties`
- `query_field_options`
- `residential_details`
- `risk_findings`
- `sources`

`authenticated` has the same seven privileges on those 11 tables, plus
SELECT on `data_sources`, `generation_jobs`, `property_reports`, and `queries`,
and INSERT/SELECT/UPDATE on `user_profiles`. `service_role` has all seven
privileges on all 22 tables.

Table grants do not by themselves bypass RLS. The current policy set leaves
many `anon` operations without an applicable policy, but the broad grants are
still materially wider than the least-privilege candidate (`anon=0`,
`authenticated=15`, `service_role=154`). Actual row behavior must be verified
again on an isolated staging restore before any grant or policy change.

## Triggers and application functions

`information_schema.triggers` 返回 18 个 event rows：

| Table | Trigger | Events | Function |
| --- | --- | --- | --- |
| `analysis_metrics` | `protect_analysis_metric_history` | `DELETE`, `UPDATE` | `prevent_published_metric_update()` |
| `analysis_sessions` | `protect_intake_identity` | `INSERT`, `UPDATE` | `prevent_intake_identity_change()` |
| `analysis_sessions` | `set_analysis_sessions_updated_at` | `UPDATE` | `set_intake_updated_at()` |
| `data_sources` | `protect_sources_ownership` | `UPDATE` | `prevent_client_ownership_change()` |
| `generation_jobs` | `set_jobs_updated_at` | `UPDATE` | `set_updated_at()` |
| `policy_documents` | `prevent_policy_version_overlap` | `INSERT`, `UPDATE` | `prevent_policy_version_overlap()` |
| `project_fields` | `set_project_fields_updated_at` | `UPDATE` | `set_intake_updated_at()` |
| `property_reports` | `protect_reports_ownership` | `UPDATE` | `prevent_client_ownership_change()` |
| `property_reports` | `set_reports_updated_at` | `UPDATE` | `set_updated_at()` |
| `queries` | `protect_queries_ownership` | `UPDATE` | `prevent_client_ownership_change()` |
| `queries` | `set_queries_updated_at` | `UPDATE` | `set_updated_at()` |
| `query_field_options` | `set_field_options_updated_at` | `UPDATE` | `set_updated_at()` |
| `user_profiles` | `protect_membership_fields` | `INSERT`, `UPDATE` | `prevent_client_membership_change()` |
| `user_profiles` | `set_user_profiles_updated_at` | `UPDATE` | `set_updated_at()` |

排除 extension-owned routines 后，`public` schema 有 8 个 application functions：

- `is_service_role()`
- `prevent_client_membership_change()`
- `prevent_client_ownership_change()`
- `prevent_intake_identity_change()`
- `prevent_policy_version_overlap()`
- `prevent_published_metric_update()`
- `set_intake_updated_at()`
- `set_updated_at()`

## Extensions

| Extension | Schema | Version |
| --- | --- | --- |
| `pg_stat_statements` | `extensions` | `1.11` |
| `pg_trgm` | `public` | `1.6` |
| `pgcrypto` | `extensions` | `1.3` |
| `plpgsql` | `pg_catalog` | `1.0` |
| `supabase_vault` | `vault` | `0.3.1` |
| `uuid-ossp` | `extensions` | `1.1` |

## Migration IDs

- `20260825000400`
- `20260827000500`
- `20260828000100`

盘点当时用于对照的候选 fresh-install branch 尚未包含 staging 的
`20260827000500` 与 `20260828000100`；最终 canonical branch 已保留这两条原文件。
当时 staging ledger 不含 `20260824000100`–`20260824000700`，也不含最终 access
contract。2026-09-02 通过 later-ID reconciliation 关闭差异，没有通过改写
timestamp、`migration repair` 或 reset 强行对齐。

## Reproduction boundary

2026-08-30 浏览器盘点没有生成 dump；2026-09-02 已另行完成完整逻辑备份与
隔离恢复。完整 drift、hash 和 M1 证据记录在
[migration-reconciliation-report.md](migration-reconciliation-report.md)；恢复门禁记录在
[database-recovery-runbook.md](../operations/database-recovery-runbook.md)。
