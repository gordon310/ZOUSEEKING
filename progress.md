# Project Progress

## Current status

- 当前正在开发：会员查询与房产报告生成流程
- 当前主要前端：`web/`
- 当前主要后端：`backend/app/`
- Supabase 与 FastAPI 路径仍未完全统一

## Recently completed

- 重构根目录与子目录 `AGENTS.md`
- 精简 `CLAUDE.md`
- 新增 `.gitignore`
- Git 仓库初始化完成
- `web/content-library.json` 从 Git 跟踪中移除
- `web/library/` 从 Git 跟踪中移除

## In progress

- 检查 Codex 使用额度是否明显下降
- 继续梳理生成文件与源码边界

## Investigation completed (2026-08-27)

- `web/library/` 的唯一实际写入入口是 `scripts/generate_xhs_package.py::sync_web_library()`；CLI、Osaka/Yokohama builder 和 local worker 都通过 `generate()` 进入该路径。Tokyo 23 区 builder 只采集并写配置，不直接生成网站图片。
- `generate()` 会同时写入 canonical `data/content_library.json`、被忽略的 `web/content-library.json`，并复制图片到被忽略的 `web/library/<slug>/images/`。当前两份 JSON 都是 70 条记录且 SHA-256 一致；图片目录约 14MB、210 个文件。
- 测试入口是 `pytest tests/unit tests/smoke -q`，但仓库没有 `backend/requirements-dev.txt`，当前环境未安装 `pytest`；`node --check web/app.js`、Python `compileall`、CLI help 和 `pip check` 已通过。SQL 测试需要 `psql` 与测试数据库，本次未执行。
- 会员路径仍有架构冲突：前端只有配置 `API_BASE_URL` 时才提交 FastAPI；否则查询只落本地历史，Supabase 主要用于远程读取、profile 和 Edge Function。local worker、FastAPI background task、Edge Function 仍会分别处理生成任务。
- `backend/app/db.py` 默认初始化旧 `backend/sql/schema.sql`，但 FastAPI 已依赖 `owner_user_id`；`supabase_schema.sql` 仍含匿名全表策略，`002_private_project_rls.sql` 是未纳入 `supabase/migrations/` 的独立 forward script。Edge Function 还以 email 作为可选归属判断，存在空 email 时无所有权校验的风险。

## Authority-path check (2026-08-27)

- 目标架构已经在 `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md` 和 Osaka intake 计划中写明：新单项目分析采用 `FastAPI → Supabase Auth/PostgreSQL/私有 Storage`，前端不直接写私有业务数据；旧区域报告流程暂时保持不变。
- 实际代码尚未收敛：`web/app.js` 仍按配置在 Supabase REST 与 `jphouse-run` Edge Function 之间切换；`scripts/run_jphouse_worker.py` 仍用 service-role 直接消费同一队列；`backend/app/main.py` 还有进程内 `BackgroundTasks`；Edge Function 使用 `verify_jwt=false`、公开 CORS，并以可选 email 判断归属。
- 数据库边界也未统一：`backend/app/db.py` 默认执行旧 `backend/sql/schema.sql`，而 `backend/sql/001–003` 不在 `supabase/migrations/`；`backend/sql/supabase_schema.sql` 仍包含匿名读写策略。（该检查完成时尚未执行线上数据库或部署变更。）
- 当前推荐基线：确认 FastAPI 为新单项目唯一业务 API，Supabase 仅承担 Auth、PostgreSQL 和私有 Storage；确认后先建立唯一 migration history，再进入现有 Osaka intake 计划 Task 1。

## Next tasks

1. 已完成对 `zoubeacon-staging` 应用 migration 004，并验证 foundation 表、intake 表、RLS 和约束；已创建并验证 private `property-intake` bucket（20 MiB，仅 `application/pdf`、`image/jpeg`、`image/png`，未添加针对该 bucket 的 object policy）。
2. 已在 Render staging API 配置 `SUPABASE_SERVICE_ROLE_KEY`、新生成的 `ABUSE_HASH_SALT`；`INTAKE_BUCKET=property-intake` 已由 Blueprint 同步，现有 Supabase staging 连接信息保留；只通过 `render.yaml` 的 `sync: false` 声明 secret 键名。
3. 已完成 staging 仅含 `synthetic_fixture` 的 smoke flow：匿名会话、文字/PDF、字段确认、预览、用户 A 转正、用户 B 拒绝、幂等转换和过期清理；测试数据已回收。
4. 继续拆分旧区域报告的 Supabase REST / Edge Function / local worker 路径；在独立架构决策前不把它们并入新 intake API。

