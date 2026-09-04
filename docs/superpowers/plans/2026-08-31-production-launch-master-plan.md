# JPPropDIs 正式上线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not delegate to subagents unless the user later explicitly authorizes delegation.

**Goal:** 在不混淆 staging、synthetic fixture 与 production 证据的前提下，先安全发布 C 端匿名 intake／免费预览，再完成会员、机构、额度、支付、真实分析、任务协作与管理员能力的完整 V1 商业化上线。

**Architecture:** Supabase Auth 是唯一身份签发方；FastAPI 是所有私有产品操作的唯一业务 API；Supabase PostgreSQL 与私有 Storage 保存业务数据；`supabase/migrations/` 是唯一前向迁移历史；异步任务只由一个 PostgreSQL-backed durable worker 执行。第一阶段发布面固定为 `consumer_intake_preview`，B 端与管理员页面在完整 V1 前只能保留为无网络副作用的 `synthetic_fixture` 评审资产。

**Tech Stack:** Python 3.12、FastAPI、asyncpg、Supabase Auth/PostgreSQL/Storage/CLI、PostgreSQL 17、Node.js、Playwright、Render、GitHub Actions。

**Specs:**

- `docs/architecture/adr-0001-authoritative-backend-and-schema.md`
- `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md`
- `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md`
- `docs/superpowers/specs/2026-08-29-business-full-surface-design.md`
- C02 将审核并集成 `docs/architecture/adr-0002-phase-one-release-scope.md` 及其机器契约。

## Global Constraints

- 第一阶段 production 只发布 C 端匿名 intake 与免费预览；项目转正、完整版报告、B 端和管理员真实操作均不在首发范围。
- `migration_baseline_status = reconciliation_required` 是硬停止条件；C03–C05 完成前禁止新增或应用 V1 会员、支付、额度、任务、联系授权或后台 migration。
- 已应用 migration 不得改写、重命名或通过 linked repair/reset 消除差异；修复必须使用审核后的 later-ID forward migration。
- 数据库、Auth、RLS、Storage、DNS、secret、billing、production deployment、真实通知及破坏性操作必须针对确切目标取得明确授权。
- 不写入真实 secret；不把 staging、local、fixture 或静态页面检查表述为 production 证据。
- 非 synthetic 数据必须有 `data_class`、来源、时间、期间、转换版本、样本量、方法、限制和 `rights_confirmed=yes`；挂牌与成交必须分开。
- 不进行未授权抓取，不复制受保护的房源图片、户型图、描述、经纪人联系方式或个人资料。
- 所有私有所有权基于不可变 `user_id = auth.uid()`；浏览器 email、隐藏按钮和客户端字段不能构成授权。
- 当前主 checkout 与远端历史、多个 Codex worktree 存在分叉；禁止 force-push，禁止覆盖用户未提交修改。
- 每个任务必须完成 RED → 最小实现 → GREEN → 证据记录 → 独立评审；离线实现存在于 worktree 不等于已集成。

## Standard Verification Matrix

每个改变相关行为的任务至少运行其聚焦测试，并在合并前运行：

```bash
PYTHONPATH=. backend/.venv/bin/python -m pytest tests -q
node --test tests/edge/jphouse-run-authority.test.mjs
npm run test:web
PYTHONPYCACHEPREFIX=/tmp/jppropdis-release-pycache backend/.venv/bin/python -m compileall -q backend scripts src
find web/js -type f -name '*.js' -print0 | xargs -0 -n1 node --check
node --check web/app.js
backend/.venv/bin/python -m pip check
git diff --check
```

数据库任务还必须在 disposable local Supabase 上运行：

```bash
supabase db reset --local
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_property_intake_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/security/test_rls_private_projects.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/security/test_rls_v1_identity_matrix.sql
supabase db lint --local --level warning
```

若本地端口、Docker、PostgreSQL 或测试凭证不可用，结果必须记录为 `BLOCKED`／`NOT_EXECUTED`，不得记为通过。

## Milestones

