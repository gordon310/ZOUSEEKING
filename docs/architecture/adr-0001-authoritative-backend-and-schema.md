# ADR-0001：权威后端与 Schema 所有权

**状态：Accepted**

**日期：** 2026-08-29

**适用范围：** V1 会员、计费、机构、任务池、联系授权和后台功能的架构前置决策。

**产品规格：** [小象避坑／小象数据 V1 会员、计费与任务协作设计规格](../superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md)

本 ADR 只确定边界，不授权实现会员、支付、任务或联系信息业务。任何业务实现必须在本 ADR 和后续对应子项目通过后进行。

## 1. 背景与当前证据

仓库当前存在多条相互竞争的路径：

- `backend/app/routes/intake.py` 已使用 FastAPI 处理私有 intake。
- `backend/app/auth.py` 在 API 边界验证 Supabase 身份。
- `web/app.js` 仍保留 authenticated PostgREST 和 Edge 回退。
- `supabase/functions/jphouse-run/index.ts`、`scripts/run_jphouse_worker.py` 和 `backend/app/main.py::run_generation_job` 重复执行区域报告。
- 2026-08-30 reconciliation 之前，`supabase/migrations/20260825000400_property_intake.sql` 依赖 `public.properties` 与 `public.residential_details`，但该目录没有更早的 migration 创建这些表；现已通过更早的 canonical baseline migration 补齐 fresh-install history。
- 当前 Render 服务使用 FastAPI，数据库连接仍指向 Supabase staging；未来迁移 Render PostgreSQL 不是本 ADR 的即时操作。

如果在这些路径上并行增加会员或支付逻辑，会产生重复扣量、绕过授权、webhook 重放不一致和 schema 漂移风险。

## 2. 决策

### 2.1 总体流向

```text
Browser
  -> Supabase Auth: signup, login, refresh, logout
  -> local/static content and approved public read-only options
  -> FastAPI: all private or authenticated product operations
       -> Supabase PostgreSQL transaction + RLS defense in depth
       -> transactional outbox/job row
            -> one durable worker

Payment provider
  -> FastAPI verified webhook
       -> unique provider event + business transaction + outbox
```

### 2.2 边界责任

| 能力 | 唯一权威归属 | 说明 |
| --- | --- | --- |
| 身份注册、登录、刷新、登出 | Supabase Auth | Supabase Auth 是唯一身份签发方；FastAPI 验证其身份声明。 |
| 私有产品读写与业务授权 | FastAPI | FastAPI 是所有私有产品读写的唯一应用边界。 |
| 数据存储与事务约束 | Supabase PostgreSQL | 额度、所有权、幂等键和审计关系在事务中保存；RLS 是纵深防御。 |
| 前向 schema 变更 | `supabase/migrations/` | `supabase/migrations/` 是唯一前向迁移历史。 |
| 支付 webhook | FastAPI 验签端点 + outbox | 支付 webhook 先验签，再写入去重事件与 outbox。 |
| 异步任务 | 一个 PostgreSQL-backed durable worker | FastAPI 创建任务；worker 原子 claim、幂等执行并记录失败。 |
| 公开静态数据生成 | 现有离线脚本 | 只处理已授权、已标注来源的数据，不写会员业务状态。 |

### 2.3 浏览器 allowlist

浏览器只允许直连：

- Supabase `auth/v1`，用于身份流程；
- `query_field_options` 的匿名只读查询；
- 静态内容和已审核公开数据。

浏览器不得直接读取或写入 profile、project、query、report、organization、usage、payment、task、consent 或 audit 数据。登录状态不构成绕过 FastAPI 的权限；隐藏按钮、查询参数和前端 email 均不是授权控制。

## 3. Worker 与 webhook 契约

- FastAPI 在同一 PostgreSQL transaction 中写入业务状态和 outbox/job 记录。
- worker 通过原子条件或 `FOR UPDATE SKIP LOCKED` claim 已提交任务；不能使用“先 select pending、再无条件 update”的流程。
- worker handler 必须幂等、有限重试、区分永久/暂时失败、可安全 replay，并且不能接收浏览器凭证。
- FastAPI webhook 在解析和信任 payload 前验证原始签名；provider event ID 有唯一约束；同一 event 重放返回已记录结果，不重复产生副作用。
- outbox 侧效应在主 transaction commit 后投递。FastAPI `BackgroundTasks` 不是 V1 durable worker。

## 4. Schema 与 migration 契约

当前 V1 的数据库实现是 Supabase PostgreSQL，`supabase/migrations/` 是唯一前向 migration history。仓库 canonical history 已在 disposable local Supabase 从空库重建并通过 SQL/RLS assertions，但 linked/staging migration ledger 尚未协调，当前状态为：

```text
migration_baseline_status = canonical_local_pass_live_reconciliation_required
```

