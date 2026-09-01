# 历史 SQL 说明

`backend/sql/ 不是迁移历史`。这些文件保留给既有 staging 的 bootstrap、恢复、生成或比对工作。

新 schema 变更只能新增到 supabase/migrations/（该目录是唯一 forward history）。文件清单和逐文件处置见
[`docs/architecture/schema-ownership-audit.md`](../../docs/architecture/schema-ownership-audit.md)
与 [`schema-ownership.json`](../../docs/architecture/schema-ownership.json)。

| Files | Classification | Rule |
| --- | --- | --- |
| `backend/sql/schema.sql` | legacy non-Supabase bootstrap | 仅用于 disposable local/test compatibility；不得新增 production 字段 |
| `backend/sql/supabase_schema.sql`、`backend/sql/supabase_user_profiles.sql` | historical staging bootstrap/reference | 不得作为新的 migration 路径 |
| `backend/sql/001_foundation_data_contract.sql`–`003_analysis_policy_versions.sql` | historical pre-migration work | 仅作为 baseline reconstruction 的来源证据 |
| `backend/sql/supabase_field_options.sql`、`backend/sql/supabase_indexes.sql` | generated/manual support SQL | 进入 managed environment 前必须重新生成或改成经过审核的 forward migration |

当前文件不删除、不改写，因为 staging lineage 尚未完成协调。它们不能由生产应用启动流程执行，也不能在新的会员、计费、任务、联系授权或后台功能中继续扩展。

## 离线审计与退役门槛

从仓库根目录运行以下命令即可检查 canonical migration 和 legacy SQL 清单；命令只读本地文件，不连接数据库：

```bash
python3 scripts/check_schema_ownership.py
npm run check:schema-ownership
```

任何历史文件的退役都必须先在 `supabase/migrations/` 新增经过审核的
forward-fix，并通过空库 reset、schema/RLS 断言、metadata-only drift 对比和
backup/restore 验证；取得明确线上批准后才可评估删除或改名。不得编辑已应用
migration、删除恢复包，或把 staging 结果当作 production 证明。