| Milestone | 必须完成 | 结果 |
| --- | --- | --- |
| G0 集成基线 | C01–C02 | 单一、干净、可审阅的 release branch；首发范围可机器验证 |
| G1 数据安全基线 | C03–C05 | 空库可重建；staging drift 已通过 forward reconciliation；RLS/Storage 四角色通过 |
| G2 首发候选 | C06–C12 | 数据、worker、配置、安全、隐私、容量和 CI gate 全绿 |
| G3 第一阶段正式上线 | C13–C14 | `consumer_intake_preview` production 受控上线并可回滚 |
| G4 完整 V1 商业化上线 | C15–C20 | 会员、机构、额度、支付、真实分析、任务和后台上线 |
| G5 上线后收敛 | C21–C23 | 旧路径退役、schema 文档收敛、扩容与未来数据库 ADR 完成 |

---

## P0 — 阻塞任何 production 发布

### C01：建立唯一 release integration 基线

**Depends on:** 无。

**Files:**

- Create: `docs/release/worktree-integration-manifest.json`
- Create: `docs/release/integration-decisions.md`
- Test: `tests/architecture/test_release_integration_manifest.py`
- Modify after review: `progress.md`

**Current inputs:** 当前主 checkout、远端 `main`、P0-1 至 P2-3 的独立 worktree、renovation 相关未提交改动。

- [ ] 在执行阶段使用 `superpowers:using-git-worktrees` 从审核后的远端 lineage 创建 `codex/production-release-v1`；不在脏 checkout 上合并。
- [ ] 运行 `git fetch --prune origin`、`git log --graph --all`、`git diff --name-status`，记录本地 main、origin/main 和每个 worktree 的 base/HEAD/dirty 状态。
- [ ] 为每份候选成果记录 `source_task`、文件清单、依赖、验证证据和 `integrated|deferred|rejected` 决策；不得批量复制整个 worktree。
- [ ] 先写 manifest 契约测试，要求 19 个既有上线任务和当前 renovation 变更均有明确处置，再生成 manifest。
- [ ] 每次只集成一个任务，运行聚焦测试并提交；禁止 force-push 或覆盖用户改动。

**Done when:** release branch 干净；所有候选成果都有唯一处置；没有 `.venv`、`output/`、`tmp/`、测试截图、secret 或生成资产误入提交；`progress.md` 与 branch 实际状态一致。

### C02：集成第一阶段范围冻结与运行时门闩

**Priority:** P0-Critical。  
**Depends on:** C01。

**Files:**

- Create: `docs/architecture/adr-0002-phase-one-release-scope.md`
- Create: `docs/architecture/phase-one-release-boundaries.json`
- Create: `docs/release/phase-one-dependencies.md`
- Create: `docs/release/phase-one-release-checklist.md`
- Create: `backend/app/release_scope.py`
- Create: `web/js/release-boundary.js`
- Modify: `backend/app/main.py`, `render.yaml`, `web/config.js`, B/admin HTML entry points
- Test: release-scope API、architecture、Edge、worker 与 Playwright 网络边界测试

- [ ] 先运行候选 worktree 的 release-scope 测试，确认能观察到 managed 环境 fail-closed、`/convert`/legacy route 阻断、Edge/worker 默认关闭和 B/admin 无网络写入。
- [ ] 逐文件审核并集成 P0-1 候选；production 静态发布物只能包含 C 端入口，或对 B/admin 评审页设置独立访问控制。
- [ ] 验证 `RELEASE_PHASE=consumer_intake_preview` 的 allowlist 与机器契约完全一致，未知 phase 只保留 health/diagnostics。
- [ ] 验证 break-glass 环境变量默认关闭，且环境变量本身不被视为上线授权。

**Done when:** ADR-0002 为 Accepted；首发实际构建物、API allowlist、浏览器网络行为和机器契约一致；离线回归全绿；状态仍为 `BLOCK / NOT AUTHORIZED`，直到 C03–C14 完成。

### C03：集成 canonical migration baseline 并完成空库重建

**Priority:** P0-Critical。  
**Depends on:** C01。

**Files:**

- Modify/Add: `supabase/migrations/` 的审核后 11-file canonical history
- Modify: `supabase/migrations/README.md`
- Create/Modify: `tests/sql/`, `tests/security/test_rls_v1_identity_matrix.sql`
- Create: `docs/architecture/migration-reconciliation-report.md`

