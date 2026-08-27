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
- 数据库边界也未统一：`backend/app/db.py` 默认执行旧 `backend/sql/schema.sql`，而 `backend/sql/001–003` 不在 `supabase/migrations/`；`backend/sql/supabase_schema.sql` 仍包含匿名读写策略。尚未执行任何线上数据库或部署变更。
- 当前推荐基线：确认 FastAPI 为新单项目唯一业务 API，Supabase 仅承担 Auth、PostgreSQL 和私有 Storage；确认后先建立唯一 migration history，再进入现有 Osaka intake 计划 Task 1。

## Next tasks

1. 已完成对 `zoubeacon-staging` 应用 migration 004，并验证 foundation 表、intake 表、RLS 和约束；已创建并验证 private `property-intake` bucket（20 MiB，仅 `application/pdf`、`image/jpeg`、`image/png`，未添加针对该 bucket 的 object policy）。
2. 在 Render staging API 的 secret 中配置 `SUPABASE_SERVICE_ROLE_KEY`、`ABUSE_HASH_SALT` 和现有 Supabase staging 连接信息；只通过 `render.yaml` 的 `sync: false` 声明键名。
3. 对 staging 运行仅含 `synthetic_fixture` 的 smoke flow：匿名会话、文字/文件、字段确认、预览、用户 A 转正、用户 B 拒绝、幂等转换和过期清理。
4. 继续拆分旧区域报告的 Supabase REST / Edge Function / local worker 路径；在独立架构决策前不把它们并入新 intake API。

## Osaka intake implementation (2026-08-27)

- 已完成 Task 1–6 的本地实现：forward-only intake schema、匿名 token、字段契约、完整度/免费预览、参数化 repository、私有 Supabase Storage adapter、FastAPI intake routes。
- 已完成 Task 7 的本地页面：`web/property-analysis.html`、独立 CSS 和 ES modules；现有区域行情 `web/app.js` 保持不变，首页增加“分析一个日本房产”入口。
- 已完成 Task 8 的离线契约：前端 intake bundle 不含 service-role key 或客户端所有权字段，匿名会话只写 `sessionStorage`；`render.yaml` 只声明待填 staging secrets，不含 secret 值。
- 已安装并验证 Supabase CLI `2.116.0`，CLI profile `codex-local` 已登录；已通过只读项目列表、linked dry-run 和远端 migration history 确认 `zoubeacon-staging` ref 为 `fnogxuytbabxmqousifh`，migration 004 已完成推送。
- 本地验证：`36 passed`（unit/api/smoke）、Playwright Chrome `3 passed`（移动端免费预览、非法文件错误状态、已登录保存）、Python compileall、三个 JS `node --check`、`pip check` 均通过。
- 已完成 staging migration 004 验收：远端 history 与本地一致，schema assertions 通过，dry-run 报告 `Remote database is up to date`。
- 已完成 staging Storage bucket 验收：控制台显示 bucket 创建成功；SQL Editor 只读查询确认 `public=false`、`file_size_limit=20971520`、三个 MIME 类型配置正确，匹配的 object policy 数为 0。
- Render staging 预检查：`zouseeking-api-staging` 服务已存在并关联 GitHub `main`；当前 dashboard 环境变量已有数据库与 Supabase 基础配置，但尚未加入 intake 所需的 `SUPABASE_SERVICE_ROLE_KEY`、`ABUSE_HASH_SALT`、`INTAKE_BUCKET`。本地 intake 改动尚未提交/推送，暂不能直接部署当前版本。
- Storage 创建后的离线回归：`PYTHONPATH=. backend/.venv/bin/pytest tests/unit tests/api tests/smoke -q` → `36 passed`；Python `compileall` 与三个前端 JS `node --check` 均通过。
- 尚未执行：Render deploy、真实账号或真实用户文件 smoke test。
- 已知边界：当前使用 Playwright fallback，因为 `browse` CLI 不可用；Image Gen 概念图请求返回 404，因此视觉 QA 以仓库现有视觉系统和本地截图为基准。

## Known issues

- Supabase 与 FastAPI 存在重复实现
- 部分权限与 RLS 仍需验证
- `data/content_library.json` 与 Web 端生成内容存在同步关系
- 生成目录较大，不应默认参与 Codex 全仓扫描

## Important decisions

- `data/content_library.json` 作为本地 canonical content library
- 生成文件不作为主要源码判断依据
- Codex 默认使用 scoped investigation，不做无必要全仓扫描

## Last updated

2026-08-27
