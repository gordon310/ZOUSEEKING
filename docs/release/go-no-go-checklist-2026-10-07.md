# 2026-10-07 Web/PWA Go/No-Go checklist

**总判定：No-Go，不能在 2026-10-07 正式上线 `consumer_intake_preview`。** 必须先闭合 C01 的干净、唯一集成基线；C02 的 ADR/机器 allowlist 一致性；C04 的 provider 备份与数据库/Storage 隔离恢复；C05 的 production 以外四身份 Storage/Auth/RLS 复验边界；C06 的非 synthetic 内容发布门禁；C08–C11 的生产配置、可靠性、隐私运营和容量门槛；C12 的 GitHub Actions 不可变证据；以及 C13/C14 的 staging candidate 和受控 production 发布/回滚证据。现有 `docs/release/production-go-live-approval.json` 明确为 `BLOCK / NOT AUTHORIZED`，`production-release-evidence.json` 为 `NOT_EXECUTED`。

状态口径：✅ 已达成 = 当前 Done when 全部有仓库内证据；🟡 部分达成 = 有可复现子证据但出口仍缺；❌ 未开始/缺口 = 没有可证明的出口实现或证据。`NEEDS_PROD_EVIDENCE` 不代表可跳过，且本审计未 SSH、未连接生产。

| 阻断项 | Done when（主计划原文） | 状态 | 证据（仓库内；本轮实跑） | 缺口/下一步 | 负责人建议 | 预估工作量 |
|---|---|---|---|---|---|---|
| C01 | release branch 干净；所有候选成果都有唯一处置；没有 `.venv`、`output/`、`tmp/`、测试截图、secret 或生成资产误入提交；`progress.md` 与 branch 实际状态一致。 | 🟡 部分达成 | `docs/release/worktree-integration-manifest.json` 与 `docs/release/integration-decisions.md` 存在；`tests/architecture/test_release_integration_manifest.py` 在 65-pass 批次通过。实跑 `git status --short` 显示未跟踪 `docs/superpowers/plans/2026-09-23-web-first-launch-14d.md`；当前为 `main` / `1dea917`，不是 manifest 指定的 release branch。`git diff --check` 通过。 | 清理或明确处置未跟踪计划；从审定 lineage 建立并核对唯一 release branch，重做候选/生成资产/secret inventory，并使 `progress.md` 与实际一致。 | Codex | 0.5–1 天 |
| C02 | ADR-0002 为 Accepted；首发实际构建物、API allowlist、浏览器网络行为和机器契约一致；离线回归全绿；状态仍为 `BLOCK / NOT AUTHORIZED`，直到 C03–C14 完成。 | 🟡 部分达成 | `docs/architecture/adr-0002-phase-one-release-scope.md` 标为 Accepted；`tests/web/release-scope.spec.js` 实跑 2 passed，B/admin 网络写入被拦截；`production-go-live-approval.json` 为 `BLOCK / NOT AUTHORIZED`。但 `backend/app/release_scope.py` 和 `phase-one-release-boundaries.json` 的 phase-one contract 仍加入 exports、analysis、usage 及大量 admin/org/service-task 路由，和 ADR “只 C 端 intake/免费预览”不一致。 | 收窄或重新批准 ADR，使 API allowlist、JSON、运行时和发布物一致；补 API release-scope 回归（含 unknown phase、`/convert`、legacy 路由）并在 clean candidate 上跑完整离线回归。 | Codex + 用户（范围决定） | 1–2 天 |
| C03 | fresh local reset 可重复通过；local restore 后断言仍通过；已应用 migration hash 未变；状态精确记录为 `canonical_local_pass_live_reconciliation_required`，并列出每一项 staging drift。 | 🟡 部分达成 | `docs/architecture/migration-reconciliation-report.md` 记录 fresh reset、SQL/RLS assertions、hash 与 drift；本轮 `scripts/restore_drill.py` 通过：`RESTORE_OK`、7 表/50 migration versions、`CLEANUP_OK`。但报告/`authoritative-boundaries.json` 当前使用 `canonical_staging_reconciled_production_reconciled`，不等于主计划要求的精确状态；本轮未 destructive reset（避免覆盖现有本机状态）。 | 统一主计划与当前 migration 状态的版本化结论；在 disposable fresh reset 上重跑并保存 migration hash/五组 SQL/RLS 输出；若要求 staging/prod reconciliation，另行审批且不能用本机结果替代。 | Codex；线上核对由用户授权 | 0.5–1 天本机；线上另计 |
| C04 | provider backup 与隔离恢复均有可复核证据；数据库和 Storage 恢复边界清楚；migration 失败可通过已演练的 rollback/forward-fix 流程处理。 | 🟡 部分达成 `NEEDS_PROD_EVIDENCE` | `tests/unit/test_database_recovery.py` 通过；本轮 `restore_drill.py` 成功本机导出→隔离恢复→断言→清理。`docs/architecture/migration-reconciliation-report.md` 与 `m1-database-production-line-evidence.json` 明确 provider physical backup/PITR 不可用或未执行，Storage blob 不在逻辑 DB backup 内。 | 在获批 provider 项目执行前列 project、成本、保留、owner、backup ID、Storage 方案和清理计划；创建/验证 provider-supported backup 或 clone；分别恢复 DB 和 private Storage synthetic object，并记录 checksum、RPO/RTO、rollback/forward-fix 演练。不得 SSH。 | 用户（provider/费用批准）+ Codex | 1–2 天，含观察/证据 |
| C05 | staging ledger 与审核后的 canonical history 可解释一致；`blocking_drift=absent`；四身份数据库与 Storage 矩阵全绿；existing-row provenance 已分类；production 仍保持未验证。 | 🟡 部分达成 `NEEDS_PROD_EVIDENCE` | `docs/architecture/rls-verification-matrix.md` 记录 2026-09-02 staging 数据库+Storage anon/owner/other/worker PASS、Auth 生命周期与 cleanup=0；`m1-database-production-line-evidence.json` 同样记录 `storage_anonymous_owner_other_worker=pass`。本轮四身份 HTTP test 因环境凭据缺失 1 skipped；其余 unit contract passes。 | 当前仓库有历史 staging Storage 四角色证据，但本轮无法复验；真实恢复邮件也 `NOT_EXECUTED`。对目标 staging 以新授权运行 `scripts/staging_m1_acceptance.py` 与 `tests/security/test_rls_four_identity_http.py`，确认 ledger、`blocking_drift=absent`、对象 upload/download/delete/restore/hash/cleanup=0、Auth email delivery；生产仍须独立验证。 | 用户（环境授权）+ Codex | 0.5–1 天 staging；生产另计 |
> **复核更正(2026-09-23)**:C06 所述内容库「70 条」与实测不符——**实测两份内容库各 6 条**;这 6 条原先均缺分类/来源字段,现已全部显式标为 `synthetic_fixture`,非 synthetic 违规 = 0,两副本 SHA-256 一致(证据:`/tmp/zouseeking-p234-details.md` 与完成记录台账)。

