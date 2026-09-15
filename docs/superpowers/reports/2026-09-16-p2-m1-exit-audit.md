# P2 M1 出口核对与收尾单元（2026-09-16 晨班 · 管家）

> 目的：P1 已于 09-07 工程闭环，本班把「下一阶段」由口号变成**可派工、可验收**的清单。
> 红线：本班只读 + 文档；零 DB 写/对象变更、零部署、零凭据操作、零删除、未改 migration 与冻结字段。

## 0. 班前状态实测（全部本地/线上实跑）

| 项 | 结果 |
|---|---|
| 工作树 | 干净；`main == origin/main == 77fd2cc`（09-15 夜班文档提交） |
| Release Gate | `77fd2cc` run **success**（七个 job）；红链自 09-12 起已清零 |
| 线上 | `api.zoubeacon.com/health/ready` → `{"status":"ready","database":"ok","version":"lightsail-2026-09"}`；`zoubeacon.app` 200；`platform.zoubeacon.com/admin.html` 200（36,284 B） |
| 资源版本 | 本地 `web/*.html` 全为 `?v=20260914-r35`（与 09-15 线上记录一致，无部署漂移） |
| 内容库一致性 | `data/content_library.json` 与 `web/content-library.json` SHA-256 同为 `86be5284…`（AGENTS 一致性要求成立） |
| 离线校验 | `compileall`（backend/scripts/src）通过；`node --check`（`web/app.js` + `web/js/*.js`）通过 |
| 测试 | `backend/.venv/bin/python -m pytest tests/unit tests/architecture -q` → **380 passed / 85 skipped**（0 failed） |
| 并发写 | 仓库内无 `codex exec` 进程、近 3 小时零文件写入 → 单写者无冲突 |

## 1. M1（09-15→09-22：P2-0/P2-1 done、staging 单路径报告）逐条核对

| # | 出口项 | 状态 | 证据 |
|---|---|---|---|
| 1 | P2-0 报告链考古 + 目标架构设计 | ✅ | `docs/superpowers/plans/2026-09-07-p20-report-archaeology.md`（含 D6a 决策、四条链盘点、目标架构） |
| 2 | P2-1 前端删 Edge 通道 | ✅ | `web/**` 内 `functions.invoke` / `/functions/v1` / `jphouse-run` **零命中**；`76b4ffc` 已在 main（并带源码级 guard 测试） |
| 3 | Edge 函数部署态退役 | ✅（staging 事实） | 管理 API 实测 staging 项目 `fnogxuytbabxmqousifh`：**`functions = []`**（未部署任何 Edge 函数）→ 线上事实上已是单通道 |
| 4 | P2-3b 数值化报告引擎接线 | ✅ | `backend/app/main.py:415-435`：`match_snapshot(load_snapshots())` → `build_sale_report(...)`，落 `data_class=scraped_aggregate`、`source_id`（运行时解析国交省来源）、`transformation_version=market-engine-v1`；09-15 live 验证 `full_report` |
| 5 | P2-1「legacy 分支删」 | ❌ **未完成** | `docs/architecture/authoritative-boundaries.json` 的 `frozen_legacy_components` 四条**全部仍在**（详见 §2） |
| 6 | P2-0 staging 迁移门禁（`20260904000100` 应用状态） | ⏳ 未核 | 需 DB 读/环境操作，超本班红线；登记为待办 |

**结论**：M1 主线（P2-0 设计、前端 Edge 退役、数值化引擎接线）已达成；M1 仍缺两个**有界工程单元**——见 §3 单元 A / 单元 B。二者都是「收敛」而非新功能，风险低、验收明确。

## 2. 未退役的冻结遗留件（逐条实测）

`frozen_legacy_components` 四条现状：