- [ ] 对三个已在 staging 应用的 migration 重新计算 SHA-256，要求与现有文件完全一致。
- [ ] 审核 P0-2 候选 migration 的依赖顺序、主键、约束、RLS、provenance、`btree_gist` 与 extension 权限。
- [ ] 先运行缺失 baseline 的失败证明，再集成最小 canonical history。
- [ ] 执行完整 disposable reset、五组 SQL assertions、四身份行为矩阵、db lint 和 local full-dump restore。
- [ ] 生成不包含客户行的 staging schema/ledger drift 报告；本任务不得执行 linked repair/push/reset。

**Done when:** fresh local reset 可重复通过；local restore 后断言仍通过；已应用 migration hash 未变；状态精确记录为 `canonical_local_pass_live_reconciliation_required`，并列出每一项 staging drift。

### C04：完成 provider backup、隔离恢复与 forward-fix 演练

**Priority:** P0-Critical。  
**Depends on:** C03。

**Files:**

- Create: `scripts/database_recovery.py`
- Create: `docs/operations/database-recovery-runbook.md`
- Create: `docs/operations/database-recovery-evidence.template.json`
- Test: `tests/unit/test_database_recovery.py`

- [ ] 集成并复核 P0-3 的 local-only/disposable 安全边界、SHA-256、TOC、owner/ACL 与失败即停逻辑。
- [ ] 在本地 disposable PostgreSQL 恢复 custom-format artifact，重跑 schema/RLS assertions，并证明目标与临时资源可安全清理。
- [ ] 在执行 provider backup/clone 前，向用户列明确切 project、成本、负责人、保留期、Storage 另行备份方式和清理计划并取得授权。
- [ ] 在授权后创建 provider-supported backup/isolated clone，验证数据库与 Storage 恢复路径，不读取或导出客户业务行。
- [ ] 记录 database owner、recovery lead、release owner、incident owner、backup ID、checksum、版本和验收结果。

**Done when:** provider backup 与隔离恢复均有可复核证据；数据库和 Storage 恢复边界清楚；migration 失败可通过已演练的 rollback/forward-fix 流程处理。

### C05：执行 staging forward reconciliation 与 Auth/RLS/Storage 正式验收

**Priority:** P0-Critical。  
**Depends on:** C03、C04。

**Files:**

- Create: new later-ID reconciliation migration under `supabase/migrations/`
- Modify: `tests/security/test_rls_private_projects.sql`
- Create/Modify: `tests/security/test_rls_v1_identity_matrix.sql`
- Create: `docs/architecture/rls-verification-matrix.md`
- Modify: `docs/architecture/authoritative-boundaries.json`

- [ ] 只读分类现有 staging 行的 provenance、owner、constraint 和 policy drift；不得自动把 email 映射成 `owner_user_id`。
- [ ] 先为目标 drift 编写失败 SQL assertions，再创建 later-ID expand/backfill/validate migration；不改写已应用文件。
- [ ] 在执行前向用户列出 staging project ref、migration ID、backup ID、预计影响行数、锁风险、forward-fix 与停止条件，并取得明确批准。
- [ ] 执行 dry-run；获批后才应用 migration。失败立即停止，不运行 migration repair、reset 或无审查的补丁 SQL。
- [ ] 分别验证 anon、owner、other user、privileged worker 以及 Storage object policy；再验证 Auth 邮箱确认、重复账号、密码找回、注销、撤销、删除和枚举防护。

**Done when:** staging ledger 与审核后的 canonical history 可解释一致；`blocking_drift=absent`；四身份数据库与 Storage 矩阵全绿；existing-row provenance 已分类；production 仍保持未验证。

### C06：集成 provenance、授权来源与发布门禁

**Priority:** P0-High。  
**Depends on:** C03；涉及 staging schema 的部分依赖 C05。

**Files:**

- Create: `src/jp_property_publisher/provenance.py`
- Create: `scripts/audit_provenance.py`
- Create: `docs/architecture/provenance-audit-2026-08.md`
- Modify: CLI、generation、worker、analysis metrics、数据字典
- Test: provenance、collection authorization、report generator、web analysis metrics 与 SQL schema tests

- [ ] 集成 P0-7 候选的 fail-closed provenance contract，先保证缺字段、非法 rights、挂牌/成交混合与展示字符串反向计算会失败。
- [ ] 对 70 条历史 library/config 逐条分类：授权重生成、保留为明确 fixture，或阻断发布；不得批量假定 `rights_confirmed=yes`。
- [ ] 为非 synthetic 数据保存 source period、retrieval/verification time、transformation version、sample size、method、missing policy、limitations 与 rights evidence。
- [ ] 验证 JPY 数值字段、单位、挂牌/成交、data class 和趋势月份在整个生成链路中保持结构化。