| C06 | 发布门禁报告中非 synthetic 违规为 0；无授权记录不会进入 production 内容；historical blocked items 数量与处置有审计证据；两份 content library 在应同步时 hash 一致。 | 🟡 部分达成 | provenance focused tests 本轮 8 passed / 13 skipped；先前组合中 contract tests 通过。`backend/app/services/provenance.py` 和 API contract tests 存在。两库 hash 本轮一致：`6c5896…f1aa1`。但 `docs/architecture/provenance-audit-2026-08.md` 明说 70 library records 可发布=0、阻断=70，CSV=2 blocked；没有 `scripts/audit_provenance.py`。 | 将 70 条逐一处置为有授权可重生成、显式 synthetic fixture 或移出发布物；对每条保存 rights、period、retrieval/verification、version、sample/method/missing/limitations；以可执行 audit 生成违规=0 的门禁报告。不得把展示字符串反算或默认 rights=yes。 | Codex + 用户（来源授权） | 3–7 天，取决于授权材料 |
| C07 | 私有报告任务只有一个 authoritative consumer；并发、重试、worker crash、取消和 replay 测试通过；旧执行器不会被正常 production 流量触发；live worker 启用仍需 C14 的单独授权。 | 🟡 部分达成 | `backend/app/report_worker.py`、`scripts/run_report_worker.py` 和 worker tests 存在；本轮包含 `test_report_worker*`、Postgres integration 的批次 65 passed（部分 DB 项 skipped）。文档 `authoritative-boundaries.json` 指向 `postgres_job_outbox_single_worker`，Edge removal test 存在。 | 主计划指定 `docs/architecture/report-job-queue-contract.md` 缺失；未见可证明的 production legacy queue inventory/drain、部署级 crash/cancel/replay 或 “旧执行器正常流量不可触发”现场证据。补合同、真库并发和故障演练；worker 保持关闭到 C14。 | Codex | 1–2 天本机/staging；上线启用另计 |
| C08 | config contract、YAML parse、health tests 和 secret scan 全绿；staging 与 production 文件边界清楚；所有 secret 值仍只存在于受控 provider；deployment 状态保持 `NOT_EXECUTED`。 | 🟡 部分达成 `NEEDS_PROD_EVIDENCE` | `render.yaml` 明确 staging；本轮 `secret_scan.py`、release policy 通过；health/release tests 在 56-pass 批次通过；`production-release-evidence.json` 为 `NOT_EXECUTED`。 | 主计划要求的 `render.production.yaml`、`backend/app/supabase_config.py`、`docs/production-readiness.md` 不存在；因此独立生产项目、origin/CORS/redirect/private bucket/rotation/commit exposure/停止条件未形成可验收契约。补文件与 tests，随后由受控 provider 验证 secrets 仅在 provider。 | Codex + 用户（provider 值/目标） | 1–2 天 + 0.5 天核验 |
| C09 | security/reliability 聚焦测试全绿；日志 redaction 证据通过；rate-limit 可在多实例下保持一致；依赖审计没有未接受的 Critical/High；告警和 on-call 路径已记录。 | ❌ 未开始/缺口 | `backend/app/observability.py`、`rate_limit.py`、`timeouts.py` 与 `docs/production-reliability.md` 均不存在。仅有 secret scan PASS 不能替代依赖审计、日志脱敏、双层限流或告警。 | 实现/测试 correlation ID、结构化脱敏日志、account+abuse-source 原子限流、outbound timeouts/retry/cancellation；运行 `pip-audit`/`npm audit` 并处理 Critical/High；记录 provider 告警与 on-call。`NEEDS_PROD_EVIDENCE`：在 provider 检查 alert route 的实际投递和演练。 | Codex + 用户（on-call/告警） | 3–5 天 + 0.5 天演练 |
| C10 | policy/terms 版本与服务端 consent record 对应；受控删除演练覆盖 DB/Auth/Storage/backup 限制；支持和事故流程有负责人；法务未确认的地区组合保持关闭。 | 🟡 部分达成 `NEEDS_PROD_EVIDENCE` | privacy unit/API/architecture tests 在 65-pass 批次通过；`backend/app/routes/privacy.py`、`services/privacy.py`、政策/条款/运营/事故文档和 UI 存在。`privacy-policy.md` 仍写“上線前草稿，待法務／負責人確認”；route 要求 current versions。 | 完成法务/运营主体、地区、SLA、support 和 incident owner 的签署；受控 synthetic deletion 覆盖 DB/Auth/Storage，记录 backup 到期限制；验证连续 retention worker/alert 及 200/400%/keyboard/mobile/reduced motion。法务未确认地区须配置关闭。 | 用户（法务/责任人）+ Codex | 1–2 天实现/测试 + 法务周期 |
| C11 | baseline JSON 可机器读取；production 部署和 rollback 阈值从该基线派生；容量满足首月预算或已明确缩小受邀范围；没有 production load test。 | 🟡 部分达成 `NEEDS_PROD_EVIDENCE` | `tests/performance/test_staging_capacity.py` 本轮通过；JSON 可读且明确 `production_contacted=false`。但 `staging-capacity-baseline-2026-09-01.json` `overall.passed=false`/`FIX`：logo 945,771B 超 524,288B；真实 DB/Storage/geocoder/worker/CDN 与首月预算均未测/未定。 | 产品确定用户量、峰值、文件量、SLO、预算、降级/受邀范围；修静态预算问题；获批后做 staging-only synthetic 分轨测量，导出 deployment/rollback threshold。禁止 production load test。 | 用户（预算/SLO）+ Codex | 1–2 天 + 0.5–1 天 staging |
| C12 | `offline_gate_passed=true`；所有 required jobs 在 GitHub Actions 绿；secret scan、dependency audit、SQL/RLS、Playwright 与 policy checks 无跳过；证据包可由 checksum 验证。`release_ready` 仍需 C13–C14 的 staging/production 证据。 | 🟡 部分达成 `NEEDS_PROD_EVIDENCE` | `.github/workflows/release-gate.yml`、`scripts/ci/release_evidence.py` 和 docs 存在；本轮 release-gate contract/policy/secret scan 通过，Playwright scope 2 passed。`tests/unit/test_release_evidence.py` 验证 code can build an offline manifest, not an actual run. | 没有本仓库中的候选 commit GitHub-hosted Actions run/runner/artifact checksum evidence，也未证明所有 required jobs（尤其 dependency audit、disposable SQL/RLS、full Playwright）无 skip。对已冻结 candidate 在 GitHub Actions 跑完整 workflow，保存 artifact manifest/checksum；此项不靠 YAML parse 通过。 | Codex + 用户（CI access） | 0.5–1 天 |
| C13 | smoke 数据与 Storage objects 清理为 0；API/Web/ready 指向同一候选 commit；无未解释 console/network 请求；staging 证据包完整；Go/No-Go 清单仅剩 production 授权动作。 | ❌ 未开始/缺口 `NEEDS_PROD_EVIDENCE` | `docs/release/phase-one-staging-evidence.json`、`docs/staging-synthetic-smoke.md`、`scripts/staging_synthetic_smoke.py` 均不存在。浏览器 scope test 仅本机，不是 staging candidate smoke。 | 固定 commit/checksum/environment diff；经新授权在 staging 使用 synthetic text/URL/PDF/JPG/PNG、location deny/geocoder failure/expiry/cross-user/idempotency，证明 Storage cleanup=0；在实际 build 做 console/network/mobile/zoom/reduced motion，产出 evidence bundle。 | Codex + 用户（staging 授权） | ~~1–2 天~~ **载体已交付(09-24 夜班,见 §A A11 / §B C13)** |
| C14 | production evidence 与部署 commit 对应；首发域名、API、Auth/Storage、日志、告警、删除和 rollback smoke 全通过；`consumer_intake_preview` 正式上线；B/admin、convert、完整版报告与付费路径仍保持关闭。 | ❌ 未开始/缺口 `NEEDS_PROD_EVIDENCE` | `docs/release/production-go-live-approval.json`: `BLOCK / NOT AUTHORIZED`；`production-release-evidence.json`: `NOT_EXECUTED`, `release_ready=false`，且所有 production checks BLOCKED/NOT_EXECUTED。 | 在 C01–C13 关闭后，记录六位 owner/批准时间、目标/commit/checksum/backup/forward-fix/rollback/观察窗；获用户明确逐项授权后才部署。依顺序验证 API/worker-off live+ready、C-only Web、synthetic smoke、30 分钟/24h 观察和 rollback smoke；保持 B/admin/convert/full report/payments 关闭。不得 SSH。 | 用户（正式授权/owners）+ Codex | 1 天发布窗口 + 24h 观察 |