## Osaka intake implementation (2026-08-27)

- 已完成 Task 1–6 的本地实现：forward-only intake schema、匿名 token、字段契约、完整度/免费预览、参数化 repository、私有 Supabase Storage adapter、FastAPI intake routes。
- 已完成 Task 7 的本地页面：`web/property-analysis.html`、独立 CSS 和 ES modules；现有区域行情 `web/app.js` 保持不变，首页增加“分析一个日本房产”入口。
- 已完成 Task 8 的离线契约：前端 intake bundle 不含 service-role key 或客户端所有权字段，匿名会话只写 `sessionStorage`；`render.yaml` 只声明 staging secret 键名，不含 secret 值。
- 已安装并验证 Supabase CLI `2.116.0`，CLI profile `codex-local` 已登录；已通过只读项目列表、linked dry-run 和远端 migration history 确认 `zoubeacon-staging` ref 为 `fnogxuytbabxmqousifh`，migration 004 已完成推送。
- 本地验证：`36 passed`（unit/api/smoke）、Playwright Chrome `3 passed`（移动端免费预览、非法文件错误状态、已登录保存）、Python compileall、三个 JS `node --check`、`pip check` 均通过。
- 已完成 staging migration 004 验收：远端 history 与本地一致，schema assertions 通过，dry-run 报告 `Remote database is up to date`。
- 已完成 staging Storage bucket 验收：控制台显示 bucket 创建成功；SQL Editor 只读查询确认 `public=false`、`file_size_limit=20971520`、三个 MIME 类型配置正确，匹配的 object policy 数为 0。
- Render staging 部署：`zouseeking-api-staging` 已从 GitHub `main` 的 `c376099` 构建并上线；Render 内部 `/health/ready` 返回 `200 OK`，服务连接数据库成功。已配置 intake 所需 secrets 与 `INTAKE_BUCKET=property-intake`，未将 secret 写入仓库。
- 已修正 Render staging 的 Auth 公钥配置：旧 `SUPABASE_ANON_KEY` 已失效，已替换为当前 staging publishable key 并重新部署；key 的实际值未写入仓库或文档。
- Storage 创建后的离线回归：`PYTHONPATH=. backend/.venv/bin/pytest tests/unit tests/api tests/smoke -q` → `36 passed`；Python `compileall` 与三个前端 JS `node --check` 均通过。
- staging synthetic smoke 已通过：`/health/live`、`/health/ready` 均为 200；文字/PDF、字段确认和预览均成功，预览保持 `comparable_status=not_checked` 且未生成虚假的取得成本总额；用户 A 转正为 200，重复转正复用同一 property，用户 B 读取和转正均为 404。
- 过期清理已通过：会话转为 `expired`，对应 private Storage 对象被删除；3 个临时会话、property 和 2 个临时 synthetic Auth 用户均已删除，清理后目标记录与对象计数均为 0。
- 尚未执行：真实账号或真实用户文件 smoke test；本次线上验证未使用真实账号或真实房产资料。
- 已知边界：当前使用 Playwright fallback，因为 `browse` CLI 不可用；Image Gen 概念图请求返回 404，因此视觉 QA 以仓库现有视觉系统和本地截图为基准。

## Known issues

- Supabase 与 FastAPI 存在重复实现
- 部分权限与 RLS 仍需验证
- `data/content_library.json` 与 Web 端生成内容存在同步关系
- 生成目录较大，不应默认参与 Codex 全仓扫描

## Fast-track backend staging release (2026-08-30)

