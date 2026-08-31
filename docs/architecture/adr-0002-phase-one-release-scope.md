# ADR-0002：第一阶段只发布 C 端 intake 与免费预览

**状态：Accepted（决策已接受；live release 尚未授权）**

**日期：** 2026-08-30

**关系：** 补充并收窄 [ADR-0001：权威后端与 Schema 所有权](adr-0001-authoritative-backend-and-schema.md)，不取代 ADR-0001。

**机器契约：** [phase-one-release-boundaries.json](phase-one-release-boundaries.json)

本决策值得单独记录：它会约束公开发布物、API 路由、后台执行器和部署配置，跨越浏览器、FastAPI、Supabase 与 worker 边界，且半年后无法只从任一代码文件恢复“为何只开放免费预览”。

## 1. 结论

第一阶段正式上线范围冻结为 C 端匿名房产资料 intake 与免费预览，发布阶段名为 `consumer_intake_preview`。FastAPI 是唯一业务 API；Supabase 在本阶段只作为 FastAPI 后方的 PostgreSQL 与私有 Storage，Supabase Auth 仍是 ADR-0001 指定的唯一身份签发方，但注册、账户转正、项目保存不属于本阶段验收范围。

以下能力不进入第一阶段：匿名会话转正式项目、项目工作台、完整版报告、旧区域报告生成、B 端会员/计费/机构/额度/订阅/导出/任务、管理员采集/审核/发布/派单真实操作。B 端与管理员页面可继续留在 staging 作为 `synthetic_fixture` 评审资产，但只能改变内存中的演示状态；网络访问仅限 allowlist 中的公开静态资源，不能读取私有 API、发出跨域请求或任何网络写入。

## 2. 背景与审计证据

上线前审计覆盖 `backend/app/`、`web/`、`supabase/functions/jphouse-run/`、`scripts/run_jphouse_worker.py`、`render.yaml`、迁移说明、ADR-0001、staging 进度和相关测试。

- `progress.md` 记录的 staging 闭环只使用 `synthetic_fixture`，已验证匿名会话、文字/PDF、字段确认和免费预览；没有真实账号、真实文件或真实房产资料验收。
- B 端与管理员规格明确为静态本地演示；真实机构、支付、额度、导出、任务、后台 CRUD 和服务端授权均未实现。
- `backend/app/main.py`、Edge Function 和 local worker 都能处理旧区域报告；`web/app.js` 还包含私有 PostgREST 与 Edge fallback，存在重复写入和执行所有权冲突。
- `supabase/migrations/` 仍处于 `migration_baseline_status = reconciliation_required`；ADR-0001 已禁止在基线协调前扩展 V1 会员、支付和任务 migration。
- 审计时 `render.yaml` 没有发布阶段，`web/config.js` 固定 staging Supabase 项目地址，B 端可通过浏览器配置或 `localStorage` 恢复旧远端路径。

审计结论为 **BLOCK（正式生产发布）**：UI 验收和 synthetic staging smoke 不能替代生产 schema/Auth/RLS/Storage、恢复演练、容量与真实资料闭环。此次修改只把边界变成可执行门闩，不把发布结论升级为 production-ready。

## 3. 要求与约束

- R1：第一阶段用户可以匿名创建 24 小时 intake 会话，提交已允许的文字、URL、PDF/JPG/PNG，确认字段并获得不伪造税费和可比数据的免费预览。
- R2：浏览器的业务请求只能进入 FastAPI；不得以 PostgREST、Edge Function、email 或客户端字段绕过业务授权。
- R3：B 端和管理员演示不得造成数据库、Auth、Storage、任务、支付、邮件或下载副作用。
- R4：任何数据库、Auth、RLS、Storage、DNS、secret、部署或 break-glass 激活都必须取得针对确切环境与操作的明确授权。
- R5：冻结必须可离线验证，并能在不删除旧实现、不迁移 live 数据的情况下回滚。

当前没有经确认的生产用户数、QPS、年度数据量、可用性目标或成本预算。本 ADR 不据 staging free plan 推导生产容量，也不批准容量设计；缺少这些数字本身是生产发布 checklist 的未完成项。

## 4. 运行时契约

### 4.1 FastAPI allowlist

`RELEASE_PHASE=consumer_intake_preview` 时只开放：

- health 与带内部 token 的 provenance diagnostics；
- `POST /api/intake/sessions`；
- intake session 下的 `inputs`、`files`、`location`、`fields` 与 `preview`。

`/convert`、`/projects/{id}`、`/api/query`、`/api/jobs/*`、`/api/my/queries` 和 `/api/reports/*` 均返回统一 404，且在认证、数据库或 background task 前被拦截。`staging` 或 `production` 未配置 `RELEASE_PHASE` 时只保留 health/diagnostics，其他业务请求 fail closed。完整列表以机器契约为准，测试会检查它和运行时代码一致。