本地完成项包括：

1. 从审核后的仓库 SQL 和只读 staging schema inventory 推导缺失基础表；
2. 新增确定性的早期 migration，并保持三条已应用 migration 字节不变；
3. 在空的 disposable local Supabase 完成 fresh reset；
4. 运行 foundation、intake、provenance、匿名/owner/other-user/service-worker SQL/RLS 断言；
5. 对比只读 staging inventory，不导出客户数据；
6. 完成 local backup/restore 演练与 forward-fix runbook。

这只证明仓库 canonical history 可 fresh install，不代表 staging 或 production 已协调。provider-supported staging backup、isolated clone restore、existing-row provenance classification、reviewed later-ID forward migration 和明确 live-write 批准仍是线上门槛。禁止 linked push、migration repair、staging reset、production reset 或 live SQL；也不得据此增加 V1 业务 migration。

`backend/sql/` 只作为历史 bootstrap/reference，不是新的 migration 路径。

## 5. 旧路径过渡

以下组件保留给现有 staging 兼容，但冻结，不得承载 V1 新功能：

- `web/app.js:direct_private_supabase_and_edge_fallback`；
- `supabase/functions/jphouse-run:regional_report_edge_executor`；
- `scripts/run_jphouse_worker.py:regional_report_rest_worker`；
- `backend/app/main.py:in_process_regional_report_executor`。

退出条件是：私有 web caller 已由 FastAPI 等价路径替代、legacy queue 已清空或迁移、唯一 durable worker 已验证、部署和下线操作已获明确批准。旧路径的存在不代表其适合新增功能或生产使用。

## 6. 被拒方案

- **PostgREST/RLS-only 业务后端：** 不能集中执行额度、机构、任务和支付幂等检查；客户端写入边界也更容易被绕过。
- **Edge Function 业务后端：** 与现有 FastAPI/Python 服务重复，无法成为唯一任务和计费写入路径。
- **FastAPI 与 Edge 双写：** 会产生报告、用量和 webhook 状态分歧。
- **现在立即迁移 Render PostgreSQL：** 会同时引入 Supabase Auth/RLS/Storage 解耦、基线迁移和恢复演练风险；这不是对未来 Render 迁移的永久否定。

未来若将数据迁移至 Render PostgreSQL，应另立 ADR 和迁移计划。可以保留 Supabase Auth、先迁业务 PostgreSQL，但必须重新验证 Supabase 专属的 `auth.users`、`auth.uid()`、RLS、Storage 引用、权限、备份、跨地区数据处理和回滚路径。

## 7. 后果与发布门槛

此选择复用现有 FastAPI intake、Supabase Auth/Storage/PostgreSQL 和 Python 服务，但增加 FastAPI 与 durable worker 的运维责任。现有浏览器 token 存储方式仍是发布前风险；仓库 canonical baseline 已通过本地验证，但 linked/staging ledger reconciliation 仍未解决；接受本 ADR 不等于系统安全、合规或 production-ready。

在身份/机构、产品/额度、支付、任务、联系授权或后台子项目中，所有新增表和写入路径必须引用本 ADR。任何需要改变数据库供应商、身份供应商、文件供应商或 migration 工具的变更，都必须新建 ADR，不得静默修改本决策。

第一阶段可发布能力由 [ADR-0002：第一阶段只发布 C 端 intake 与免费预览](adr-0002-phase-one-release-scope.md) 进一步收窄。ADR-0001 规定“能力最终归谁”，不表示这些能力已经进入当前 release allowlist。

## 8. Verification 与下一道门槛

本 ADR 的离线验证结果：

- 系统 Python 的 `python3 -m pytest` 因未安装 pytest 未能执行；使用仓库已有的 `backend/.venv/bin/python` 重跑架构契约、schema 初始化和 legacy job 回归，结果为 `11 passed`。
- `node --test tests/edge/jphouse-run-authority.test.mjs` 结果为 `1 passed`。
- `node --check web/app.js` 和 `backend/.venv/bin/python -m compileall -q backend scripts src` 通过。
- `git diff --check HEAD~3..HEAD` 通过。

上述为 ADR 最初的验证记录；当时没有执行 SQL/RLS 行为、fresh migration reset、linked Supabase 检查、backup/restore、浏览器交互或部署验证。

2026-08-30 离线 reconciliation 补充验证：canonical 11-file history 已通过 fresh local reset、schema/provenance assertions、匿名/owner/other-user/service-worker RLS matrix，以及 local full-dump restore drill。现状更新为 `migration_baseline_status = canonical_local_pass_live_reconciliation_required`。这不代表 staging 或 production 已协调；本次没有执行 linked Supabase、migration repair、staging reset、production 操作或部署。live baseline gate 通过前，不得增加 V1 membership、billing、task、contact-consent 或 admin migration。
