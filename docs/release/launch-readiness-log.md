# 上线准备·完成记录(重点事项台账)

> **规则(用户 2026-09-23 定)**:同一事实**只验证一次并在此登记**;此后**不再重复验证**。
> 只有**相关代码/数据/配置发生变更**时,才对相应条目重新验证。CI(`release-gate.yml`)是唯一权威门。
> 需要重验时,在"重验条件"列注明触发条件,并更新日期与证据。

| 日期 | 事项 | 状态 | 一次验证的证据 | 重验条件 |
|---|---|---|---|---|
| 09-20 | 数据库定稿:单一迁移史 | ✅ | `scripts/check_schema_ownership.py` pass;仓库 50 条迁移 == 线上已登记 50 条;运行时引用 `backend/sql/*` 会被审计判 fail(注入反例实测) | 新增迁移时 |
| 09-20 | 报告生成 outbox + 常驻 worker | ✅ | 生产 `/api/query` → outbox `completed` → 任务 100%;**compose 服务 `report-worker`**;入口自建连接池 + 15 分钟租约回收 | worker/compose 变更时 |
| 09-20 | 成员读路径走 RLS 视图 | ✅ | 生产四身份:`member_queries` owner 200 / 匿名 401 / 跨用户 0 行 / 写 400;三视图均 `security_invoker=true` | RLS/视图变更时 |
| 09-20 | 销号(账号可删除) | ✅ | 生产 `DELETE /auth/v1/admin/users/{id}` → 200;`usage_events` 匿名化保留(actor=null)、queries 清空 | 注销链路变更时 |
| 09-21 | provenance 契约强制 | ✅ | `REQUIRED_STATISTIC_FIELDS` 12 项;缺失即报错(删字段反例);官方 MLIT/e-Stat 标注 `verified_observation`;口径取自 DB(改库值→接口变) | 契约/接口变更时 |
| 09-22 | 统计配额强制(旁路已堵) | ✅ | 单期与趋势共用 `stats_query`;生产实测两路径均 200 且 `usage_events` 增 2 条(scope=`org:<id>`) | 配额/统计路径变更时 |
| 09-22 | 区域统计与多月趋势 | ✅ | 生产 200;趋势 5 期跨年有序(`2025Q1→2026Q1`);逐期 provenance 含真实时间戳 | 统计逻辑变更时 |
| 09-22 | 邮件域名加固 | ✅ | 根域与发信子域 DMARC 均 `p=reject`(权威 NS + 1.1.1.1 + 8.8.8.8 一致);根域 `spf -all` | DNS 变更时 |
| 09-22 | 生产可观测 | ✅ | 机侧 systemd timer 15 分钟只读自查,生产实跑 `exit_status=0`,摘要 `failed=0 zombie_running=0 pending_due=0`;Hermes 侧每日 09:30 QQ 巡检 | 检查脚本/服务变更时 |
| 09-22 | 恢复演练 | ✅ | `scripts/restore_drill.py` 真跑:`SOURCE_READ_ONLY` → 导出 298,695 字节 → 隔离恢复 → 断言 7 表 + 50 迁移版本 → 清理 | 迁移/备份策略变更时 |
| 09-22 | CI 门禁 | ✅ | `release-gate.yml` 七道门;本周期每个提交均 success(最新 `fd13974`) | 工作流变更时 |
| 09-22 | 采集 worker 生命周期 | ✅ | `--loop 0` 常驻;独立实测 SIGTERM 0.044s 内 exit 0;**生产定案(09-23 读取):同一生命周期自 09-22 15:21:22 起持续运行、`restarts=0`、已完成 3384 轮** —— 远超旧设计 60 轮/10 分钟上限 | worker 命令变更时 |
| 09-22 | 测试残留清理 | ✅ | 删除 19 无主 queries(+15 jobs/5 reports/6 outbox,级联);用户数据 6 条完好;备份留档 `~/zouseeking-cron-tasks/orphan-residue-backup-2026-09-22.json` | 不再重验 |
| 09-23 | Stripe 生产支付 | ✅ | `STRIPE_SECRET_KEY=sk_live`(计数 1,不回显);`payment_orders` 有 live 单 `cs_live_…` CNY 5.00 `paid`(09-13);webhook `checkout.session.completed` `processed` | 支付链路/价格变更时;10-07 前做一次对账(已排 09-26 提醒) |
| 09-23 | 邀请制准入 + 试运行标识 | ✅ | 迁移 + 原子校验;真库并发 `max_uses=1` 仅成功一次;无效/停用/过期/耗尽码稳定 4xx;四语言齐备(繁中已按仓库约定改为「數據」);751/1 | 邀请链路变更时 |
| 09-23 | 限流一致性 + on-call | ✅ | PostgreSQL 共享原子计数(单语句 CTE);真库四独立连接并发 3 允许/1 拒绝/计数 3;存储不可用 **fail-closed 503**;`docs/operations/oncall.md` | 限流实现/告警路径变更时 |
| 09-23 | 内容库 provenance | ✅ | **实测两份各 6 条**(更正审计所称 70 条);全部显式 `synthetic_fixture`,非 synthetic 违规 0;两副本 SHA-256 一致 | 内容库变更时 |
| 09-23 | 容量基线(受邀范围) | ✅ | 机器可读首月基线(10–20 人、限区域);**预算数值待用户提供,未虚构** | 范围/预算变更时 |
| 09-23 | 静态资源瘦身 | ✅ | 总量 **2,366,624 → 1,240,939 B**;最大文件 **945,771 → 246,943 B**;logo 改 SVG,PWA 180/192/512+maskable 保留;可读源在 `web-source/`,`npm run build:web-assets` 可复现;版本统一 `20260923-r63`;探针 `verdict: SHIP`;761/1 | 静态资源/构建脚本变更时 |
| 09-23 | 正式上线口径 | ✅ | 用户拍板:Web/PWA 先行,硬出口 **2026-10-07**;商店/备案为并行轨道 | 用户改口径时 |
| 09-24 | 生产迁移台账 | 🟡 | 管理 API 只读实测:生产已登记 **50** / 仓库 **54**;待应用 `20260921000100`(provenance 回填)、`20260923000100/000200/000300`(邀请门/错误态/共享限流) | 应用 4 条后重验;此后新增迁移时 |
| 09-24 | 生产注册门(邀请制准入在生产的实际状态) | 🔴 **未生效** | 管理 API:`disable_signup=false`(公共注册仍开放);`invite_codes`/`invite_redemptions` **仅定义于未应用的两条迁移** → 生产无邀请码表。**09-23 行的 ✅ 证据取自真库,非生产**;生产侧不成立 | 迁移应用 + 邀请端点确认 + 切 `disable_signup=true` 后重验(顺序不可颠倒) |
| 09-24 | 生产后台 API 边界 | 🔴 **后台被关闭** | 未鉴权 `/api/admin/*` 均 **401**(鉴权边界生效);SSH 只读实测生产 `deploy/.env` **无 `ADMIN_ENABLED` 键**(`grep -c` 返回 0)→ 代码默认 `false`(`backend/app/admin/service.py:1236`)→ 鉴权通过后一律 **503「admin 未配置」** = **后台管理平台在生产不可用**,与 10-07「C 端 + 后台同时上线」直接冲突 | 部署批次写入 `ADMIN_ENABLED=true` 并重启 api 后用已登录管理员会话重验 |
| 09-24 | 生产环境键存在性(只读) | 🟡 | SSH 只读:5 容器 Up(api 42h / worker 27h / report-worker 27h / scheduler 8d / nginx 6d);`STRIPE_SECRET_KEY`(`sk_live` 前缀 ✓)、`SUPABASE_SERVICE_ROLE_KEY`、`ABUSE_HASH_SALT`、`ENVIRONMENT` 均存在;`ADMIN_ENABLED`、`QUERY_RATE_LIMIT_PER_HOUR`、`INVITE_REGISTER_RATE_LIMIT_PER_HOUR` **三键缺失** → 分别落代码默认 `false` / `20` / `5`(限流默认足够;后台默认关闭见上行) | 部署批次写入或变更 env 后重验 |
| 09-24 | C09 可观测与出站超时契约 | ✅ | 新增 `backend/app/observability.py`(请求关联 ID + 逐行 JSON + 脱敏,`X-Request-Id` 回写)、`backend/app/timeouts.py`(出站超时/重试/取消集中化,**默认值不变**)、`docs/production-reliability.md`;**独立实跑**(非自报):中间件 200/500 两路径、非法 request id 替换为 32-hex、email/token/JWT/异常原文**零泄漏**、每请求单行 JSON、第三方 INFO 噪声骨架行消除;`pytest tests/unit tests/architecture` **471 passed / 91 skipped**;`compileall`、`git diff --check` 净 | observability/timeouts/worker_logging 实现变更时 |
| 09-24 | 前端部署漂移 | 🔴 | 线上 `?v=20260917-r61` vs 仓库 `deploy/frontend-version.txt=20260923-r63` → 生产前端落后 **16 个提交**(invite 注册前端、四语试运行标识、静态瘦身 r63、后台页签修复未上线) | 部署批次后重验版本号 |
| 09-24 | 报告任务队列合同(C07) | ✅ | `docs/architecture/report-job-queue-contract.md`(五态机 + 原子认领/租约 + 三个幂等边界 + 取消真实行为 + 证据索引);5 条静态守护钉死唯一执行器(`report_worker.py:241`),3 条真库用例(租约重放不重复 / 重入队幂等 / completed 不再认领);守护经**变异测试**验证;unit+arch **476**、真库 **8**、全量 **673** | 队列实现 / worker / compose 变更时 |
| 09-24 | 生产配置合同(C08) | ✅ | `docs/operations/production-configuration-contract.md`(Lightsail 拓扑 + staging/prod 边界 + jpsskill 受控例外 + 全量 env 契约 + known gaps);`deploy/.env.example` 补 **25 键**;6 条静态守护(不依赖 PyYAML)经**变异测试**验证;`secret_scan` / `check_release_policy` 均 PASS | 配置键 / compose / render.yaml 变更时 |
| 09-24 | C13 staging smoke 载体 | 🟡 载体已交付 | 四处交付物落地:`scripts/staging_synthetic_smoke.py`(默认 `--plan` 零网络零 socket;`--execute` 双开关 + `SMOKE_*` 三环境变量;生产 host 硬拒;10 条固定用例;`finally` 清理 + 读回断言残留 0;证据递归脱敏)、`docs/staging-synthetic-smoke.md`、`docs/release/phase-one-staging-evidence.json`(`NOT_EXECUTED` 骨架)、`tests/smoke/test_staging_synthetic_smoke.py`。独立验收:smoke **15 passed**、unit+arch **482/91**、全量 **694/113** | **真实 staging 运行 + 浏览器审计尚未执行** → 用户一次性写入授权 + `SMOKE_*` 凭据后重验 |
| 09-24 | canonical 证据写入守卫 | ✅ | `--self-check` 裸跑不再写任何文件;指向 `docs/release/phase-one-staging-evidence.json` 被硬拒(exit 2),实测该文件 SHA-256 前后未变 → 防止「离线假通过」被当成 staging 证据 | 守卫或证据路径变更时 |

## 待闭合(未完成项,不属本台账)
- ~~G2-ENG:邀请制准入 + 试运行标识(工程缺口)~~ → **工程侧已闭合(见本表 09-23 行)**;**生产侧未生效(见 09-24 行),待部署批次**
- G3:C01–C14 逐项判定 → **已完成 10-07 口径复核(见 `docs/release/go-no-go-checklist-2026-10-07.md` 文末《2026-09-24 范围对齐复核》)**
- G4:生产迁移/RLS/额度/日志终检 + 回滚预案演练(09-27 ~ 09-30 窗口)
- G5:发布公告 + 首周观察看板
- G6/G8:提审材料 / 退款客服流程(用户口径 + Hermes 起草)
- G7:合规评估与备案(并行轨道)
- **新增(09-24 实测)**:一次部署批次(4 条迁移 + r63 前端 + 注册门切换,需用户批准)
- **新增(09-24 夜班)**:C13 真实 staging 运行 + 浏览器审计(工程载体已交付;需用户一次性 staging 写入授权 + `SMOKE_ANON_KEY` / `SMOKE_OWNER_TOKEN` / `SMOKE_OTHER_TOKEN`)
