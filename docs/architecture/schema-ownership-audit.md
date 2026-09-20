# Schema ownership 审计

**审计日期：** 2026-09-20
**范围：** `supabase/migrations/`、`backend/sql/`、`backend/app/`、`scripts/` 及当前开发/部署文档。
**方式：** 离线 manifest 与源码审计；不连接、修改或部署任何数据库环境。

## 已定稿的归属

`supabase/migrations/` 是唯一 canonical forward migration history。应用启动在任何环境都不执行建表或其他 DDL；`backend/sql/` 是冻结的历史参考/支持材料，不能作为运行时、开发或托管环境的 schema 来源。

机器护栏是 [`scripts/check_schema_ownership.py`](../../scripts/check_schema_ownership.py)。它必须同时验证：

- manifest 覆盖每个 `backend/sql/*.sql` 文件且不将其声称为 forward history；
- canonical migration 文件列表、14 位版本命名和版本唯一性与 manifest 一致；
- `backend/app/` 与 `scripts/` 的可执行 Python/JavaScript 源码没有引用 `backend/sql/` 下的 SQL 文件；
- 必需文档和禁止操作声明仍存在。

任何违反都会产生非零退出码，因此归属不是仅供记录的文档约定。

## 基线状态与取证

```text
migration_baseline_status = canonical_staging_reconciled_production_reconciled
repository supabase/migrations/*.sql count = 47
recorded production supabase_migrations.schema_migrations count = 47
max(version) on both sides = 20260920000300
set(repository_versions) - set(production_versions) = empty
set(production_versions) - set(repository_versions) = empty
```

上述双向差集均为空才判定两侧对齐。此为已提供的 production ledger 取证记录，不是本审计命令的在线数据库连接或写操作。

## 依赖方向

```text
supabase/migrations/  ->  Supabase PostgreSQL schema/RLS
backend/app/          ->  trusted application queries only
scripts/              ->  approved operational/data tasks, never legacy schema bootstrap
backend/sql/          ->  frozen historical reference only
```

## Legacy SQL 清单处置

| 文件 | 分类 | 处置 |
| --- | --- | --- |
| `backend/sql/001_foundation_data_contract.sql` | `historical_pre_migration_source` | baseline 来源证据，不并行执行 |
| `backend/sql/002_private_project_rls.sql` | `historical_pre_migration_source` | 历史 RLS 来源，不作为 forward script |
| `backend/sql/003_analysis_policy_versions.sql` | `historical_pre_migration_source` | 历史 policy/immutability 来源 |
| `backend/sql/schema.sql` | `legacy_non_supabase_bootstrap` | 退役 bootstrap 参考，应用不得执行 |
| `backend/sql/supabase_schema.sql` | `historical_staging_bootstrap` | 冻结 staging 参考 |
| `backend/sql/supabase_user_profiles.sql` | `historical_staging_bootstrap` | 冻结 profile 参考 |
| `backend/sql/supabase_field_options.sql` | `generated_support_sql` | 生成/比对输入；发布必须转为审核后 forward migration |
| `backend/sql/supabase_indexes.sql` | `manual_support_sql` | 比对/来源输入，不能独立构成 migration |

## 本地审计命令

```bash
python3 scripts/check_schema_ownership.py
python3 scripts/check_schema_ownership.py --json
PYTHONPATH=. backend/.venv/bin/python -m pytest -q tests/unit/test_schema_initialization.py tests/architecture/test_schema_ownership_audit.py
```

审计只证明仓库契约、文件清单和运行时引用边界；SQL/RLS 运行行为仍须以独立的本地或获授权环境验证。
