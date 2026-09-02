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

## 小象数据 CLI 契约（2026-08-27）

- `src/jp_property_publisher/cli.py` 现在要求每条发布记录填写 `data_class`，仅接受 `verified_observation`、`scraped_aggregate`、`modeled_estimate`、`synthetic_fixture`。
- 月度统计按 `month + market + status + data_class` 分组，草稿中同步展示类别，避免不同数据类别混算。
- 两个输入样例和数据字典已同步；新测试覆盖缺失/非法类别及跨类别分组。CLI 测试与离线回归均通过。

## Investigation completed (2026-08-27)

- `web/library/` 的唯一实际写入入口是 `scripts/generate_xhs_package.py::sync_web_library()`；CLI、Osaka/Yokohama builder 和 local worker 都通过 `generate()` 进入该路径。Tokyo 23 区 builder 只采集并写配置，不直接生成网站图片。
- `generate()` 会同时写入 canonical `data/content_library.json`、被忽略的 `web/content-library.json`，并复制图片到被忽略的 `web/library/<slug>/images/`。当前两份 JSON 都是 70 条记录且 SHA-256 一致；图片目录约 14MB、210 个文件。
- 测试入口是 `pytest tests/unit tests/smoke -q`，但仓库没有 `backend/requirements-dev.txt`，当前环境未安装 `pytest`；`node --check web/app.js`、Python `compileall`、CLI help 和 `pip check` 已通过。SQL 测试需要 `psql` 与测试数据库，本次未执行。
- 会员路径仍有架构冲突：前端只有配置 `API_BASE_URL` 时才提交 FastAPI；否则查询只落本地历史，Supabase 主要用于远程读取、profile 和 Edge Function。local worker、FastAPI background task、Edge Function 仍会分别处理生成任务。
- `backend/app/db.py` 的初始化路径仍指向旧 `backend/sql/schema.sql`，但 FastAPI 已依赖 `owner_user_id`；`supabase_schema.sql` 仍含匿名全表策略，`002_private_project_rls.sql` 是未纳入 `supabase/migrations/` 的独立 forward script。Edge Function 还以 email 作为可选归属判断，存在空 email 时无所有权校验的风险。

## Authority-path check (2026-08-27)

- 目标架构已经在 `docs/superpowers/specs/2026-08-25-osaka-residential-analysis-design.md` 和 Osaka intake 计划中写明：新单项目分析采用 `FastAPI → Supabase Auth/PostgreSQL/私有 Storage`，前端不直接写私有业务数据；旧区域报告流程暂时保持不变。
- 实际代码尚未收敛：`web/app.js` 仍按配置在 Supabase REST 与 `jphouse-run` Edge Function 之间切换；`scripts/run_jphouse_worker.py` 仍用 service-role 直接消费同一队列；`backend/app/main.py` 还有进程内 `BackgroundTasks`；Edge Function 使用 `verify_jwt=false`、公开 CORS，并以可选 email 判断归属。
- 数据库边界也未统一：`backend/app/db.py` 的初始化路径仍指向旧 `backend/sql/schema.sql`，而 `backend/sql/001–003` 不在 `supabase/migrations/`；`backend/sql/supabase_schema.sql` 仍包含匿名读写策略。（该检查完成时尚未执行线上数据库或部署变更。）
- 当前推荐基线：确认 FastAPI 为新单项目唯一业务 API，Supabase 仅承担 Auth、PostgreSQL 和私有 Storage；确认后先建立唯一 migration history，再进入现有 Osaka intake 计划 Task 1。

## Next tasks

