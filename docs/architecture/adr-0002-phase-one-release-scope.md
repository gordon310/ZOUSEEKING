# ADR-0002：第一阶段发布 C 端与后台管理平台（2026-09-26 修订）

**状态：Accepted（2026-09-26 修订首发范围；live release 仍未授权）**

**日期：** 2026-08-30（原始决策）· **修订：** 2026-09-26

**关系：** 补充并收窄 [ADR-0001：权威后端与 Schema 所有权](adr-0001-authoritative-backend-and-schema.md)，不取代 ADR-0001。

**机器契约：** [phase-one-release-boundaries.json](phase-one-release-boundaries.json)

## 0. 修订摘要（2026-09-26）

原始结论为「第一阶段只发布 C 端 intake 与免费预览」。用户于 **2026-09-23** 拍板改为 **C 端（小象避坑 Web/PWA）与后台管理平台同时正式对外上线**（硬出口 2026-10-07，商店上架为并行轨道、不阻塞；B 端「小象数据」随后），并于 **2026-09-24** 追加四项决策：开放注册（不切 `disable_signup`，注册去邀请码强制；2026-09-25 追加执行：关闭 GoTrue 公共注册旁路 `disable_signup=true`，我方注册端点保持开放）、授权 C13、批准 C04 成本上限、法务地区 = 日本。原始 C-only 结论**作废**；**§1 起为本修订后的有效结论**，原始论证保留在 §5/§6 以免丢失当时依据。

修订后的四个面复核（本机实跑 + 生产只读实测，证据见 `docs/release/go-no-go-checklist-2026-10-07.md`《2026-09-26 范围面复核》与本日 `progress.md`）：

| # | 面 | 实测状态 |
|---|---|---|
| R1 | ADR 文字 | 本文件（2026-09-26 修订，L1–L3 与 §1） |
| R2 | 机器契约 `phase-one-release-boundaries.json` | `api_allowlist` **42 条**（health/diagnostics 4 + intake 6 + exports 3 + analysis 1 + usage 1 + 后台 admin/org/service 27），与运行时 `PHASE_ONE_API_CONTRACT` **逐条相同、零重复** |
| R3 | 运行时 `backend/app/release_scope.py` | C 端首发面所需路由**不在** allowlist：`POST /api/auth/invite-register`、`POST /api/auth/login`、`POST /api/query`、`GET /api/my/queries`、`GET /api/reports/{query_key}`(+`/download`)、`POST /api/billing/*`、`GET /api/org/region-stats` 实测均 `in_phase_one_allowlist=False` |
| R4 | 生产实际 phase | `docker exec deploy-api-1 printenv RELEASE_PHASE` = **`consumer_active`**、`ENVIRONMENT=` **`staging`**（2026-09-26 只读实测）→ 该 phase 下 `request_allowed()` 全放行，**本 allowlist 在生产未生效**；实际门禁来自服务层鉴权 / RLS / 额度 |

**未闭合项（交用户 / 工程，不擅自决定）**：

- **U1 首发面 ≠ allowlist**：10-07 的 C 端（注册/登录/查询/报告/付费）与后台所需路由不在 `consumer_intake_preview` allowlist 内，而该 allowlist 是 ADR 声明的发布边界。需二选一：(a) 定义 10-07 专用 phase + 显式 allowlist（含上列路由）；(b) 明确申明由 `consumer_active` + 服务层鉴权承担，并把这一点写进 ADR 与检查单。**当前形态下 (a) 与 (b) 都不能说「ADR 与运行时一致」**。
- **[已闭合] U2 代码注释与生产现实矛盾**：`release_scope.py` 的 `consumer_active` 注释现说明其为 2026-10-07 C 端 Web/PWA 上线的当前生产 phase、全放行且不做 allowlist 过滤，并列明服务层边界。
  证据：`backend/app/release_scope.py` 仅更新 `CONSUMER_ACTIVE` 上方注释；`tests/architecture/test_release_scope_regression.py` 守护该注释不得再含旧生产禁用表述。
- **U3 生产 `ENVIRONMENT` 标签**：生产主机 `ENVIRONMENT=staging`（属标签不一致；当前仅影响 fallback/运维判读）。
- **U4 B 端无技术门禁**：`consumer_active` 下前端 `release-boundary.js` 不设闸，`data-query`/`analysis`/`exports`/`organization` 等 B 端页在生产可直连 API——「B 端随后上线」目前只是计划口径，**没有可执行门禁**。
- **[已闭合] U5 回归缺口**：go-no-go C02 的 API release-scope 回归现覆盖 unknown phase、`/convert` 与 legacy 路由。
  证据：`tests/architecture/test_release_scope_regression.py` 直接调用 `request_allowed()`，覆盖 preview allow/block 矩阵、unknown/unconfigured managed fail closed，以及 `development`/`consumer_active` 全放行；契约逐条一致性继续由 `tests/architecture/test_authoritative_backend_policy.py` 的既有单一断言覆盖。
