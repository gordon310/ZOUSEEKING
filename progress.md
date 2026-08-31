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
- `PYTHONPATH=. /Users/gordonmac/GordonDev/JPPropDIs/backend/.venv/bin/python -m pytest tests/unit/test_database_recovery.py -q` → `8 passed`。
- 当前 release candidate 使用 `jpp-canonical-local-full-exec-20260831-v2.dump`（SHA-256 `b9e521827d32647157cf1676bf53a2e9e0e2fd4149bba189fd6f886b466dc215`、PostgreSQL `17.6`、pg_dump `18.6`）；checksum/TOC、foundation/intake/private-RLS 三组断言和目标清理均为 `pass`。报告保留在受限临时目录，未提交仓库。
- 本地演练负责人按已确认角色记录：`database_owner=数据库运维`、`backup_operator=备份`、`recovery_lead=任务派发`、`release_owner=版本发布`、`forward_fix_owner=后台审核`、`incident_commander=超级管理员`；`security_reviewer=系统安全`、`billing_owner=财务`未参与本地演练。
- provider backup、Storage object backup、隔离 clone、live forward-fix 仍为 `deferred/blocked`，因此 C04 尚未达到 production release pass；正式上线前必须重新取得明确的费用、保留期、清理窗口和 provider 恢复批准。

## Important decisions

- `data/content_library.json` 作为本地 canonical content library
- 生成文件不作为主要源码判断依据
- Codex 默认使用 scoped investigation，不做无必要全仓扫描

## Last updated

2026-08-27