## 必须先闭合项（按门槛链）

1. C01–C02：清洁候选基线，并解决 “C-only intake preview” 与现有 admin/org allowlist 的冲突。
2. C04–C06：provider 可恢复性、可复验 Storage/RLS/Auth，以及 70 条内容库的授权/处置和违规=0 门禁。
3. C08–C11：独立 production contract、可靠性/双层限流/告警、已签隐私运营闭环、满足预算的容量基线。
4. C12–C13：真实 GitHub Actions 全绿的不可变候选证据包，以及完整 staging synthetic evidence；C13 完成时清单才能只剩 production 授权。
5. C14：受控生产部署与回滚观察。这是最后一道门，不能由已有 “production running” 主张或静态配置替代。

## 需用户决策/动作

- 指定 release owner、database owner、security reviewer、privacy/legal approver、rollback owner 与 incident commander，并提供书面批准时间。
- 明确首发是否严格限制为 C 端 anonymous intake/免费预览，还是批准改变 ADR；本审计不默认扩大范围。
- 批准 provider backup/clone、Storage restore、staging synthetic writes 和生产验证的准确项目、成本上限、数据/清理计划与停机条件；生产证据必须单独收集，禁止 SSH。
- 确认首月用户/QPS/文件/Storage/worker 并发、SLO、预算、降级策略与是否仅受邀范围。
- 完成隐私政策/条款的法务和运营签署，确认允许地区、跨境处理、支持渠道、删除 SLA 与事故责任人。
- 提供 GitHub Actions 与目标 provider 的受控证据收集权限；最终批准 C14 的部署、DNS、secret、migration、流量和 rollback 操作。