**Done when:** 发布门禁报告中非 synthetic 违规为 0；无授权记录不会进入 production 内容；historical blocked items 数量与处置有审计证据；两份 content library 在应同步时 hash 一致。

### C07：收敛为一个 durable report worker

**Priority:** P0-High。  
**Depends on:** C05。

**Files:**

- Create: `backend/app/report_jobs.py`
- Create: `scripts/run_report_worker.py`
- Create: `docs/architecture/report-job-queue-contract.md`
- Modify: API routes/models、legacy worker、Edge Function、`web/app.js`
- Test: `tests/api/test_report_job_routes.py`, `tests/unit/test_report_jobs.py`, architecture/Edge/Playwright authority tests

- [ ] 集成 P0-6 候选，确保 FastAPI 幂等入队、worker 使用 `FOR UPDATE SKIP LOCKED` claim、有限重试、失败分类、lease、cancel/replay 与报告幂等 upsert。
- [ ] 用 later-ID migration 增加 attempt、lease、run-after 与唯一幂等约束；不得用应用内状态模拟缺失的数据库不变量。
- [ ] 让 `REPORT_WORKER_ALLOW_LIVE` 默认关闭；在凭证读取和外部调用前 fail closed。
- [ ] 冻结 Edge、local worker 和 FastAPI `BackgroundTasks` 区域执行器；记录 legacy queue 数量、迁移或排空方案。
- [ ] 对外部 adapter 使用原生 async timeout/cancellation；不得用无法终止同步工作的 `asyncio.to_thread` 冒充超时。

**Done when:** 私有报告任务只有一个 authoritative consumer；并发、重试、worker crash、取消和 replay 测试通过；旧执行器不会被正常 production 流量触发；live worker 启用仍需 C14 的单独授权。

### C08：准备独立 production 配置与 secret/readiness 契约

**Priority:** P0-High。  
**Depends on:** C02、C05、C07。

**Files:**

- Create: `render.production.yaml`
- Create: `backend/app/supabase_config.py`
- Create: `docs/production-readiness.md`
- Modify: health/auth/storage/config docs and tests
- Test: production config、auth、health、storage contract tests

- [ ] 保持根 `render.yaml` staging-only；逐文件审核并集成 P0-5 production candidate。
- [ ] production Blueprint 使用独立 Supabase project、`INIT_SCHEMA=false`、`/health/ready`、quoted `"off"` 和 `sync: false` secret declarations。
- [ ] 同时支持经批准的 publishable/secret key 名称，日志和错误不得回显 key、连接串或内部异常。
- [ ] 固化 `/health/live` 无依赖、`/health/ready` 执行 `select 1` 且失败返回泛化 503 的测试。
- [ ] 定义 production origin、CORS、Auth redirects、private bucket、secret rotation、版本/commit 暴露和停止条件；不在本任务创建服务或写入 secret。

**Done when:** config contract、YAML parse、health tests 和 secret scan 全绿；staging 与 production 文件边界清楚；所有 secret 值仍只存在于受控 provider；deployment 状态保持 `NOT_EXECUTED`。

### C09：生产可靠性、安全、日志与双层限流

**Priority:** P0-High。  
**Depends on:** C02、C07、C08。

**Files:**

- Create: `backend/app/observability.py`, `backend/app/rate_limit.py`, `backend/app/timeouts.py`
- Create: `docs/production-reliability.md`
- Modify: auth、intake、health、geocoder、storage、worker 和 collectors
- Test: observability、rate-limit、timeout、public error 与 dual-rate API tests

- [ ] 集成 P0-8 候选，统一 request/job correlation ID、结构化日志、PII/secret redaction 和公开错误分类。
- [ ] signup、login/reset、intake、upload、preview、report、export、notification 分别实施 account + abuse-source 双限流；数据库写操作使用可原子化的可信服务端路径。
- [ ] 所有 outbound request 设置 connect/read/total timeout、有限 transient retry、jittered backoff 和 cancellation。
- [ ] 修复 release gate 报告的已知依赖漏洞；无法安全升级时记录 compensating control 与明确 release decision，不得忽略扫描失败。
- [ ] 用 fixture 验证日志不含 token、email、姓名、源 payload、文件内容或 raw exception。