1. 已完成对 `zoubeacon-staging` 应用 migration 004，并验证 foundation 表、intake 表、RLS 和约束；已创建并验证 private `property-intake` bucket（20 MiB，仅 `application/pdf`、`image/jpeg`、`image/png`，未添加针对该 bucket 的 object policy）。
2. 已在 Render staging API 配置 `SUPABASE_SERVICE_ROLE_KEY`、新生成的 `ABUSE_HASH_SALT`；`INTAKE_BUCKET=property-intake` 已由 Blueprint 同步，现有 Supabase staging 连接信息保留；只通过 `render.yaml` 的 `sync: false` 声明 secret 键名。
3. 已完成 staging 仅含 `synthetic_fixture` 的 smoke flow：匿名会话、文字/PDF、字段确认、预览、用户 A 转正、用户 B 拒绝、幂等转换和过期清理；测试数据已回收。
4. 已完成旧区域报告第一阶段路径分流（FastAPI manual-run、Edge owner guard、worker 原子抢占）；后续仍需独立架构决策，不能把旧流程并入新 intake API。
5. 已完成 FastAPI schema 自动初始化的 fail-closed 保护：默认不初始化，且仅在明确的 `local`/`development`/`test` 环境并设置 `INIT_SCHEMA=true` 时执行；staging/production 继续使用独立的 forward migration。
6. 已新增 `supabase/migrations/20260827000500_legacy_private_data_rls.sql`：移除旧区域私有表的匿名权限和普通用户写权限，保留登录用户按 `owner_user_id` 只读本人任务/报告，并锁定会员等级与额度字段；尚未应用到线上。

## Legacy regional execution boundary (2026-08-27)

- 已完成第一阶段分流：API 已配置且用户已认证时，Mypage 的旧区域任务走 FastAPI `POST /api/jobs/{job_id}/run`，按 `owner_user_id` 查询并用条件更新原子抢占；前端轮询 `/api/jobs/{job_id}`，不再调用 Edge Function。
- Edge Function 保留为旧兼容路径，`verify_jwt=true`，并要求 `queries.owner_user_id` 与当前 Auth 用户 ID 非空且匹配；缺少归属按不存在处理。
- local worker 处理 `generation_jobs` 前使用 `status=eq.pending` 条件更新抢占，抢不到的任务跳过，避免多个 worker 重复生成。
- 验证：新增 API 2 项、Edge 授权 1 项、worker 2 项和 Playwright 分流 1 项；Python/前端语法检查与原有测试均通过。尚未部署或在线验证本次 Edge/worker 改动。

## Startup schema initialization guard (2026-08-27)

- 审计指出 `backend/app/main.py` 原先在未配置 `INIT_SCHEMA` 时默认执行旧 `backend/sql/schema.sql`，并且仅依赖环境变量约定，存在在错误数据库上自动建表或覆盖迁移边界的风险。
- 现在 `should_init_schema()` 只有在 `INIT_SCHEMA=true` 且 `ENVIRONMENT` 明确为 `local`、`development` 或 `test` 时才允许初始化；未配置或 staging/production 环境均跳过。
- `backend/README.md` 和 `docs/render-postgres-deploy.md` 已同步说明默认关闭、允许环境和 migration 要求。
- 新增 `tests/unit/test_schema_initialization.py`，覆盖默认关闭、staging 拒绝和明确 development 开启。

## Legacy private RLS hardening (2026-08-27)

- 审计确认旧 `backend/sql/supabase_schema.sql` 曾为 `queries`、`generation_jobs`、`property_reports` 和 `data_sources` 创建匿名全表读写策略，旧 RLS 脚本还允许 `authenticated` 直接写任务状态。
- 基础 setup 脚本现在默认撤销这些私有表的匿名权限；正式 forward migration `20260827000500_legacy_private_data_rls.sql` 会重建策略：匿名无权限，登录用户只能读取自己拥有或关联的记录，查询/任务/报告/数据源写入由受信任后端负责。
- `user_profiles` 的会员等级和每日额度通过 trigger 保护，用户仍可读写自己的普通资料字段；没有从旧 email 字段自动回填 `owner_user_id`，避免把不可信身份映射成所有权。
- `tests/security/test_rls_private_projects.sql` 已增加表权限、匿名角色和 `authenticated` 写权限断言。当前环境没有 `psql` 或本地 Postgres，因此本轮未执行该 SQL 回归；未做线上 migration/deploy。

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

