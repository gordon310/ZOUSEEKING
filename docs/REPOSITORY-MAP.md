# ZOUSEEKING Monorepo · 仓库地图与生成物边界（P0.2 交付）

日期：2026-09-05 · 权威分支：`main`（origin/main，远端 = Render staging 构建源）
配套：文件级全量差异清单见 `2026-09-04-divergence-file-manifest.txt`（历史仲裁用）。

## 1. 顶层结构

| 路径 | 性质 | 说明 |
|---|---|---|
| `backend/` | 源码 | FastAPI（asyncpg），唯一业务 API 边界（ADR-0001）。`app/billing|usage|intake|renovation|routes|services`；V1 DB 适配器 `billing/store.py`、`usage/db_ledger.py` |
| `web/` | 源码 | 静态前端三角色：小象避坑(C)/小象数据(B)/管理员后台；`js/i18n.js` 三语；`property-analysis.html` intake 流程 |
| `supabase/migrations/` | 源码 | **唯一 migration history**（19 个文件：24000xx→20260902xx 链 + 0904 wip + V1×5）；`functions/` Edge 兼容路径（退役中） |
| `supabase/.temp/` | 忽略 | 本地 CLI link 状态，不入库 |
| `src/` | 源码 | `jp_property_publisher`：授权数据标准化 CLI（data_class 强制） |
| `scripts/` | 源码 | 采集/生成/CI 门禁/worker：`build_jphouse_23ku/osaka/yokohama`（配 configs）、`generate_xhs_package.py`、`ci/*` release 门禁 |
| `configs/` | 源码 | 数据管道区域/来源配置（jphouse_23ku/osaka_wards/yokohama_wards 等 70+）+ `data_quality_policy.json` |
| `docs/` | 源码 | 架构 ADR、legal、operations、release 门禁证据、superpowers 规划/规格 |
| `data/` | 混合 | `input/` 人工源数据（入库）、`collected|output/` 生成物（忽略）、`content_library.json` canonical（入库） |
| `tests/` | 源码 | `unit/ api/ smoke/ sql/(psql DO 断言) web/(Playwright) security/ architecture/` |
| `design-system/` | 忽略(部分) | zouseeking-frontend 本地演示 |
| 根级旧文件 | 清理候选 | origin 历史遗留根级静态副本（index.html/app.js/library/…13 项，见 C 类遗留） |

## 2. 生成物边界（git 忽略规则，勿手工入库）

- 忽略：`data/collected/`、`data/output/`、`web/library/`、`web/content-library.json`、`output/`、`test-results/`、`tmp/`、`*.venv`、`.env*`、`supabase/.temp/`、`dist/`、截图/PDF 样例产物。
- 生成物的**唯一写入入口**是 owning 脚本（`generate_xhs_package.py::sync_web_library` 等）；同步后校验 `data/content_library.json` 与 `web/content-library.json` 哈希一致。
- 任何 migration/字段改动必须同步 `docs/data-dictionary.md`（AGENTS 规则）。

## 3. 三产品线边界（同库分域）

| 线 | 前端 | 后端/域 | 数据表（V1 域, 未应用） |
|---|---|---|---|
| 小象避坑 C 端 | property-analysis/project*/profile?role=consumer | intake + renovation + billing(c_plus/单份) | intake 链 + V1 subscriptions/billing |
| 后台管理 | admin.html + admin.js | worker/采集/审核/会员/财务 | 20260905 V1 org/usage/tasks/finance + 现有 legacy 私有表 |
| 小象数据 B 端 | index/data-query/business-pages | 统计/订阅/导出 | 机构共享额度走 V1 org/usage |

## 4. 部署与数据真相

- Render：`zouseeking-api-staging` 从 GitHub main 构建（secret 只存 Render，不落仓）；健康端点 `/health/live|ready` 当前 200。
- Supabase staging：`zoubeacon-staging`（fnogxu…），migration history 13 条与 main 一致（2026-09-05 reconcile）；生产项目**未配置/未触碰**（vbwyn…=废弃测试实例）。
- 未应用（有意 pending）：`20260904000100`（B1/P2）、`20260905xxxx` V1×5（baseline 后 gate）。
- 备份/回退点：`backup/workspace-20260904-{main,intake,originmain}`、`codex/replay-carryover`（09-04 分叉仲裁产物，保留）。
