# Runtime Conflict Inventory

本清单配合 [ADR-0001：权威后端与 Schema 所有权](adr-0001-authoritative-backend-and-schema.md) 使用。它记录当前代码和文档的过渡状态，不把旧路径误认为 V1 权威实现。

## 竞争路径

| Current component | Current role | ADR status | V1 rule | Exit condition |
| --- | --- | --- | --- | --- |
| `web/app.js` direct authenticated PostgREST and Edge fallback | legacy profile/query/report compatibility | frozen | 不新增私有读写 | FastAPI 等价接口验证并移除 caller |
| `supabase/functions/jphouse-run/` | legacy regional report generator | frozen | 不加入会员、额度、账单、任务、授权或后台逻辑 | 清空/迁移 queue 并经批准下线函数 |
| `scripts/run_jphouse_worker.py` | local service-role REST report worker | frozen | 不加入 V1 worker handler | canonical worker 验证且 legacy queue 退役 |
| `backend/app/main.py::run_generation_job` | in-process report executor | frozen | 不执行 V1 durable job | canonical queue/worker 接管报告生成 |
| `backend/sql/` and `supabase/migrations/` | competing schema histories | blocked | 未来只允许 `supabase/migrations/` | baseline reconciliation 通过 |
| `docs/supabase-setup.md` | 混合历史 setup 和当前 staging 指引 | conflict documented | ADR-0001 优先 | 重叠工作区改动整合后更新 |
| `docs/render-postgres-deploy.md` | deferred Render PostgreSQL option | V1 rejected | 禁止仅替换 connection string | 新 ADR 和 migration plan 获批 |

以上路径不得承载 V1 新功能。

## 当前允许的浏览器直连

- Supabase Auth `auth/v1`：注册、登录、刷新和登出。
- `query_field_options`：匿名公开只读查询。
- 静态内容和已审核公开数据。

profile、project、query、report、organization、usage、payment、task、consent 和 audit 数据均不属于浏览器直连范围。

## 迁移与退出说明

当前 `supabase/migrations/` 还不能从空库重建 staging schema；`backend/sql/` 仍保留为历史 bootstrap/reference。先完成 migration baseline reconciliation，再移除旧的私有 caller、迁移 legacy queue、验证唯一 durable worker，并在取得部署批准后下线兼容路径。