### 4.2 旧路径冻结

| 路径 | 第一阶段状态 | 机械门闩 | 重新启用条件 |
| --- | --- | --- | --- |
| 浏览器私有 PostgREST 与 Edge fallback | frozen | B/admin 页面 `release-boundary.js` 仅允许同源 `/content-library.json` 与 `/field-options.json` GET；发布配置不固定 Supabase 项目 | 新 ADR、等价 FastAPI 接口和浏览器回归通过 |
| `supabase/functions/jphouse-run` | frozen | `JPHOUSE_LEGACY_EXECUTION_ENABLED` 必须精确为 `true`，否则 410 | 仅经批准的迁移/排空窗口；不得作为常规业务后端 |
| `scripts/run_jphouse_worker.py` | frozen | `ENABLE_FROZEN_JPHOUSE_WORKER` 必须精确为 `true`，且先于凭证读取检查 | 仅经批准的恢复/迁移操作，记录输入、范围和回滚 |
| FastAPI in-process regional executor | frozen | release allowlist 在 handler 与 `BackgroundTasks` 前阻断 | 由一个 durable worker 替代并另行验收 |
| B 端与管理员按钮 | demo only | 浏览器级网络写阻断；只允许内存中 `synthetic_fixture` 状态 | 完成服务端数据模型、授权、审计和对应 ADR |

环境变量不是操作授权。即使代码具有 break-glass 开关，任何 staging/production 激活仍须由人工确认确切环境、持续时间、数据范围、负责人和回滚步骤；本 ADR 不授权设置这些变量。

## 5. 考虑过的方案

### A. 只发布 C 端 intake 与免费预览（采用）

最好地复用已经通过 synthetic staging smoke 的窄链路，不依赖未协调的会员/计费/任务 schema，也不需要启动重复报告执行器。代价是暂时没有保存项目、完整报告和商业化闭环。

### B. 同时发布账号转正、项目保存和完整版报告

它的最佳情形是给 C 端更完整的价值闭环，并为后续付费准备入口。但当前 Auth 生命周期、migration baseline、项目权限、正式报告数据与 worker 均未达到发布门槛；把 UI 验收当作后端验收会扩大跨用户与重复写入风险。

### C. 同时发布 B 端和管理员功能

它的最佳情形是一次展示完整平台叙事，且 staging UI 已可评审。但真实机构、额度、支付、任务、导出、管理员授权和审计并不存在；发布按钮会制造能力错觉，因此只保留无网络副作用的 demo。

### D. 以 PostgREST/RLS 或 Edge Function 加速上线

它能少写 FastAPI 接口，但会恢复 ADR-0001 已拒绝的重复业务边界，无法集中执行额度、幂等、任务和审计规则，也使浏览器重新拥有私有表写入口，因此不采用。

## 6. 后果、非目标与翻转条件

好处是发布面、数据副作用和排障面都显著缩小；任何未知 `RELEASE_PHASE` 会安全关闭业务 API。代价是旧实现仍保留在仓库，B/admin staging 页面仍需明确标记为演示，生产静态发布物还要单独排除或限制这些评审页面。

本 ADR 不解决 migration baseline、不创建 production schema/bucket/Auth 配置、不部署、不迁移队列、不删除旧路径、不实现支付/额度/任务/完整版报告，也不声明数据具有统计代表性或系统 production-ready。

只有当 migration baseline 可从空库重建、production Auth/RLS/Storage 与恢复计划通过、唯一 durable worker 和 FastAPI 等价接口通过、真实但非敏感的受控验收完成、容量与隐私要求确认后，才考虑新 ADR 扩大范围。任何一项未满足都不足以推翻当前窄范围。

## 7. Rollout 与 rollback

本地落地顺序是：运行时 allowlist → Edge/local worker 默认关闭 → B/admin 网络门闩 → Render staging 阶段声明 → 离线契约测试。live rollout 必须按 [第一阶段发布检查单](../release/phase-one-release-checklist.md) 逐项完成并重新取得部署授权。

回滚时应回退本次代码/静态配置并保持旧执行器关闭；不得通过打开 Edge/local worker 开关来“恢复服务”。若发布阶段配置缺失或异常，让业务 API 保持 fail closed，先恢复配置与验证，再决定是否重新开放。

## 8. Open questions

- production 静态发布物是只打包 C 端文件，还是对 B/admin staging 评审页做独立访问控制？
- production 域名、CORS origin、FastAPI base URL 和环境配置的负责人是谁？
- 匿名资料的隐私文本、同意版本、删除请求入口和保留期是否已经由产品/法务确认？
- 首月用户量、峰值 QPS、文件量、Storage 增长、SLO 和预算是多少？
- 免费预览是否允许生产收集真实资料，还是先限定受邀测试？

这些问题在获得明确答案前保留为 release blocker，不由实现者自行假设。