- 已将基于远端 `main` 的 `codex/release-candidate` fast-forward 推送到 GitHub `main`（`e8f9465`），触发 `zouseeking-api-staging` 自动部署。
- Render staging 验证通过：`/health/live`、`/health/ready`、`/openapi.json` 均返回 `200`；`/health/ready` 报告 `database=ok`。
- OpenAPI 已包含 `/api/intake/sessions`、`/api/intake/sessions/{session_id}/location`；未认证项目读取返回 `401`。
- 本次仅发布后端代码，未执行 Supabase migration、数据库写入、生产部署或真实用户数据测试。
- 完整 migration baseline reconciliation、备份恢复和 V1 业务表继续延期到单独批准窗口。

## C04 provider backup 与隔离恢复（2026-08-31）

- 已确认项目尚未上线，前期费用上限为 `JPY 0`；数据库/Auth/Storage 继续采用 Supabase Free，暂不创建 Render 付费数据库、启用 PITR 或创建 provider clone。
- 已加入 `scripts/database_recovery.py`、`docs/operations/database-recovery-runbook.md`、证据模板和聚焦单元测试；工具只接受 loopback maintenance database、`jpp_restore_` 一次性目标，先校验 SHA-256/TOC，首个断言失败即停止并仅清理自己创建的目标。
- `PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit/test_database_recovery.py -q` → `8 passed`。
- 当前 release candidate 使用 `jpp-canonical-local-full-exec-20260831-v2.dump`（SHA-256 `b9e521827d32647157cf1676bf53a2e9e0e2fd4149bba189fd6f886b466dc215`、PostgreSQL `17.6`、pg_dump `18.6`）；checksum/TOC、foundation/intake/private-RLS 三组断言和目标清理均为 `pass`。报告保留在受限临时目录，未提交仓库。
- 本地演练负责人按已确认角色记录：`database_owner=数据库运维`、`backup_operator=备份`、`recovery_lead=任务派发`、`release_owner=版本发布`、`forward_fix_owner=后台审核`、`incident_commander=超级管理员`；`security_reviewer=系统安全`、`billing_owner=财务`未参与本地演练。
- provider backup、Storage object backup、隔离 clone、live forward-fix 仍为 `deferred/blocked`，因此 C04 尚未达到 production release pass；正式上线前必须重新取得明确的费用、保留期、清理窗口和 provider 恢复批准。

## C05 baseline/RLS 验收预检（2026-08-31）

- 已在本地 canonical disposable PostgreSQL 上复核 11 条 migration ledger：`20260824000100`–`20260824000700`、`20260825000400`、`20260827000500`、`20260828000100`、`20260829000100`。
- 五组本地断言全部通过：foundation、property-intake、provenance/metric、private-project RLS、V1 identity matrix；本次只使用本地 synthetic/empty 数据，断言事务已回滚。
- candidate 离线回归：`PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit tests/architecture tests/smoke tests/api -q` → `95 passed`；Edge authority tests → `2 passed`；Python compileall 与 `web/js`/`app.js` 的 `node --check` 均通过。
- staging 只读 migration dry-run：普通 dry-run 因早期本地 migration 位于远端末尾而停止；`--dry-run --include-all` 仅报告将推送 `20260824000100`–`20260824000700` 与 `20260829000100`，未执行写入。
- staging 的 live reconciliation 未执行：没有 provider backup/隔离 clone、没有可用 direct staging database URL，existing-row provenance 尚未分类，也没有创建或应用 later-ID forward migration。
- 未执行 linked `db push`、`migration repair`、staging/production reset 或任何线上写入；C05 的 live 部分保持 `BLOCKED`，不影响继续推进不依赖 live 数据的后续离线任务。

## C06 provenance 与授权来源离线审计（2026-08-31）

- 对 release candidate 的 `content-library.json` 做只读 formal provenance 审计：70 条记录中 `publishable_records=0`、`issue_count=70`；未自动补写 provenance 或 rights。
- 两份 `data/input/*.csv` 均因缺少 `aggregation_method`、`limitations`、`method`、`missing_value_policy`、`observed_at`、`retrieved_at`、`rights_status`、`sample_size`、`source_period`、`version` 而阻断；没有记录被提升为可发布数据。
- `content-library.json` 与 `web/content-library.json` SHA-256 均为 `eb0fefae86a04204d9c0682f69e76a21497fcd1f18f5b8c4aa631197a1b71d1e`，仅证明生成副本一致，不证明来源权利或统计代表性。
- 审计报告：`docs/architecture/provenance-audit-2026-08.md`。未联网、未写数据库、未改生成文件；C06 的 formal contract 集成仍需 canonical 路径、授权 manifest 和 later-ID migration 评审，状态保持 `BLOCK / NOT AUTHORIZED`。