## 本轮命令结果

完整命令和输出（包含一次错误的 Node test 调用、并将本机密钥脱敏）见 [`/tmp/zouseeking-googate-details.md`](/tmp/zouseeking-googate-details.md)。关键实跑结果为：focused Python 65 passed/6 skipped、release/policy batch 56 passed、Playwright scope 2 passed、恢复演练 PASS；这些只构成离线/本机证据，绝不构成 production evidence。

---

# 2026-09-24 范围对齐复核(Web-first 10-07 口径)

> 本节由晨班 BOT 追加。原表 C01–C14 编制于 2026-09-21,当时首发范围 = ADR-0002 的「C-only intake preview」。
> 用户已于 **2026-09-23** 拍板改为「C 端 + 后台管理平台同时上线、邀请制试运行、硬出口 **2026-10-07**」
> (依据 `docs/superpowers/plans/2026-09-23-web-first-launch-14d.md`)。原表作为历史快照保留,
> **10-07 前的判定以本节为准**;结论口径:✅ 已闭合维持 / 🟡 收窄或需一次动作 / 🔴 阻断 10-07。

## A. 生产侧实测事实(本轮只读实测;命令见 §D)

| # | 事实 | 实测结果 | 含义 |
|---|---|---|---|
| A1 | 生产迁移台账 | 生产已登记 **50** 条 / 仓库 **54** 条 | 缺 4 条:`20260921000100`(provenance 回填)、`20260923000100`(邀请门)、`20260923000200`(邀请错误态)、`20260923000300`(共享限流) |
| A2 | 邀请表是否存在于生产 | `invite_codes` / `invite_redemptions` **仅**在 `20260923000100`、`20260923000200` 中定义,而这两条未应用 | **生产不存在邀请码表** → 「邀请制准入」在生产**尚未生效**;09-23 台账的 ✅ 证据取自真库,非生产 |
| A3 | 生产注册门 | Management API:`disable_signup=**false**`、`mailer_autoconfirm=false` | 生产仍开放**公共注册**,与「邀请制试运行」口径直接冲突(AGENTS:Consumer pre-release registration is invitation-only) |
| A4 | 生产后台 API | 未鉴权 `/api/admin/*` 均 **401**;SSH 只读实测生产 `deploy/.env` **无 `ADMIN_ENABLED` 键** → 代码默认 `false` | 鉴权边界生效;**后台管理平台在生产被关闭**(鉴权通过后 503)。10-07 要求后台同时上线 → **新增阻断项**,部署批次必须写入 `ADMIN_ENABLED=true` |
| A5 | 前端部署漂移 | 线上 `?v=20260917-r61`,仓库 `deploy/frontend-version.txt` = `20260923-r63` | 生产前端 ≈ `99e33ce`(09-22),**落后 16 个提交**:invite 注册前端、四语试运行标识、静态瘦身、后台页签修复均未上线 |
| A6 | 服务健康 | `zoubeacon.app` 200、`platform.zoubeacon.com/admin.html` 200、`/health/ready` = `ready/database ok` | 服务可用;不代表新范围已生效 |
| A7 | CI | `252b661` Release Gate **success**(七 job,run 35862699493) | C12 的「每次提交绿」持续成立 |
| A8 | C09 可观测/超时缺口 | `observability.py` / `timeouts.py` / `docs/production-reliability.md` 三处缺口**已落地并独立实跑验收**(471 passed / 91 skipped;零 PII 泄漏;`X-Request-Id` 回写) | C09 由 🟡 升 ✅(见 §B),原判定解除 |
| A9 | C07 / C08 缺口 | C07 合同 + 5 静态守护 + 3 真库用例;`C08` 生产配置合同 + `deploy/.env.example` 补 25 键 + 6 静态守护。两者均经独立实跑与**变异测试**(故意引入违规 → 守护测试精确报错) | 两项判定由 🟡 升 ✅(见 §B) |
| A10 | 部署清单缺迁移步骤 | `p5-release.sh` / P5 清单此前**没有应用迁移的步骤**(compose 启动按 AGENTS 不跑 DDL),且配置快照漏 `ADMIN_ENABLED`。已新增 `apply-migrations.sh`(plan 只读对账 / apply 逐条事务 + 台账登记,只写 `version`,与生产既有 50 行一致)并补进清单 | 阻断链第 1 步的执行体已可运行;`plan` 模式已在生产实测(改动前:`on_disk=51 applied=50 pending=1`) |
| A11 | C13 载体(09-24 夜班新增) | 四处交付物**已落地**:`scripts/staging_synthetic_smoke.py`(默认 `--plan` **零网络零 socket**;`--execute` 需 `--allow-staging` + `--authorized-writes` **双开关**且 `SMOKE_ANON_KEY/OWNER_TOKEN/OTHER_TOKEN` 三环境变量齐备,否则 exit 2;生产 6 个 host 与白名单外 host **硬拒**;candidate commit 必须 40-hex 且在本地 git;10 条固定用例;`finally` **必清理 + 读回断言残留 0**;证据 JSON 递归脱敏)、`docs/staging-synthetic-smoke.md`、`docs/release/phase-one-staging-evidence.json`(**`NOT_EXECUTED`** 骨架)、`tests/smoke/test_staging_synthetic_smoke.py`(15 条离线用例) | 独立验收实跑:`pytest tests/smoke/test_staging_synthetic_smoke.py -q` → **15 passed**;`pytest tests/unit tests/architecture -q` → **482 passed / 91 skipped**;全量无库 `pytest -q` → **694 passed / 113 skipped**;生产 host → `error: api-url production host is explicitly forbidden` exit 2;`--self-check` 裸跑**不写** canonical 证据文件(实测哈希未变),指向该文件被硬拒 exit 2。**真实 staging 运行与浏览器审计未执行(需用户授权)** |