- **[已闭合] U6 文档漂移**：09-11 架构快照现标注以 ADR-0002 与机器契约为准，并将 allowlist 更新为 42 条（C 端 15 + 后台 27）及当前 phase 语义。
  证据：`docs/architecture/2026-09-11-system-architecture-and-logic.md` 标题下增加快照提醒，并更新 API 全局说明与 release_scope 段落；第 989 行前端 git 树默认 scope 经核对仍为 `consumer_intake_preview`，无需改动。

本决策值得单独记录：它会约束公开发布物、API 路由、后台执行器和部署配置，跨越浏览器、FastAPI、Supabase 与 worker 边界，且半年后无法只从任一代码文件恢复“为何只开放免费预览”。

## 1. 结论（2026-09-26 修订后有效）

第一阶段正式上线范围 = **C 端（小象避坑 Web/PWA）+ 后台管理平台 同时对外上线**。

- **C 端**：开放注册（无邀请码；注册一律经 FastAPI 注册端点，服务端限流与 consent 记录强制，公共 Auth 直连注册在生产已关闭）、匿名 intake 与免费预览、物件查询与报告生成（PostgreSQL outbox + durable worker）、单次购买付费与退款/客服路径。
- **后台管理平台**：管理侧登录 + 成员/审计/财务/采集/服务任务等后台操作；`ADMIN_ENABLED` 是服务层开关（生产已置 `true`，未鉴权请求仍 401）。
- **B 端（小象数据：机构/会员/额度/导出/任务）随后上线**，不在 10-07 首发面；当前**没有**可执行门禁把 B 端挡在首发面之外（见 §0 U4）。
- 发布 phase 名称与 API allowlist 的口径、以及「ADR 文字 ↔ 机器契约 ↔ 运行时 ↔ 生产实际」的实测差异，见 §0 与 §4.1。

FastAPI 仍是唯一业务 API；Supabase 只作为 FastAPI 后方的 PostgreSQL 与私有 Storage，Supabase Auth 仍是 ADR-0001 指定的唯一身份签发方。

**历史结论（2026-08-30，已作废）**：原为「只发布 C 端匿名 intake 与免费预览」，并把注册、账户转正、项目保存、B 端与管理员真实操作排除在第一阶段之外。作废依据 = 用户 2026-09-23 / 2026-09-24 的范围决策（见 §0）。

以下能力**仍在本阶段之外**（与修订前一致的部分）：匿名会话转正式项目（`/convert` 在 `consumer_intake_preview` 下 404，见 §4.1）、旧区域报告生成、Edge Function 与 local worker 执行路径（已移除）。B 端业务能力的正式开放时点仍在 10-07 之后。

## 2. 背景与审计证据

上线前审计覆盖 `backend/app/`、`web/`、已退役的 `supabase/functions/jphouse-run/`、原 `scripts/run_jphouse_worker.py`、`render.yaml`、迁移说明、ADR-0001、staging 进度和相关测试。

- `progress.md` 记录的 staging 闭环只使用 `synthetic_fixture`，已验证匿名会话、文字/PDF、字段确认和免费预览；没有真实账号、真实文件或真实房产资料验收。
- B 端与管理员规格明确为静态本地演示；真实机构、支付、额度、导出、任务、后台 CRUD 和服务端授权均未实现。
- 审计时 `backend/app/main.py`、Edge Function 和 local worker 曾都能处理旧区域报告；本次已移除 Edge/local worker 执行路径，报告由 PostgreSQL outbox worker 唯一消费，`web/app.js` 的私有 PostgREST 与 Edge fallback 仍是冻结风险。
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

### 4.1 FastAPI allowlist（2026-09-26 实测口径）

运行时 `PHASE_ONE_API_CONTRACT`（`backend/app/release_scope.py:13-68`）当前 = **42 条**，与机器契约 `phase-one-release-boundaries.json` 的 `api_allowlist` 逐条相同：

- health 与带内部 token 的 provenance diagnostics（4 条，任何 phase 都放行）；
- intake：`POST /api/intake/sessions` 及 session 下的 `inputs`、`files`、`location`、`fields`、`preview`（6 条）；
- `POST/GET /api/exports`、`GET /api/exports/{export_id}`、`POST /api/analysis`、`GET /api/usage/summary`（5 条）；
- 后台面 admin / org / service（27 条，`ADMIN_ENABLED` 与角色校验仍在服务层强制）。