## Important decisions

- `data/content_library.json` 作为本地 canonical content library
- 生成文件不作为主要源码判断依据
- Codex 默认使用 scoped investigation，不做无必要全仓扫描

## Product and data-collection decisions (2026-08-27)

- 产品边界：C 端应用统一称为“小象避坑 / ZOUBEACON”；B 端数据仓库统一称为“小象数据 / ZOUSEEKING”。现阶段暂保留在同一仓库，以模块和权限边界区分，后期再考虑拆分部署。
- 数据采集采用混合模式：官方/地方公开数据、已授权合作方数据、受控网页聚合数据、用户主动提交资料，以及人工复核；不做无授权全网爬取、反爬绕过或复制受保护房源内容。
- 正式流水线：来源登记 → 定时/手动采集 → 不可覆盖的原始快照与哈希 → 解析标准化 → 质量检查 → 人工复核 → 数据仓库 → 指标与报告。每条数据保留来源、时间、权限、解析版本和证据。
- 当前采集脚本仍是原型（SUUMO/Tochidai 页面抓取、CSV 校验和 JSON 生成），上线前需补授权、快照、证据、失败告警和质量检查。
- C 端链接、PDF、图片和文字先进入私有项目空间；第一阶段只安全保存并标记人工审核，不自动执行 OCR、AI 提取、税费计算或法律结论。后续 AI 只能生成带证据定位的候选字段，经用户/人工确认后使用。
- 更新节奏建议：房源每日或按需，区域租售每周，人口/土地/灾害等每月或季度，政策法规事件触发并定期复核。定时任务应由独立 worker/调度器执行。
- 字段扩展遵循“数据字典 + forward migration + 解析映射 + 测试 + 报告更新”；核心分析字段使用关系型列，来源差异字段使用 JSONB。修改字段含义、单位、区域或指标口径需版本化。

## ZOUBEACON intake UI (2026-08-27)

- 已按确认的移动端/桌面端方案重做 `web/property-analysis.html` 与 `web/property-analysis.css`：小象避坑 / ZOUBEACON 品牌、五步流程、移动纵向步骤与底部导航、桌面右侧分析进度、识别字段和免费预览卡片。
- 已将右侧完整度、识别字段、字数计数、文件选择/拖拽状态和菜单键盘行为接入现有 intake 状态；没有加入静态房源示例值，也没有改动后端或数据存储流程。
- 已增加响应式与进度联动 Playwright 用例，并收窄重复桌面/移动节点的定位；`npm run test:web` → `6 passed`。浏览器检查覆盖桌面首屏、390×844 移动截图、菜单 Escape 返回焦点和控制台 error/warning（无）。
- 视觉 QA 使用用户提供的 ZOUBEACON 参考图与本地页面截图；本地静态服务器不提供 `/api` POST，真实提交仍需通过配置的 FastAPI API 验证，未使用真实房产资料。

## ZOUBEACON report deliverables (2026-08-28)

- 已按确认方案补齐项目工作台的免费预览报告样式：资料完整度、购入费用项目、资料提醒、可比数据状态、优先确认事项和收费版内容引导。
- 已补齐收费完整版报告样式：行动结论、项目基本信息、来源与可信度、市场比较、成本模型、自住、投资、法律、深度风险、下一步行动、方法与免责声明共 11 章。
- 免费与收费状态可通过 `project.html?demo=1&state=preview|completed` 切换；报告版本、生成中、失败和补充资料状态保持可演示。
- 所有演示数字继续标记为 `synthetic_fixture`；缺少证据时显示“资料不足/可比样本不足”，未接入真实支付、真实报告生成或真实市场数据。
- 新增 `tests/web/project-workspace.spec.js`；全量 `npm run test:web` → `9 passed`。Playwright 桌面与 390px 移动端检查无横向溢出，控制台无 error/warning。