## C07–C13 后续离线候选验收（2026-08-31）

- 在各自隔离候选 worktree（未自动合入本 release candidate）完成专用回归：C07 durable worker `26 passed`，C07 legacy path retirement `16 passed`，C08 production config/auth/readiness `12 passed`，C09 reliability/rate-limit/observability `19 passed`，C10 privacy operations `16 passed`，C11 capacity/unit/api/performance `71 passed`，C12 release-gate/evidence/secret-scan/static-server `21 passed`。
- C13 staging synthetic smoke 离线 runner `16 passed`；`--mode offline --run-id c13-offline-20260901` 返回 `status=passed`，覆盖 health、匿名 session、text/PDF、location、preview、跨用户隔离、幂等与清理。该结果不代表 staging live 或 production。
- C11 离线容量探针实测：FastAPI synthetic 100/100、DB pool 50/50、bounded queue 20/20 均通过预算；静态总量 `1,520,420B` 在 2MiB 内，但 `web/assets/logoELE.png` 为 `945,771B`，超过单文件 `524,288B`，所以整体 verdict 为 `FIX`。未据此进行图片删除或压缩。
- C12 供应链补充检查：`npm audit --offline --audit-level=high` 返回 `found 0 vulnerabilities`，但 registry advisory 请求在当前环境 DNS 失败；`pip-audit`/`pip_audit` 不存在。因此仅记录为本地缓存结果，不能替代在线 advisory feed，C12 仍未达到完整 gate pass。
- 当前 release candidate 直接 secret scan `PASS`；C12 policy scan 已在集成 release gate 后为 `PASS`。浏览器离线回归首次发现候选缺失 `data/content_library.json`；已从同哈希生成源补齐后重跑，当前 `22 passed`。
- C07–C11 候选代码仍需逐文件 review 后再集成；C12 release gate 已纳入本候选。未执行 GitHub Actions、`pip-audit`（当前环境无 `pip_audit` 模块）、staging load、线上 Auth/DB/Storage、deployment 或 DNS。SQL/RLS 与 provider 证据缺失时，任何候选均不得标为 production pass。

## C14 Go/No-Go 模板（2026-08-31）

- 已新增 `docs/release/production-go-live-approval.json` 与 `docs/release/production-release-evidence.json`；已写入已确认角色、保留期 7 天、清理窗口 `2026-09-01 02:00–03:00 JST`、费用上限 `JPY 0` 与 provider backup/clone 延后策略。
- 模板中的 live action、provider change、deployment、DNS、backup ID、commit 和 checksum 均保持未授权/null；不会被脚本当作可执行目标。
- C14 仍为 `NOT_EXECUTED`；在 C03–C13 证据闭合并取得逐项明确授权前，不执行任何 production 或 staging 写入。

## C14 Go/No-Go 复核（2026-09-01）

- 已复核角色、`retention_days=7`、`cost_cap_jpy=0`、`cleanup_window_jst=2026-09-01 02:00–03:00`、Storage `property-intake` 与 provider object backup 延后策略；模板目标、backup ID、deployment commit/checksum 继续为 null/false。
- 当前结论仍为 `BLOCK / NOT AUTHORIZED`：migration baseline 尚需 live reconciliation，provider backup/isolated clone 在 JPY 0 下未获批，SQL/RLS、Auth/Storage、deployment/DNS/billing live 证据未执行；C06 provenance `70/70` 阻断、C11 单文件预算 `FIX`、C12 npm/pip advisory 未闭合。

## P1 离线候选预检（2026-09-01）

- C06 formal provenance 候选隔离回归：Python contract/report/audit `33 passed`、Node web/authorization `6 passed`、worker contract `2 passed`；候选实现未合入本 release candidate，历史内容仍按审计结果阻断。
- P1 Stripe offline boundary `38 passed`、数据质量 pipeline `26 passed`；均为 fixture/mock 验证，未连接 Stripe、未收费、未写入真实数据，不能替代 C14 后的 staging UAT。