`RELEASE_PHASE=consumer_intake_preview` 时只有上述 42 条可进入路由；`/convert`、`/projects/{id}`、`/api/query`、`/api/jobs/*`、`/api/my/queries`、`/api/reports/*`、`/api/auth/*`、`/api/billing/*`、`/api/org/region-stats` 均返回统一 404，且在认证、数据库或 background task 前被拦截。`staging` 或 `production` 未配置 `RELEASE_PHASE` 时只保留 health/diagnostics，其他业务请求 fail closed。未知 phase 同样 fail closed。

**与修订后范围的差异（见 §0 U1，未闭合）**：上述 allowlist 编码的是修订前的 C-only intake 范围，因此**不能**用于 10-07 首发（它不含注册、查询、报告、付费路由）；而生产实际运行 `RELEASE_PHASE=consumer_active`——该 phase 在 `request_allowed()` 中**全放行**，即 allowlist 在生产未生效，门禁来自服务层鉴权 / RLS / 额度。`release_scope.py:8-10` 又明确把 `consumer_active` 标注为「Staging acceptance phase … Never use in production」。因此「ADR 声明的发布边界」与「生产实际边界」当前不是一回事，二者需要在 10-07 前收敛（选项见 §0 U1）。

### 4.2 旧路径冻结

| 路径 | 第一阶段状态 | 机械门闩 | 重新启用条件 |
| --- | --- | --- | --- |
| 浏览器私有 PostgREST 与 Edge fallback | frozen | B/admin 页面 `release-boundary.js` 仅允许同源 `/content-library.json` 与 `/field-options.json` GET；发布配置不固定 Supabase 项目 | 新 ADR、等价 FastAPI 接口和浏览器回归通过 |
| `supabase/functions/jphouse-run` | removed | 仓库与 Supabase function 配置均不再登记 | 若重新引入，必须先有新 ADR、FastAPI 等价授权/配额与回归证据 |
| `scripts/run_jphouse_worker.py` | removed | 文件已删除；不再读取旧 worker 凭证或 REST 队列 | 若重新引入，必须先有新 ADR、授权、配额与回归证据 |
| FastAPI in-process regional executor | worker-only implementation | API 不再用 `BackgroundTasks` 调度；仅由 `backend/app/report_worker.py` 调用共享执行函数 | durable worker、原子 claim、幂等、有限重试和真库并发证据 |
| B 端与管理员按钮 | 由 phase 驱动（修订后：后台为正式面） | 浏览器门闩只在 `phase == consumer_intake_preview` 时生效（`web-source/js/release-boundary.js`）；`deploy/render-frontend-config.py:24` 在 phase ≠ `consumer_intake_preview` 时把 `businessOperations`/`adminOperations` 置 `true` | 后台：`ADMIN_ENABLED` + 角色校验 + 审计（已在生产生效）。B 端：**尚无门禁**——生产 `consumer_active` 下 B 端页面可直连 API（§0 U4），需在 B 端正式上线前给出收敛手段 |

环境变量不是操作授权。即使代码具有 break-glass 开关，任何 staging/production 激活仍须由人工确认确切环境、持续时间、数据范围、负责人和回滚步骤；本 ADR 不授权设置这些变量。

## 5. 考虑过的方案

### A. 只发布 C 端 intake 与免费预览（2026-08-30 原始采用；**已被 §0 修订取代**）

最好地复用已经通过 synthetic staging smoke 的窄链路，不依赖未协调的会员/计费/任务 schema，也不需要启动重复报告执行器。代价是暂时没有保存项目、完整报告和商业化闭环。

### A′. C 端（含注册/查询/付费）与后台管理平台同时上线（**2026-09-26 修订后采用**）

依据用户 2026-09-23 / 2026-09-24 决策。修订后的事实前提已与 2026-08-30 不同：注册与账号生命周期、报告 outbox worker、额度与 provenance 契约、后台 `ADMIN_ENABLED` 与角色/审计均已落地并有实测证据（见 `progress.md` 与 `docs/release/launch-readiness-log.md`）。代价与剩余缺口 = 发布 phase 与 allowlist 尚未按新范围收敛（§0 U1–U5），且 live release 在 C03–C14 闭合前仍未授权。

### B. 同时发布账号转正、项目保存和完整版报告

它的最佳情形是给 C 端更完整的价值闭环，并为后续付费准备入口。但当前 Auth 生命周期、migration baseline、项目权限、正式报告数据与 worker 均未达到发布门槛；把 UI 验收当作后端验收会扩大跨用户与重复写入风险。

### C. 同时发布 B 端和管理员功能

它的最佳情形是一次展示完整平台叙事，且 staging UI 已可评审。但真实机构、额度、支付、任务、导出、管理员授权和审计并不存在；发布按钮会制造能力错觉，因此只保留无网络副作用的 demo。