## B. C01–C14 对 10-07 的判定

| 项 | 判定 | 依据 / 下一步 | 负责人 |
|---|---|---|---|
| C01 | ✅ 维持 | 工作树干净、`main == origin/main == 252b661`、无未跟踪残留;按 2026-09-04 决策 **main 即唯一权威分支**(不另建 release branch),发布时记录 commit SHA + 前端版本号即可 | Hermes |
| C02 | 🔴 阻断(需决策) | ADR-0002 仍写 C-only,而 `backend/app/release_scope.py:68` 已把 `ADMIN_API_CONTRACT` 并入 `PHASE_ONE_API_CONTRACT`。新范围下 **allowlist 方向与业务一致,应收窄的是 ADR 文字而非 allowlist**;需用户重批 ADR-0002 为「C 端 + 后台」 | 用户 + Codex |
| C03 | 🟡 重验条件已触发 | 仓库新增 4 条迁移 → 台账「新增迁移时」触发;09-22 `restore_drill.py`(50 版本)证据已过期。本轮已用 Management API 只读核对台账(50/54),需重跑 drill | Codex |
| C04 | 🔴 阻断 | provider 物理备份/PITR 与私有 Storage 恢复**均无证据**;需用户批准项目、成本上限、停机窗口 | 用户 + Codex |
| C05 | 🟡 需一次生产复验 | 数据库四身份有 09-20 生产证据;Storage 四角色仅 09-02 staging 证据;生产 Auth 生命周期未复验 | 用户(授权) + Codex |
| C06 | ✅ 闭合 | 实测两副本各 **6** 条、全部 `synthetic_fixture`、SHA-256 一致(`301cf824…`);非 synthetic 违规 0 | Hermes |
| C07 | ✅ 已闭合(09-24 补) | 合同 `docs/architecture/report-job-queue-contract.md` 落地:五态状态机(以 migration 的 `check (status in ...)` 为准)+ 原子认领/15 分钟租约 + `claim_token` 保护 + 三个独立幂等边界 + **取消的真实行为**(SIGTERM;无面向客户的取消入口,如实列为 known gap)+ 遗留执行器保证 + 证据索引。新增 5 条静态守护(钉死 `run_generation_job` 唯一调用点 = `report_worker.py:241`、断言无请求线程路径执行报告)+ 3 条真库用例(租约重放不重复、重入队幂等、completed 不再认领);守护测试经**变异测试**验证确有拦截力。unit+arch 476 / 真库 8 / 全量 673 | Codex ✅ |
| C08 | ✅ 已闭合(09-24 补) | 按实际架构改为 Lightsail 生产配置合同 `docs/operations/production-configuration-contract.md`(逐服务拓扑 + staging/production 边界 + `jpsskill` 受控 env_file 例外 + **全量环境变量契约** + secret 处理 + health/readiness + known gaps,并标注 `deployment status: NOT_EXECUTED`);`deploy/.env.example` 补齐 **25 个**此前未声明的键;6 条静态守护(键覆盖〔含经 `configured_limit`/超时助手传入的键〕/ 服务集 / env_file 规则 / render 仅 staging / NOT_EXECUTED 锚点 / 无密钥形态),**不依赖 PyYAML**;守护测试经**变异测试**验证确有拦截力 | Codex ✅ |
| C09 | ✅ 已闭合(09-24 补) | 三处缺口已落地:`observability.py`(请求关联 + 脱敏结构化日志)、`timeouts.py`(出站超时/重试/取消契约,默认值不变)、`docs/production-reliability.md`;`rate_limit.py`、`oncall.md`、依赖审计维持原判。剩 `NEEDS_PROD_EVIDENCE`:生产告警投递与演练未做(已在文档 `Known gaps` 诚实标注) | Codex ✅ |
| C10 | 🟡 待用户 | 隐私/删除链路代码与测试在;法务/运营签署未完成;受控删除演练未做 | 用户(法务) + Codex |
| C11 | 🟡 仅缺数值 | 09-23 已落「受邀范围」机器可读基线;**静态预算问题已消除**(最大文件 945,771 → 246,943 B < 524,288 B);缺用户提供的预算/SLO 数值 | 用户 |
| C12 | ✅ 收窄满足 | 每次 push 均有 gate 绿证据(`252b661` 七 job);依赖审计已纳入必填。剩「候选 commit artifact checksum 归档」一次性动作 | Hermes |
| C13 | 🟡 载体已交付(仅剩授权 + 一次运行) | **09-24 夜班**:四处交付物已落地并独立验收(见 §A A11)——默认零网络的 `--plan`、双开关门控的 `--execute`(生产 host 硬拒)、10 条固定用例、finally 清理 + 读回、脱敏证据写入、`NOT_EXECUTED` 骨架;`--self-check` 加硬守卫,**不再可能**把 canonical 证据文件写成离线假通过(实测 exit 2 且文件哈希未变)。**真实 staging 运行、cleanup 读回实测、浏览器审计仍未执行** → 需用户一次性 staging 写入授权 + `SMOKE_*` 凭据 | 用户(授权) + Codex |
| C14 | 🔴 阻断 | `production-go-live-approval.json` = `BLOCK / NOT AUTHORIZED`;旧口径「B/admin/convert/付费保持关闭」与新范围**矛盾**(新:后台同时上线、付费=单次购买) | 用户 |

