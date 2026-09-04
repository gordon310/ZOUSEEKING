# Schema ownership 审计

**审计日期：** 2026-09-02
**范围：** `supabase/migrations/`、`backend/sql/`、数据库启动入口及开发/部署文档。
**方式：** 文件/manifest 审计、disposable local reset、获批 staging
transaction dry-run、later-ID push、逻辑备份隔离恢复及运行验收。

## 结论与边界

**本地与 staging ownership contract：SHIP。production baseline：BLOCKED。**

- `supabase/migrations/` 是唯一允许新增的 forward migration history，当前清单为 13 个文件。
- `backend/sql/` 的 8 个 SQL 文件分别属于历史 bootstrap、迁移前来源、生成支持或手工支持材料，不能拼接成第二条 migration history。
- `backend/app/db.py::init_schema` 仍读取 `backend/sql/schema.sql`，但 `backend/app/main.py::should_init_schema` 只在显式 `INIT_SCHEMA=true` 且 `ENVIRONMENT` 为 `local`、`development` 或 `test` 时调用；Render staging 的 `INIT_SCHEMA=false`。该路径保留为 disposable local/test compatibility，不是托管环境建库入口。
- `migration_baseline_status = canonical_staging_reconciled_production_pending`：
  canonical history 的本地 reset、staging later-ID reconciliation、逻辑备份隔离
  恢复及运行验收已通过；production 没有连接、修改或验证。

机器清单见 [`schema-ownership.json`](schema-ownership.json)，只读护栏见
[`scripts/check_schema_ownership.py`](../../scripts/check_schema_ownership.py)。

## 依赖方向

```text
supabase/migrations/  ->  Supabase PostgreSQL schema/RLS
backend/app/db.py     ->  legacy backend/sql/schema.sql (local/dev/test only)
backend/app/routes/   ->  trusted FastAPI boundary -> PostgreSQL
render.yaml           ->  staging ENVIRONMENT=staging, INIT_SCHEMA=false
```

`backend/sql/` 不被 canonical migration 自动包含，也不被普通 staging/production 启动流程调用。

## Canonical forward history

| 文件 | 责任 |
| --- | --- |
| `20260824000100_legacy_schema_baseline.sql` | legacy 区域查询表、profile、索引、触发器和 RLS 起点 |
| `20260824000200_foundation_data_contract.sql` | `data_class`、property/source/evidence/metric/risk/policy foundation |
| `20260824000300_private_project_rls.sql` | owner 字段、服务角色保护和 owner-scoped RLS 起点 |
| `20260824000400_analysis_policy_versions.sql` | policy 日期约束和指标历史保护起点 |
| `20260824000500_provenance_and_immutable_contract.sql` | published provenance、指标维度和不可变约束 |
| `20260824000600_provenance_contract_hardening.sql` | source provenance、rights 状态和 source/output 一致性 |
| `20260824000700_user_submitted_source_rights.sql` | user-submitted 输出的 rights-bearing source/evidence locator |
| `20260825000400_property_intake.sql` | authenticated property-intake 会话、输入、证据、预览和限流 |
| `20260827000500_legacy_private_data_rls.sql` | 已有区域报告表的 legacy private-data RLS hardening |
| `20260828000100_property_photo_location.sql` | project name、坐标、地址候选、精度和 owner-scoped indexes |
| `20260829000100_baseline_access_contract.sql` | 22 张 application table 的最终 RLS/grant/access contract |
| `20260902000100_staging_baseline_reconciliation.sql` | 在不伪造旧 ledger 的前提下协调 staging provenance、constraints、least-privilege RLS/grants 与 Storage policy 边界 |
| `20260902000200_service_role_grant_portability.sql` | 显式固定 22 张 application table 的 trusted `service_role` 权限，消除 managed staging 与 disposable CLI 版本差异 |

文件名必须保持唯一 14 位时间戳并按顺序应用。已应用文件不可编辑；任何线上修复只能新增更晚的 reviewed forward migration。

## Legacy SQL 处置

| 文件 | 分类 | 处置 |
| --- | --- | --- |
| `backend/sql/001_foundation_data_contract.sql` | `historical_pre_migration_source` | 仅作 baseline 来源证据，不与 canonical history 并行执行 |
| `backend/sql/002_private_project_rls.sql` | `historical_pre_migration_source` | 仅作历史 RLS 来源，不作为新的 forward script |
| `backend/sql/003_analysis_policy_versions.sql` | `historical_pre_migration_source` | 仅作历史 policy/immutability 来源 |
| `backend/sql/schema.sql` | `legacy_non_supabase_bootstrap` | 仅 disposable local/development/test compatibility |
| `backend/sql/supabase_schema.sql` | `historical_staging_bootstrap` | 冻结的 staging reference，不作为建库命令 |
| `backend/sql/supabase_user_profiles.sql` | `historical_staging_bootstrap` | 冻结的 profile reference，不作为建库命令 |
| `backend/sql/supabase_field_options.sql` | `generated_support_sql` | 生成/比对输入；托管环境需另有 reviewed forward migration |
| `backend/sql/supabase_indexes.sql` | `manual_support_sql` | 比对/来源输入；不能独立构成 migration |

这些文件本轮不删除、不改名、不改写。历史文件退役或 production 应用前仍需
production 备份策略、schema/RLS 断言、metadata drift、恢复方案和明确批准。

## 开发命令

从仓库根目录运行以下本地只读命令：

```bash
python3 scripts/check_schema_ownership.py
python3 scripts/check_schema_ownership.py --json
npm run check:schema-ownership -- --json
python3 -m unittest discover -s tests/architecture -p 'test_schema_ownership_audit.py' -v
```

`INIT_SCHEMA=true` 不应用 `supabase/migrations/`；它只用于 disposable local/development/test 的 legacy compatibility。不要把 `backend/sql/`、旧 restore 包或 schema dump 当作新的 migration history。

## 审计证据与未评估项

- `check_schema_ownership.py` 对照本地 migration/legacy SQL 清单、标准命名、文档存在性和禁止操作；`status=pass` 只证明 ownership 文档/layout，不证明 SQL/RLS runtime 行为。
- disposable local fresh reset、六组 SQL assertions 与 lint 均通过。
- 获批 staging transaction dry-run、两条审核后 later-ID push、最终 ledger/catalog、
  四身份 RLS、Auth 生命周期和私有 Storage 行为均通过；合成用户和对象已清理。
- 免费层完整逻辑备份恢复到第二套隔离本地 Supabase 后，22 tables、263
  pre-migration columns、72 indexes、20 policies、三条原 ledger ID、0 Auth users、
  0 业务行与 0 Storage objects 均一致。
- 未执行 production 数据库/Auth/Storage、部署、DNS、billing、physical backup/PITR
  或真实恢复邮件投递。详细证据见
  [`migration-reconciliation-report.md`](migration-reconciliation-report.md) 与
  [`rls-verification-matrix.md`](rls-verification-matrix.md)。