**Done when:** security/reliability 聚焦测试全绿；日志 redaction 证据通过；rate-limit 可在多实例下保持一致；依赖审计没有未接受的 Critical/High；告警和 on-call 路径已记录。

### C10：第一阶段隐私、同意、保留和删除运营闭环

**Priority:** P0-High。  
**Depends on:** C05、C09。

**Files:**

- Create: `backend/app/routes/privacy.py`, `backend/app/services/privacy.py`
- Create: `docs/legal/privacy-policy.md`, `docs/legal/terms-of-service.md`, `docs/legal/privacy-operations-runbook.md`, `docs/legal/incident-response.md`
- Create: `web/privacy.html`, `web/terms.html`, `web/support.html`
- Modify: intake/account HTML, API routes, i18n and retention cleanup
- Test: privacy API/unit/architecture/Playwright tests

- [ ] 产品与法务确认运营主体、首发地区文本、禁止上传内容、资料用途、同意版本、保存期、删除 SLA、客服入口和事故响应责任人。
- [ ] 同意时间由可信服务端/Auth 事件记录；浏览器时间仅作显示，不作审计真值。
- [ ] 匿名 intake 到期时删除数据库状态与 private Storage objects；失败进入可重试队列并告警。
- [ ] 删除执行器未配置时 fail closed，返回不泄露账号存在性的统一响应；不得显示“已删除”而实际未执行。
- [ ] 验证 200%/400% zoom、键盘、focus、状态播报、390x844、reduced motion 和禁止上传提示。

**Done when:** policy/terms 版本与服务端 consent record 对应；受控删除演练覆盖 DB/Auth/Storage/backup 限制；支持和事故流程有负责人；法务未确认的地区组合保持关闭。

### C11：建立受控容量基线、SLO 与预算

**Priority:** P0-High。  
**Depends on:** C07–C10。

**Files:**

- Create: `scripts/staging_capacity_probe.py`
- Create: `docs/operations/staging-capacity-validation.md`
- Create: `docs/operations/staging-capacity-baseline.json`
- Test: `tests/performance/test_staging_capacity.py`

- [ ] 集成 P1-6 的 synthetic probe；默认只允许 localhost/staging allowlist，明确拒绝 production target。
- [ ] 产品确认首月用户量、峰值 QPS、每日文件数、20 MiB 上限、Storage 增长、报告并发、SLO、预算和降级策略。
- [ ] 先在本地 fixtures 验证 probe，不制造真实用户或客户文件。
- [ ] 对 staging 压测前列出目标、最大并发、总请求数、synthetic 数据、清理步骤和停止阈值并取得授权。
- [ ] 分别记录 FastAPI intake、数据库 pool、Storage、geocoder、durable worker 的 p50/p95/p99、错误率与饱和点；不能把一个路径代表全系统。

**Done when:** baseline JSON 可机器读取；production 部署和 rollback 阈值从该基线派生；容量满足首月预算或已明确缩小受邀范围；没有 production load test。

### C12：统一 CI、release gate 与不可变证据包

**Priority:** P0-Critical。  
**Depends on:** C03–C11。

**Files:**

- Create: `.github/workflows/release-gate.yml`
- Create: `scripts/ci/`
- Create: `docs/release/release-gate.md`, `docs/release/rollback-checklist.md`
- Test: release gate contract、evidence、secret scan、static fixture server tests

- [ ] 集成 P0-10 候选，并使 Python、Node、Playwright、disposable SQL/RLS、供应链、policy 和 evidence 七个 job 相互独立且全部必需。
- [ ] 移除对 ignored generated assets 的隐式依赖，测试只使用 canonical fixture 或 CI 明确生成的副本。
- [ ] 解决 `pip-audit` 的未接受漏洞和 Supabase disposable port collision；SQL job 未执行必须令 gate 失败。
- [ ] 在 GitHub-hosted Actions 实际运行一次，而不是只做 YAML parse；保存 commit、runner、依赖 lock、测试摘要和 artifact checksum。
- [ ] 只有所有 required checks 通过才生成 source artifact、candidate tag 名和 release evidence bundle。