### D. 以 PostgREST/RLS 或 Edge Function 加速上线

它能少写 FastAPI 接口，但会恢复 ADR-0001 已拒绝的重复业务边界，无法集中执行额度、幂等、任务和审计规则，也使浏览器重新拥有私有表写入口，因此不采用。

## 6. 后果、非目标与翻转条件

修订后（§0）：发布面从「匿名 intake + 免费预览」扩大到「C 端全流程 + 后台管理平台」，收益是首日即具备完整价值闭环与可运营的后台；代价是发布面、数据副作用与排障面都变大，且**当前缺少与新范围一致的技术门禁**（§0 U1–U5）。旧实现仍保留在仓库（见 §4.2）。

本 ADR 不解决 migration baseline、不创建 production schema/bucket/Auth 配置、不部署、不迁移队列、不删除旧路径，也不声明数据具有统计代表性或系统 production-ready；`docs/release/production-go-live-approval.json` 在 C03–C14 闭合前保持 `BLOCK / NOT AUTHORIZED`。

**修订前的翻转条件（2026-08-30 原始口径，保留）**：只有当 migration baseline 可从空库重建、production Auth/RLS/Storage 与恢复计划通过、唯一 durable worker 和 FastAPI 等价接口通过、真实但非敏感的受控验收完成、容量与隐私要求确认后，才考虑新 ADR 扩大范围。

**修订后的翻转/收紧条件（2026-09-26）**：

- 只有在下列全部完成后才可宣布「ADR 与运行时一致」：① 按新范围确定并落地发布 phase 与 allowlist（含 auth/query/reports/billing/region-stats 的取或舍，§0 U1）；② 生产 phase 口径与代码注释一致（U2）且 `ENVIRONMENT` 标签正确（U3）；③ 补齐 API release-scope 回归（unknown phase / `/convert` / legacy 路由，U5）。
- 任何 B 端（小象数据）正式开放必须先有可执行门禁与自己的 ADR 修订（U4）。
- 若任一门槛未满足，宁可回到更窄的 phase 或推迟，不得用 `consumer_active`（全放行）作为发布边界的替代表述。

## 7. Rollout 与 rollback

本地落地顺序是：运行时 allowlist → Edge/local worker 默认关闭 → B/admin 网络门闩 → Render staging 阶段声明 → 离线契约测试。live rollout 必须按 [第一阶段发布检查单](../release/phase-one-release-checklist.md) 逐项完成并重新取得部署授权。

回滚时应回退本次代码/静态配置并保持旧执行器关闭；不得通过打开 Edge/local worker 开关来“恢复服务”。若发布阶段配置缺失或异常，让业务 API 保持 fail closed，先恢复配置与验证，再决定是否重新开放。

## 8. Open questions

**2026-09-26 状态标注**（未标注 = 仍未答复，保留为 release blocker，不由实现者自行假设）：

- production 静态发布物是只打包 C 端文件，还是对 B/admin staging 评审页做独立访问控制？→ **修订后部分失效**：后台管理平台本身是首发面，`admin.html` 必须留在生产发布物内；剩下的开放问题是 **B 端页面**（`data-query`/`analysis`/`exports`/`organization`/`service-tasks`）是否随首发发布、以及用什么门禁收敛（§0 U1/U4）。
- production 域名、CORS origin、FastAPI base URL 和环境配置的负责人是谁？→ **域名已落地**：`zoubeacon.app`/`api.zoubeacon.com`/`platform.zoubeacon.com` 已在 nginx 生效（`deploy/nginx/default.conf`）；**负责人与 `ALLOWED_ORIGINS` 的逐域确认仍未登记**，且生产 `ENVIRONMENT=staging` 标签待修正（§0 U3）
- 匿名资料的隐私文本、同意版本、删除请求入口和保留期是否已经由产品/法务确认？→ **地区口径已定（日本，2026-09-24 决策 4）**；文本定稿仍待 D-5，未定项 = 删除 SLA 天数 / 事故责任人 / 是否上特商法记载页
- 首月用户量、峰值 QPS、文件量、Storage 增长、SLO 和预算是多少？→ **仍未答复**（C11 保持开放；基线与预算数值待用户提供）
- 免费预览是否允许生产收集真实资料，还是先限定受邀测试？→ **已答复（2026-09-24 决策 1）**：**开放注册、不设邀请制**（不切 `disable_signup` 的旧计划已废弃；公共 Auth 直连注册在生产已关闭，注册一律走 FastAPI 端点）。受邀范围限制不再作为首发前提。

上述未答复项在获得明确答案前保留为 release blocker。