## C. 10-07 阻断链(按执行顺序)

1. **一次部署批次(需用户批准)**:`git pull --ff-only` → 应用 4 条待应用迁移 → **在 `deploy/.env` 写入 `ADMIN_ENABLED=true`** → `docker compose -f deploy/docker-compose.prod.yml up -d --build nginx api worker report-worker scheduler`。验收:前端版本 = `20260923-r63`、生产迁移台账 54/54、**已登录管理员访问后台为 200(非 503)**。
2. **同批处理注册门(顺序不可颠倒)**:迁移应用后**先**确认邀请端点可用,**再**把 `disable_signup` 切 `true`;否则会出现「公共注册已关、邀请注册不可用 = 无人能注册」。验收:非邀请注册被拒、邀请码注册成功。
3. **C04/C05 生产证据(需授权 + 成本上限)**:provider 备份或 clone + 私有 Storage 恢复 + 四身份复验(禁止 SSH,禁止把本机结果当生产证据)。
4. **C13 staging candidate smoke 证据包** —— ✅ **工程载体已交付(2026-09-24 夜班,见 §A A11)**;剩:用户一次性 staging 写入授权 + `SMOKE_ANON_KEY`/`SMOKE_OWNER_TOKEN`/`SMOKE_OTHER_TOKEN` → `scripts/staging_synthetic_smoke.py --execute --allow-staging --authorized-writes`(自动比对 `?v=` 与 `deploy/frontend-version.txt`、finally 清理 + 读回)→ 浏览器审计(`--browser-evidence`)→ 证据文件由 `NOT_EXECUTED` 变为实测结果。
5. ~~**C07/C08/C09 收窄后的合同与可观测缺口**~~ → ✅ **已全部闭合(2026-09-24)**:C09 可观测/出站超时契约、C07 报告队列合同与证据、C08 生产配置合同(均含静态守护测试,并经变异测试验证)。三者剩余的仅为 `NEEDS_PROD_EVIDENCE` 类项(生产告警投递、告警/恢复演练),不构成工程缺口。
6. **C02 ADR 重批(用户)+ C10/C11 用户数值**。
7. **C14 逐项授权**:六位 owner、批准时间、回滚 smoke、30 分钟/24h 观察窗。