## C01–C03 候选归档与整合回归（2026-09-01）

- C01/C02 架构边界与第一阶段 allowlist 已归档：`fe4b9dd`、`110358e`；C03 canonical migration baseline、legacy SQL 归类与 schema inventory 已归档：`41cafc7`。
- 整合后离线回归：Python unit/architecture/smoke/api `95 passed`；Edge authority `2 passed`；Python `compileall`、全部 `web/js` 与 `app.js` `node --check`、机器 JSON 解析均通过。
- 这些结果仍只证明 release candidate 的本地契约；staging drift、provider backup/clone、later-ID forward-fix、production deployment 和真实资料验收继续保持未执行。

## C12 发布证据包（2026-09-01）

- 已在当前 release candidate `5adbb9b3370d6a46661b0b592d470dbfe3dd8a32` 重新记录证据并生成离线包：`/private/tmp/jpp-c12-evidence.p96IcF/bundle/manifest.json`。
- 真实结果：Python `112 passed`、Edge authority `2 passed`、compileall、全部 JS syntax、secret scan、release policy、diff check 和 browser `22 passed` 均为 `PASS`；synthetic offline smoke 另行 `PASS`；SQL/RLS 为 `NOT_EXECUTED`；npm advisory 因当前环境 DNS 失败为 `FAIL`；`pip-audit` 不存在为 `BLOCKED`。manifest 仍为 `offline_gate_passed=false`、`release_ready=false`。
- manifest 的 `offline_gate_passed=false`、`release_ready=false`；外部 staging/production DB、Auth、Storage、deployment、DNS、billing 均保持 `NOT_EXECUTED`。该证据包不构成上线批准。

## C16 会员与账户控制离线契约（2026-09-01）

- 新增 `backend/app/account_controls.py`：用户可编辑资料 allowlist、服务端管理字段拒绝、12–128 位密码基线、统一认证失败响应、15 分钟近期认证、B 端 5 席位 owner/member 边界、内部角色最小权限与套餐不授予后台角色。
- 前端 `web/app.js` 与根 `app.js` 移除 `localStorage` 本地密码哈希/注册/登录回退；仅接受 Supabase Auth 或明确 `demo` 会话。资料服务未开放或 demo-only 页面不会创建 profile 或写入私有表；历史本地会话不再作为认证凭据。
- 注册/登录/密码更新失败不再透传 provider 原始错误；注册页面和密码修改页面同步显示 12 位密码基线。B 端浏览器演示 fixture 改用 `provider=demo`。
- 聚焦测试：`tests/unit/test_account_controls.py` `8 passed`；`tests/web/account-controls.spec.js` `2 passed`；整合回归 `132 passed`、Playwright `25 passed`；JS syntax、Python compileall、`git diff --check`、release policy 和 secret scan 均为 `PASS`。
- 本任务只完成离线契约和静态行为，未新增/应用 migration，未触碰真实 Auth/RLS/Storage、provider backup/clone、部署、DNS、计费或真实会员数据；C14 Go/No-Go 继续保持 `BLOCK / NOT AUTHORIZED`。

## C17 Stripe 计费边界离线实现（2026-09-01）

- 已整合 `backend/app/billing/` 离线边界：服务端产品/地区价格白名单与最小货币单位、Checkout/Portal/状态/取消/退款端口、原始 bytes `Stripe-Signature` 验签、唯一 `event.id` 幂等 claim/process、transient 重试、dunning outbox 与脱敏审计。
- 默认 provider/store 未注入，计费操作保持 `503 billing is not configured`；价格列表不暴露 `stripe_price_id`。Checkout 产品、金额、币种、customer 和 redirect URL 均由服务端决定，权益不由浏览器回跳开通。
- 离线验证：`tests/billing` `38 passed`；整合 Python `tests/unit tests/architecture tests/smoke tests/api tests/billing` `170 passed`；Playwright Chromium `25 passed`；Python `compileall`、JS `node --check`、`git diff --check`、release policy 与 secret scan 均为 `PASS`。
- 已更新 `docs/release/worktree-integration-manifest.json`：P1-2 标记为 `integrated`，并保留 provider gateway/store、canonical billing migration、真实 webhook delivery、税费/收据、退款演练、provider backup/restore 与 live Stripe 为后续授权门槛；C14 Go/No-Go 仍为 `BLOCK / NOT AUTHORIZED`。
- 本轮未连接 Stripe、未使用 live key、未收费、未写入线上数据库/Auth/RLS/Storage，未执行部署、DNS 或 billing 配置；下一项 C18 继续处理 usage ledger/quota 的 disposable 离线边界。