**Done when:** `offline_gate_passed=true`；所有 required jobs 在 GitHub Actions 绿；secret scan、dependency audit、SQL/RLS、Playwright 与 policy checks 无跳过；证据包可由 checksum 验证。`release_ready` 仍需 C13–C14 的 staging/production 证据。

### C13：构建并验收第一阶段 staging release candidate

**Priority:** P0-Critical。  
**Depends on:** C02–C12。

**Files:**

- Create: `scripts/staging_synthetic_smoke.py`
- Create: `docs/staging-synthetic-smoke.md`
- Create: `docs/release/phase-one-staging-evidence.json`
- Test: `tests/smoke/test_staging_synthetic_smoke.py`

- [ ] 固定候选 commit、artifact checksum、staging API/Web 服务、Supabase project ref 和 environment diff。
- [ ] 对 staging code deploy 可按既有授权直接执行；任何 DB/Auth/RLS/Storage 写入 smoke 必须另列确切数据与清理计划并取得授权。
- [ ] 用 synthetic/非敏感资料覆盖 text、URL、PDF、JPG、PNG、位置拒绝、geocoder 失败、过期清理、跨用户拒绝和幂等。
- [ ] 对实际发布物执行浏览器网络审计、console error/warning、桌面/390x844、键盘、zoom 和 reduced-motion 检查。
- [ ] 确认免费预览保持 `data_class`、资料不足、`comparable_status=not_checked`，不返回虚假税费总额或完整版报告结论。

**Done when:** smoke 数据与 Storage objects 清理为 0；API/Web/ready 指向同一候选 commit；无未解释 console/network 请求；staging 证据包完整；Go/No-Go 清单仅剩 production 授权动作。

### C14：Production Go/No-Go、第一阶段部署与回滚观察

**Priority:** P0-Critical。  
**Depends on:** C13。

**Files:**

- Create: `docs/release/production-go-live-approval.json`
- Create: `docs/release/production-release-evidence.json`
- Modify after completion: `progress.md`

- [ ] 记录 release owner、database owner、security reviewer、privacy/legal approver、rollback owner 和 incident commander 的姓名与批准时间。
- [ ] 列出 production Supabase/Render/Storage/Auth/DNS 目标、candidate commit、artifact checksum、secret key 名、backup ID、forward-fix、rollback 和观察窗口。
- [ ] 只有用户明确授权上述确切操作后，才创建/修改 production 资源、设置 secret、应用 migration、部署服务或修改 DNS。
- [ ] 先部署 API/worker 且 worker 保持关闭，验证 live/ready；再部署只含 C 端首发入口的 Web；最后按批准范围开启业务流量。
- [ ] 使用受控 synthetic smoke，不使用真实客户资料；按 C11 的批准阈值观察首个 30 分钟并保持 24 小时增强监控。
- [ ] 若 error rate、p95、DB saturation、Storage failure、RLS/ownership、PII log 或 cleanup 指标越过 C11 阈值，立即停止流量并执行已批准 rollback；不得打开旧 Edge/local worker 作为补救。

**Done when:** production evidence 与部署 commit 对应；首发域名、API、Auth/Storage、日志、告警、删除和 rollback smoke 全通过；`consumer_intake_preview` 正式上线；B/admin、convert、完整版报告与付费路径仍保持关闭。

---

## P1 — 阻塞完整 V1 商业化上线

### C15：真实账户、机构、席位与内部角色服务端化

**Depends on:** C05、C14。

**Files:** new later-ID migration; focused `backend/app/membership/` and FastAPI routes; membership/RLS/audit tests; data dictionary updates.

- [ ] 建模自然人账户、机构、最多 5 个 active members、`owner|member`、合作方资格和逐项内部角色；套餐不能授予后台权限。
- [ ] 所有 private reads/writes 经过 FastAPI；RLS 分别验证 C、B Free、B Pro、其他机构、合作方、后台角色和 service worker。
- [ ] 实现邀请、接受、撤销、暂停、近期认证和结构化审计；客户端不能提交 owner、role、tier 或 limit。
- [ ] 通过 forward migration、backup/forward-fix、SQL/API/并发测试和 staging UAT 后再申请 production rollout。

**Done when:** 第六席位被数据库/服务端拒绝；跨机构访问为 0；内部角色最小权限成立；真实后台不再依赖前端 fixture。