## Frontend flow-first review pass (2026-08-28)

- Added the C-end review surface: `web/ui-review.html`, project list `web/projects.html`, and project workspace `web/project.html`; the review page links the public query, intake, project states, legacy analysis, and account screens.
- The demo flow now covers free preview → save/register handoff → ready → running → completed/failed → retry → update; report history supports V1/V2/V3 switching, and cancelling an update does not create a new version.
- Demo-only fixture content remains explicitly labeled `synthetic_fixture`; no database schema, online migration, authentication policy, or real report-generation path was changed in this UI pass.
- Milestone verification only: JavaScript syntax/diff checks and a Playwright browser smoke flow covering version switching, update cancellation, V3 generation, screenshots, and console errors. Full data-contract review, synthetic test-data preparation, and regression tests are intentionally deferred until the screen-by-screen UI review is confirmed.
- Image Gen concept generation returned HTTP 404; visual confirmation therefore uses the existing repository visual system and local browser screenshots.

## Visual unification pass (2026-08-28)

- Unified the legacy `index`, `analysis`, `mypage`, and `profile` surfaces with the ZOUBEACON palette, typography hierarchy, borders, radii, shadows, form controls, and orange primary actions.
- Reused the same inline elephant mark in all page headers so embedded SVG rendering is reliable; cache-busting stylesheet versions were updated for the reviewed pages.
- Added compact desktop rules for the legacy pages, intake, project list, and project workspace; mobile layouts retain readable body text and larger touch targets.
- Concentrated browser verification across all 8 HTML surfaces at desktop and 390px mobile sizes: no horizontal overflow or console errors. One empty-image slot belongs to the hidden legacy image dialog and is not a page asset failure.

## Property photo location and investigation naming (2026-08-28)

- 已按确认的 A 方案接入 `property-analysis.html`：独立“拍摄房屋照片”入口使用原生相机能力；只有用户点击“获取照片位置并生成地址”后才请求浏览器定位权限。
- 已新增 FastAPI `PUT /api/intake/sessions/{session_id}/location`：保存数值型经纬度、精度、带时区时间和同意版本；通过标准库 GSI reverse-geocoder adapter 生成街区级候选地址。地址解析失败时仍保留坐标并提供手工地址回退，不暴露第三方异常。
- 已新增调查记录名称字段与 owner-scoped 重复处理：确认地址默认作为 `project_name`；同一用户重复地址返回 `duplicate_address`，页面聚焦名称输入并允许手工修改后重试；客户端不能提交 `owner_user_id`。
- 已新增 forward migration `supabase/migrations/20260828000100_property_photo_location.sql`、数据字典和配置说明；开发提交阶段未应用 production、未部署、未使用真实照片或真实定位数据。
- 本轮最终验证：Python 全量 `60 passed`；Playwright 全量 `12 passed`；所有 `web/js/*.js` 通过 `node --check`；`compileall` 和 `git diff --check` 已通过。桌面 `1440x900` 与移动 `390x844` 渲染 QA 无横向溢出、控制台无 error/warning；截图保存在 `/private/tmp/zoubeacon-photo-location-desktop.png` 和 `/private/tmp/zoubeacon-photo-location-mobile.png`。

## Staging migration verification (2026-08-28)

- 用户明确确认后，已将 `20260827000500_legacy_private_data_rls.sql` 和 `20260828000100_property_photo_location.sql` 应用到 linked `zoubeacon-staging`；Supabase migration history 已记录 `20260825000400`、`20260827000500`、`20260828000100`，production 未修改。
- 远端只读核验通过：照片定位字段、数值范围约束、owner-scoped 地址/名称索引存在；`tests/sql/test_property_intake_schema.sql` 与 `tests/security/test_rls_private_projects.sql` 均通过；`property-intake` bucket 仍为 private、20 MiB、仅 PDF/JPEG/PNG。
- 未完成项：本机没有 Docker/PostgreSQL server，schema-only dump 未生成；Render staging health GET 无响应，当前本地未提交的 FastAPI 代码尚未部署，真实账号/真实照片/真实定位闭环仍未验证。