## D. 本轮实测命令与输出(证据)

```text
git status --porcelain                              → 空(工作树干净)
git rev-list --count origin/main..main              → 0 ;HEAD = 252b661
gh run list --limit 6                               → 252b661 Release Gate success (run 35862699493)
backend/.venv/bin/python -m pytest tests/unit tests/architecture -q → 457 passed / 91 skipped
backend/.venv/bin/python -m compileall -q backend scripts src        → OK
node --check web/app.js                             → OK ;git diff --check → 干净
shasum -a 256 data/content_library.json web/content-library.json     → 301cf824…(两份一致,各 34,641 B)
ls supabase/migrations/*.sql | wc -l                → 54
GET api.supabase.com/v1/projects/fnogxuytbabxmqousifh/database/migrations → 200,50 条,最新 20260922000100
GET api.supabase.com/v1/projects/…/config/auth      → disable_signup=false ;mailer_autoconfirm=false
curl -w '%{http_code}' api.zoubeacon.com/api/admin/{overview,collection/runs,service/tasks} → 401 / 401 / 401
curl api.zoubeacon.com/health/ready                 → {"status":"ready","database":"ok"}
curl zoubeacon.app                                  → 200(资源 ?v=20260917-r61);platform.zoubeacon.com/admin.html → 200
实测缺失(ls 返回 No such file):backend/app/{observability,timeouts,supabase_config}.py、
docs/production-{readiness,reliability}.md、docs/architecture/report-job-queue-contract.md、
docs/release/phase-one-staging-evidence.json、scripts/{audit_provenance,staging_synthetic_smoke}.py、render.production.yaml
```