### C16：产品、版本化价格、权益与原子用量

**Depends on:** C15。

**Files:** new later-ID migration; `backend/app/entitlements/`, `backend/app/usage/`; usage API; tests for UTC+8, concurrency and idempotency.

- [ ] 实现 C Free、单份报告、C Plus、B Free、B Data Pro 的版本化价格与权益；地区无批准价格时禁止付款。
- [ ] 实现 UTC+8 自然月、首月按日折算、向上取整和 C Plus 最低单份价格规则。
- [ ] 用 transaction、row/advisory lock、唯一 idempotency key 实现 query、analysis、report reserve/commit/release、subscription slot 和 export rows。
- [ ] 客户端只能查看用量；limit、scope、owner/org 全由可信服务端派生；所有纠正采用 append-only reversal。

**Done when:** 8 路并发争抢最后一份额度只成功 1 次；重试、跨周期 idempotency、失败释放、5 人共享额度、闰年/月末边界全部通过。

### C17：支付、订阅、取消、退款与 dunning

**Depends on:** C15–C16。

**Files:** `backend/app/billing/`, billing routes, provider adapter, new later-ID migration, webhook/refund/dunning tests and finance runbook.

- [ ] 以现有 offline Stripe boundary 为候选输入；默认 provider 未配置时返回安全 503，不创建订单或权益。
- [ ] Checkout 使用服务端 price allowlist；webhook 在解析前验证 raw body 签名，并以 provider event ID 去重后写 transaction + outbox。
- [ ] 实现默认关闭自动续费、提前 5 日提醒、月末不足 5 日不自动续、取消、2 次失败重试、7 日降级、48 小时未使用退款和质量失败退款。
- [ ] 财务退款使用双人/受限权限、原路退回、结构化原因和不可变审计；浏览器不能写订单、套餐、额度或退款状态。
- [ ] 真实 Stripe/dashboard/webhook/密钥/收费/退款只在用户明确批准 sandbox/live 环境后执行。

**Done when:** webhook replay、worker restart、重复扣款、错误币种、未开通权益、取消与退款测试全绿；sandbox 完整闭环通过；live billing 仍需单独 Go/No-Go。

### C18：真实授权分析数据与完整版报告

**Depends on:** C06、C07、C16。

**Files:** data source registry/pipeline, report service/worker, analytics modules, report schema/versioning, data-quality and browser tests.

- [ ] 将 prepare/quality-check pipeline 接入授权 source registry、immutable snapshot/hash、parser version、review status 和 publication gate。
- [ ] 至少准备可比较的多月份、相同地区/资产/状态/data class 数据；挂牌与成交分开，JPY canonical，汇率带来源/日期。
- [ ] 报告由 durable worker 生成并版本化；完整报告显示来源、期间、样本、单位、方法、限制和 model version。
- [ ] 可比数据不足时明确返回不足，不用 synthetic 或展示字符串补数；图表同时提供文字摘要/数据表。

**Done when:** 真实 source registry 权利证据通过人工复核；质量 gate 可重复；已授权数据的 known-result analytics tests 全绿；完整版报告 staging UAT 通过且不承诺收益或法律结论。

### C19：任务池、双向联系授权、真实 B/Admin、导出与订阅

**Depends on:** C15–C18。

**Files:** task/consent/admin/export/subscription services and routes; new later-ID migrations; RLS/audit/retention tests; existing B/Admin UI rewired from fixtures.

- [ ] 实现邀请制合作方资格、one-task/one-organization 匹配、状态历史、暂停/投诉和负责人访问边界；平台不处理任务款项。
- [ ] 只有双方分别同意后才披露 verified email；72 小时未完成则失效，30 天停止展示，3 年审计保留，跨地区组合默认关闭。
- [ ] 导出只包含授权字段并按成功行数计量；统计订阅按有效条件组合计槽位，发送重试不重复计量。
- [ ] 将 B/Admin 页面从 memory fixture 切换到 FastAPI，并按会员运营、数据运维、任务调度、审核、财务、超级管理员分别授权。
- [ ] 验证普通管理员、非负责人、其他机构和匿名用户均不能读取邮箱、原始项目文件、退款或审计敏感字段。