| 遗留件 | 实测现状 | 线上影响 |
|---|---|---|
| `web/app.js:direct_private_supabase_reads_legacy_view` | `supabaseUserFetch` 定义在 `app.js:644`，调用点 `750 / 768 / 867 / 1220`（直读 `user_profiles`、`property_reports`）；`supabaseReportToRecord` 定义 `581`、调用点 `1243` 仍在 | `app.js` 被 `index/mypage/profile/data-query/analysis` 五页加载；登录态非后端会话时走 PostgREST 直读（受 RLS 保护，非越权，但违反 ADR-0001 单通道） |
| `supabase/functions/jphouse-run:regional_report_edge_executor` | 代码保留（break-glass 语义） | staging **未部署**（§1.3 实测），无运行时风险；仅需决定删除或长期冻结 |
| `scripts/run_jphouse_worker.py:regional_report_rest_worker` | 代码保留；`deploy/docker-compose.prod.yml` **未部署该 worker** | 同上 |
| `backend/app/main.py:in_process_regional_report_executor` | **仍在生产路径上执行**：`main.py:631`（`/api/query` 缓存未命中分支）与 `main.py:732`（job run 入口）均 `background_tasks.add_task(run_generation_job, ...)`；`deploy/docker-compose.prod.yml:37` 的 `worker` 只跑 `scripts/collection_worker.py`，**没有任何 durable worker 消费 `generation_jobs`**（除冻结的 `run_jphouse_worker.py`） | ⚠️ 与 D4「报告生成 = FastAPI durable worker」及 ADR-0001 `background_execution=postgres_job_outbox_single_worker` 冲突：api 容器重启/重建会中断在跑任务（用户侧由 09-15 的终结态 requeue 自愈兜底，但任务本身不durable） |

## 3. 建议下阶段单元（待 Gordon 决策；推荐项置顶）

**D1（推荐）单元 A：报告生成入 durable worker。** 新增/改造 worker 消费 `generation_jobs`（原子认领 `pending`→`running`、有界重试、失败分类），api 侧去掉两处 `BackgroundTasks` 报告路径，保留 09-15 的 requeue 自愈与缓存语义；同步 `authoritative-boundaries.json` 冻结清单与架构 guard 测试。
验收：durable 路径下 live 一轮 query → job `completed` → `full_report`；`main.py` 零 `add_task(run_generation_job…)`；`pytest tests/unit tests/architecture` 与 `npm run test:web` 全绿；杀进程重启后任务可被另一实例续跑（幂等回放）。

**D2 单元 B：`web/app.js` legacy 直读退役。** `mypage/profile/data-query/analysis` 四页的私有数据改走 `/api/my/*` 与 `/api/reports/*`；删 `supabaseUserFetch` 私有读取分支与 `supabaseReportToRecord`；从 `frozen_legacy_components` 移除该项并收紧 guard 测试。
验收：`web/app.js` 内 `rest/v1` 私有表零命中（仅留 `query_field_options` 公开读）；四页在匿名/登录/接口失败三态均诚实降级；Playwright 现有用例零放宽。

**D3 未部署的冻结件二选一（产品/架构决定）**：① 直接删除（Edge 函数 + `run_jphouse_worker.py`，最干净）② 长期冻结并写明「break-glass 仅限事故」的启用条件与负责人。

**D4 环境与合规项（需你操作或拍板，本班未动）**：
1. SES 生产权限：IAM 用户 `zoubeacon-ses-ops` 加 `support:CreateCase/DescribeCases/AddCommunicationToCase`（推荐，之后由 Hermes 开案跟进）或你本人控制台追加回复。
2. `N3` 4 行历史僵尸报告清理（DB 写，需批准；不批也会在对应账号下次查询时自愈）。
3. SES 获批后立刻把 `mailer_autoconfirm` 改 `false` 并跑一轮注册确认链路。
4. `C4` 迁移台账卫生（2026091x 起未录入 `supabase_migrations.schema_migrations`）——需先给「补齐 or 不补」的口径。
5. P2-0 门禁：`20260904000100` 在 staging 的应用状态核验（需 DB 读授权）。

**D5 本班次任务书调整建议**：`早班·P1自主推进`（job `ab373f6bd99d`）已无 P1 单元，内容与夜班只读核查高度重叠。建议改为「P2 推进班（派工+验收）」或停用，避免每日重复投递。

## 4. 本班红线

零代码改动（仅文档）、零 DB/线上写、零部署、未触凭据与冻结字段、无删除操作、未改 migration。