## Three-role frontend surface pass (2026-08-28)

- 根据产品角色确认，将前端入口明确分为 C 端“小象避坑 / ZOUBEACON”、B 端“小象数据 / ZOUSEEKING”和工作人员“管理员后台”；角色矩阵记录在 `docs/superpowers/ui-review/2026-08-28-role-surface-review.md`。
- B 端 `web/index.html` 现在作为“小象数据”工作台入口，保留原有 `app.js` 查询/账户 ID，同时增加查询、统计、服务任务协作入口和明确标注的 `synthetic_fixture` 服务任务演示；B 端桌面账户区采用紧凑布局。
- B 端 `web/analysis.html`、`web/mypage.html`、`web/profile.html` 已统一品牌与功能导航；C 端项目页的账户资料通过 `profile.html?role=consumer` 切换为“小象避坑”呈现，未复制账户业务逻辑。
- 新增管理员控制台 `web/admin.html`、`web/admin.css`、`web/js/admin.js`，覆盖采集任务、质量审核、发布前检查、C 端服务派单、状态筛选、模块切换、移动菜单和本地演示状态操作。
- `web/ui-review.html` 已改为三角色评审入口，区分 C 端引导密度、B 端紧凑协作和管理员表格优先；本轮没有新增或修改数据库 migration、RLS、认证策略或真实业务数据。
- 已执行新 JS `node --check`、既有 `web/app.js node --check`、`git diff --check`；Playwright fallback 已检查新旧页面桌面与 `390x844` 移动布局、B 端任务筛选/接单、管理员模块/复核/移动菜单，未发现横向溢出或 page error。
- 待产品确认：B 端服务任务到底是个人承接、团队派单还是仅查看转交；三角色导航和当前紧凑程度确认后，再进入数据结构与权限契约评审。

## UI wording and layout follow-up (2026-08-28)

- C 端提交资料已增加“物件类型 / 房型”必填选择，包含公寓、塔楼、一户建和其他物件；未选择时不会进入资料整理，确认页与演示预览会保留所选类型。
- 由于当前 `CreateSessionRequest` 尚未包含物件类型且禁止未知字段，本轮只做前端流程门槛和本地会话演示，不伪造服务端持久化；正式 `asset_type` 字段留到数据契约评审后通过 forward migration 接入。
- 面向用户的日本房产相关文案统一改为“物件”；已有生成内容在 Web 展示层做兼容替换，未手工改写由脚本维护的 content library。
- B 端桌面布局改为左侧账户栏 + 右侧工作区，移动端恢复单列；“最近发布的数据”改为“最近更新内容”，并标明正式内容应由后台采集和质量审核后推送，当前仍使用本地预览库。
- 已用 Playwright 验证 B 端 `统计分析`、`数据与服务工作台`、`账户资料` 路由可打开，C 端未选物件类型会停留在提交步骤；数据库、认证策略和测试数据本轮未改动。

## B 端主页、会员管理与多语言跟进 (2026-08-28)