**Done when:** B/Admin 不再是假按钮；跨机构/未授权联系信息访问为 0；任务、同意、导出、订阅、审计和 retention 的 SQL/API/Playwright 矩阵全绿。

### C20：完整 V1 staging 验收与 production 扩围

**Depends on:** C15–C19。

- [ ] 建立完整 V1 release manifest，列出新增 routes、migrations、worker、provider、网页入口和回滚边界。
- [ ] 在 disposable/local、CI、staging 分别运行全量 Python/Node/Playwright/SQL/RLS、billing sandbox、worker crash/replay、privacy deletion 和 data-quality tests。
- [ ] 用受控测试账户覆盖 C Free/C Plus/B Free/B Pro/机构 owner/member/合作方/各后台角色；不使用真实客户资料。
- [ ] 单独取得 production database/Auth/RLS/Storage/deployment/DNS/billing 授权；按 expand → backfill → verify → switch → contract 分阶段发布。
- [ ] 观察期内按 C11 阈值监控报告成功率、退款、重复计量、RLS 拒绝、联系信息访问、队列 lease 和 cleanup。

**Done when:** 完整 V1 production 功能和计费闭环通过；所有角色、额度、支付、报告、任务、隐私和后台证据可追溯；`release_ready=true` 只对应已部署 commit 与证据包。

---

## P2 — 上线后收敛与未来演进

### C21：退役旧执行路径

**Depends on:** C20。

**Files:** `backend/app/legacy_paths.py`, retirement machine contract/design/plan, legacy worker/Edge/web callers and tests.

- [ ] 集成 P2-1 的 staged retirement contract；先记录调用计数和 legacy queue 状态，不直接删除。
- [ ] 当等价 FastAPI/worker 已验证、queue 为 0、观察窗口无调用且 rollback 证据通过后，按 approved flag 关闭旧 caller。
- [ ] 分别删除或 archive direct PostgREST、Edge executor、local worker 和 in-process executor；每次删除独立提交并跑全量回归。

**Done when:** 运行时只剩 ADR-0001 路径；break-glass 不再依赖旧执行器；docs/config/tests 无旧路径漂移。

### C22：收敛 schema ownership 与开发文档

**Depends on:** C21。

- [ ] 集成 P2-2 schema ownership audit 和机器检查，确认 `supabase/migrations/` 是唯一 forward history。
- [ ] 将 `backend/sql/` 明确保留为 immutable historical bootstrap/reference；移除普通启动、README 和 runbook 中把它当建库入口的命令。
- [ ] 更新 README、backend docs、Supabase setup、data dictionary、ADR 和 contributor commands；实际运行每条新命令。

**Done when:** schema ownership audit 只有一个 canonical history；新贡献者可以从空库构建；没有文档诱导 linked repair、mutable setup 或 production startup initialization。

### C23：上线后容量优化、SLO 复盘与 Render PostgreSQL ADR

**Depends on:** C20；Render 数据库迁移评估还依赖 C22。

- [ ] 用 production 聚合指标复盘 30/60 日容量、成本、错误预算、Storage 增长、worker backlog 和数据库 pool；不读取客户内容。
- [ ] 对真实瓶颈做聚焦索引/并发/缓存优化，每项先有 traced query 或 profile，再改代码。
- [ ] 完成 Render PostgreSQL future migration ADR，分别评估 Supabase Auth、`auth.uid()`/RLS、private Storage、备份恢复、区域、连接池、成本、停机、rollback 和 dual-write 风险。
- [ ] 默认结论为“不迁移”，除非 ADR 的全部前置证据和可逆 cutover 条件成立；不得把迁移简化成替换 `DATABASE_URL`。

**Done when:** SLO 与预算基于生产聚合证据；优化有前后对比；未来数据库选择有 Accepted/Rejected ADR；没有未经授权的数据库创建或数据迁移。

## Program Completion Rule

- 完成 C14 只能声明：**第一阶段 C 端 intake／免费预览已正式上线**。
- 完成 C20 才能声明：**JPPropDIs 完整 V1 商业化能力已正式上线**。
- 完成 C23 才能声明：**上线后架构债务和未来数据库决策已进入稳定维护状态**。
- 任一任务若只有离线代码、静态审计、fixture 测试、未提交 worktree 或 staging 结果，状态必须保持 `PARTIAL` 或 `BLOCKED`，不得标记 `DONE`。