> 未做:任何 DB 写入、迁移应用、部署、DNS/凭据变更、删除;生产侧仅上述只读 GET 探测(未使用任何用户或管理员凭据登录)。

## E. 2026-09-24 夜班:C13 载体交付的实测输出(证据)

```text
git status --porcelain                    → 空(班前);交付后仅 4 个新增文件(未跟踪,由 Hermes 提交)
backend/.venv/bin/python -m pytest tests/smoke/test_staging_synthetic_smoke.py -q   → 15 passed
backend/.venv/bin/python -m pytest tests/unit tests/architecture -q                → 482 passed / 91 skipped
backend/.venv/bin/python -m pytest -q(全量,无库)                                  → 694 passed / 113 skipped
PYTHONPYCACHEPREFIX=/tmp/jp-pycache backend/.venv/bin/python -m compileall -q scripts tests/smoke → OK
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --plan                 → exit 0;打印白名单/candidate c4962b8…/r63/fixture 字节数与 SHA-256/端点/清理计划
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --plan --api-url https://api.zoubeacon.com → error: api-url production host is explicitly forbidden(exit 2)
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --execute              → error: --execute requires --allow-staging …(exit 2)
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --execute --allow-staging --authorized-writes → error: --execute requires environment variables: SMOKE_ANON_KEY, SMOKE_OWNER_TOKEN, SMOKE_OTHER_TOKEN(exit 2)
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --plan --candidate-commit deadbeef → error: candidate commit must be a 40-character hexadecimal SHA(exit 2)
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --self-check           → 只打印证据,不写文件;canonical 证据文件 SHA-256 前后一致(c5025853…)
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --self-check --evidence-out docs/release/phase-one-staging-evidence.json → error: canonical 证据文件只允许真实 staging 运行写入(exit 2)
```

> 本轮未做:任何 DB 写入、迁移应用、部署、SSH、连 staging/production、删除;未使用任何凭据。Codex 沙箱内的 1 例失败为沙箱禁止本地端口绑定所致(本机复跑该集合 482 passed / 91 skipped,无失败)。