- 按确认方案精简 `web/index.html`：入口只保留登录/注册、登录下方的紧凑“最近更新内容”和进入查询的主按钮；移除主页独立查询面板、概览 KPI 与服务任务列表。
- 新增 `web/data-query.html` 作为独立数据查询界面；详情打开/返回、查询筛选、历史记录和现有 `app.js` 数据流保持可用。最近更新行改为 `¥ + 记录名称 + 月份/地区`，不再加载图片。
- 管理员 `web/admin.html` 增加会员管理页签、脱敏搜索、状态筛选、查看详情和暂停/恢复演示；数据只存在前端本地 `synthetic_fixture`，没有写入真实会员、认证或数据库。
- 新增共享 `web/js/i18n.js`，为数据查询、统计分析、数据与服务工作台以及 B 端账户壳接入中文、英文、日文切换；数据记录本身仍保留来源语言和日本地区原称，避免把数据内容误当作界面翻译。
- 修复 B 端登录态账户栏在 390px 下的横向溢出：紧凑账户栏不重复显示顶部功能导航，仅保留退出操作；补齐 B 端/管理员页面 favicon，避免浏览器自动请求产生 404。
- 新增 `tests/web/business-home-members-locale.spec.js`；聚焦 Playwright 用例 `4 passed`，覆盖主页精简、独立查询详情、三语切换和本地会员状态操作。额外浏览器验收覆盖 `1440x900` 与 `390x844`，5 个 B/管理员路由均无横向溢出、无 page error 或 console error。
- 当前仍是界面与演示层改动：没有新增会员数据表、RLS、认证权限、配额校验或真实后台 CRUD；后台正式会员管理仍需在数据结构和权限契约评审后接入。
- 当前会话未提供可用的 Browser 控制工具，因此使用本地 Chrome + Playwright fallback 完成页面验收；未使用真实会员或真实市场数据。

## B 端完整业务页面补齐 (2026-08-29)

- 按确认范围新增 6 个小象数据页面：`web/organization.html`（机构与成员）、`web/billing.html`（套餐与账单）、`web/usage.html`（用量与额度）、`web/subscriptions.html`（统计订阅）、`web/exports.html`（数据导出）和 `web/service-tasks.html`（C 端服务任务池）。
- 新增共享 `web/business-pages.css` 与 `web/js/business-pages.js`；桌面端使用左侧机构/状态栏加右侧主工作区，手机端恢复单列，成员行在手机端可直接查看角色、状态和操作。
- 六个页面均明确标注 `synthetic_fixture` / 本地演示；邀请、套餐选择、自动续费、订阅、导出、任务申请/撤回只更新页面内存，不调用 API，不写入会员、额度、支付或任务数据。
- `web/js/i18n.js` 已补齐上述页面的中文、英文、日文标题、导航、核心操作、状态、用量单位和任务信息；`web/ui-review.html` 已加入 6 个页面的 B 端评审入口。
- 新增的 Playwright 断言覆盖 6 个路由、桌面/`390x844` 移动端无横向溢出、控制台/page error、三语切换、机构邀请、账单币种/自动续费、用量筛选、订阅、导出和任务申请/撤回。
- 定向验收：`npx playwright test tests/web/business-home-members-locale.spec.js --project=chromium` → `8 passed`；全量 Web 回归：`npm run test:web` → `20 passed`。
- 静态验收：所有 `web/js/*.js` 通过 `node --check`，`git diff --check` 通过；本轮用本地 Chrome + Playwright fallback 检查 `1440x900` 和 `390x844` 截图，无 page error、console error 或横向溢出。
- 仍未完成：真实机构/成员/订阅/支付/额度/导出/任务的数据结构、权限和服务端计量；本轮前端已从 `056a263` 部署到 Render staging，但本地未提交的后端/SQL 变更尚未部署或应用到数据库。本轮前端改动已整理为可独立发布 commit，后端与数据变更仍需按架构门槛单独验证。

## Product acceptance gate (2026-08-29)

- 产品方已确认前端界面和输出报告内容：C 端免费预览/完整版报告、B 端查询与业务页面、管理员演示入口，以及中/英/日界面切换均按 staging 版本验收。
- Render staging 前端使用 release commit `056a263`；示例报告脚本为 `scripts/create_report_sample_pdf.py`，本地生成的 PDF 仅用于评审，所有数值继续标记为 `synthetic_fixture`。
- 本次验收不等于真实会员、支付、额度、任务、数据库或报告生成服务验收；后端/SQL commit `57762f5` 仍只在本地，未部署或应用新的业务 migration。
- 下一道门槛：完成 Supabase migration baseline reconciliation、schema/RLS/备份恢复验证，再冻结已验收字段并进入后端 staging。