## C18 用量账本与配额离线契约（2026-09-01）

- 已整合 `backend/app/usage/`：线程安全的 in-memory ledger、UTC+08:00 自然日/月账期、owner/organization scope 隔离、scope-wide operation 幂等指纹、`consume` 与 `reserve/commit/release` 原子语义、原账期 reservation transition 和 quota 容量检查。
- 新增默认关闭的 `POST /api/usage/events`：客户端不能提交 `user_id`、scope 或 limit；可信服务端依赖负责身份、scope 与配额解析。未知故障只返回通用 `503 usage_unavailable`，未配置 service 时返回 `503 usage service is not configured`。
- 离线契约文档：`docs/release/usage-ledger-offline-contract.md`；未新增或应用 `supabase/migrations/`，未扩大 `consumer_intake_preview` allowlist。
- TDD 证据：先运行缺失实现的 RED（collection `ModuleNotFoundError`），再运行 `tests/unit/test_usage_ledger.py tests/api/test_usage_routes.py` → `13 passed`；覆盖日本时间边界、幂等冲突、配额不变性、scope 隔离、跨日 reservation、释放状态与 8 路并发 limit=1。
- 本轮未执行：真实 PostgreSQL/multi-instance 原子性、migration baseline reconciliation、Auth/RLS、真实会员/组织配额、Stripe entitlement 绑定、staging/production UAT、provider backup/restore、部署、DNS、billing 或线上写入；C14 Go/No-Go 继续为 `BLOCK / NOT AUTHORIZED`。

## C19 数据质量与来源登记离线候选（2026-09-01）

- 已整合 `src/jp_property_publisher/pipeline.py` 与 CLI `prepare`/`quality-check`：严格 CSV、来源 registry、snapshot manifest、本地 SHA-256/字节数重算、捕获时间/source period/parser version、数值/单位/币种、重复、异常值、权限和数据类别门禁均可离线重放。
- `configs/data_quality_policy.json` 固定 `trend-policy-v1`：至少 3 个可比月份、每月 5 条、总计 15 条，并按区域、租售、`listing`/`closed`、数据类别、单位和币种分组；指标用中位数并保留样本数、期间、来源/快照和限制。`modeled_estimate` 不进入事实指标，`synthetic_fixture` 只允许 fixture scope，混合 fixture/事实会阻断发布。
- 新增 `data/source_registry.json` 的 pending placeholder 与可重放 `tests/fixtures/data_pipeline/` synthetic fixture；没有自动补写 rights/provenance，也没有改写现有输入数据。
- TDD 证据：先运行缺失 pipeline 的 RED（collection `ModuleNotFoundError`），再运行数据流水线/CLI/既有 CLI 聚焦测试 → `34 passed`；整合回归 `tests/unit tests/architecture tests/smoke tests/api tests/billing` → `216 passed`，CLI fixture prepare 退出码 `0`（30 条 prepared、6 条指标、`publishable=true`、`publication_scope=fixture_only`），Playwright Chromium `25 passed`，compileall、JS syntax、pip check、release policy、secret scan、JSON parse 和 diff check 均为 `PASS`。
- 本轮未执行：联网抓取、真实来源授权或历史重建、数据库/migration/RLS、生产 provenance 写入、真实数据发布、staging/production UAT、provider backup/restore、部署、DNS、billing 或线上写入；P1-5 privacy/retention 顺延 C20，C14 Go/No-Go 继续 `BLOCK / NOT AUTHORIZED`。

## Important decisions

- `data/content_library.json` 作为本地 canonical content library
- 生成文件不作为主要源码判断依据
- Codex 默认使用 scoped investigation，不做无必要全仓扫描

## Last updated

2026-09-01
