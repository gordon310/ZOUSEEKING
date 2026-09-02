# Runtime Conflict Inventory

本清单配合 [ADR-0001：权威后端与 Schema 所有权](adr-0001-authoritative-backend-and-schema.md) 使用。它记录当前代码和文档的过渡状态，不把旧路径误认为 V1 权威实现。

## 竞争路径

| Current component | Current role | ADR status | V1 rule | Exit condition |
| --- | --- | --- | --- | --- |
| `web/app.js` direct authenticated PostgREST and Edge fallback | legacy profile/query/report compatibility | frozen | 不新增私有读写 | FastAPI 等价接口验证并移除 caller |
| `supabase/functions/jphouse-run/` | legacy regional report generator | frozen | 不加入会员、额度、账单、任务、授权或后台逻辑 | 清空/迁移 queue 并经批准下线函数 |
| `scripts/run_jphouse_worker.py` | local service-role REST report worker | frozen | 不加入 V1 worker handler | canonical worker 验证且 legacy queue 退役 |
| `backend/app/main.py::run_generation_job` | in-process report executor | frozen | 不执行 V1 durable job | canonical queue/worker 接管报告生成 |
| `backend/sql/` and `supabase/migrations/` | historical bootstrap vs canonical history | local + staging canonical / production pending | 只允许 `supabase/migrations/` 新增前向变更 | production 经独立备份、恢复、reviewed migration 和批准完成协调 |
| `docs/supabase-setup.md` | 混合历史 setup 和当前 staging 指引 | conflict documented | ADR-0001 优先 | 重叠工作区改动整合后更新 |
| `docs/render-postgres-deploy.md` | deferred Render PostgreSQL option | defer; see [ADR-0002](adr-0002-render-postgres-future-migration.md) | 仅作非执行评估；禁止替换 connection string、创建 DB 或迁移数据 | 全部迁移门槛与独立线上变更批准均满足 |

以上路径不得承载 V1 新功能。

## 当前允许的浏览器直连

- Supabase Auth `auth/v1`：注册、登录、刷新和登出。
- `query_field_options`：匿名公开只读查询。
- 静态内容和已审核公开数据。

profile、project、query、report、organization、usage、payment、task、consent 和 audit 数据均不属于浏览器直连范围。

## 迁移与退出说明

当前 `supabase/migrations/` 的 canonical history 已能在 disposable local Supabase
从空库重建并通过 SQL/RLS assertions；`backend/sql/` 仅保留为历史
bootstrap/reference。状态为 `canonical_staging_reconciled_production_pending`：
staging 在 2026-09-02 通过备份、隔离恢复、later-ID reconciliation 和运行验收，
但 production 没有连接或修改。旧私有 caller、legacy queue 与 durable worker 的
退出仍需各自的等价性、监控、回滚和部署批准，不能由 M1 自动放行。

`backend/sql/` 与 canonical migration 的逐文件重叠、保留和 forward-fix 门槛见 [`schema-ownership-audit.md`](schema-ownership-audit.md)；Render PostgreSQL 的未来评估见 [`adr-0002-render-postgres-future-migration.md`](adr-0002-render-postgres-future-migration.md)；文件审计不替代运行证据，M1 staging 证据也不代表 production 已验证。