## Staging connection and Render health verification (2026-08-30)

- 已确认 Render `zouseeking-api-staging` 的 `DATABASE_URL` 已配置，并指向 Supabase `zoubeacon-staging`（project ref `fnogxuytbabxmqousifh`）的 pooler 连接；未重置密码、未修改生产项目。
- 只读 PostgreSQL 核验通过：TLS 连接成功，服务器 PostgreSQL 17.6；public schema 有 22 张基础表，22 张均启用 RLS，存在 20 条 public policy。
- Supabase migration history 核验通过：`20260825000400_property_intake`、`20260827000500_legacy_private_data_rls`、`20260828000100_property_photo_location`。
- Render staging 健康端点返回 HTTP 200：`status=ready`、`database=ok`、`version=staging`；本次只读检查未执行数据库写入或迁移。
- 本地未持久化数据库密码或 `STAGING_DATABASE_URL`；完整 migration baseline reconciliation、RLS 身份矩阵和备份恢复演练仍按既有门槛待完成。

## Release candidate execution (2026-08-31—2026-09-01)

- 隔离分支 `codex/release-candidate` 已完成 C01/C02/C03 的受控归档与整合回归：C01/C02 提交 `fe4b9dd`、`110358e`，C03 提交 `41cafc7`；整合后 Python `95 passed`、Edge `2 passed`、compileall、JS syntax 和机器 JSON 解析均通过。
- C04 本地恢复演练与 C05 本地 baseline/RLS 预检保持通过；staging dry-run 只读显示 8 条早期 migration 与 `20260829000100` 待处理，未执行 push、repair、reset 或线上写入。
- C06 只读 provenance 审计发现历史内容库 70/70 阻断、两份 CSV 均缺正式 provenance 字段；未补写 rights、未联网、未发布。
- C07–C13 离线候选已完成专项回归；C11 静态单文件预算为 `FIX`，C12 在线 advisory/CI 与 C13 live smoke 仍未闭合。C14 Go/No-Go 模板保持 `BLOCK / NOT AUTHORIZED`，费用上限 `JPY 0`、保留期 7 天、清理窗口 `2026-09-01 02:00–03:00 JST`。
- C12/C13 首次候选证据记录：Python `95 passed`、Edge `2 passed`、compileall/JS syntax/secret scan/diff 为 `PASS`；浏览器本地 `22` 项为 `18 passed / 4 failed`，失败原因是候选缺失 `data/content_library.json`；npm advisory 为 DNS `FAIL`、`pip-audit` 为 `BLOCKED`、policy 为 `FAIL`。该历史 manifest `offline_gate_passed=false`、`release_ready=false`。
- 后续已补齐候选 `data/content_library.json`，集成 offline release gate/policy/rollback 文件并通过新增 17 项聚焦测试；最新离线回归为 Python `112 passed`、browser `22 passed`、policy `PASS`，synthetic smoke `c13-offline-20260901` `PASS`。npm advisory 仍因 DNS `FAIL`、`pip-audit` 缺失 `BLOCKED`，SQL/RLS 与全部线上检查仍 `NOT_EXECUTED`。
- C14 Go/No-Go 复核仍为 `BLOCK / NOT AUTHORIZED`：角色、7 天保留、`JPY 0` 费用上限和清理窗口已记录；migration live reconciliation、provider backup/isolated clone、C06 provenance、C11 单文件预算、SQL/RLS 与所有线上检查仍未闭合。
- 生产上线仍被 migration reconciliation、provider backup/clone、provenance 授权、CI/供应链和精确目标审批阻断；主工作区既有未提交代码与生成资产未被本轮覆盖或清理。

## Last updated

2026-09-01
