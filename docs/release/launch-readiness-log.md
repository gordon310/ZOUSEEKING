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
| 09-24 | 生产部署批次(Web/PWA 上线) | ✅ | `git pull` → `85bc86f`;4 条迁移应用 → 台账 **54/54, pending=0**;`ADMIN_ENABLED=true`(env 备份 `.env.bak-20260924`);api/report-worker/worker/scheduler 重建;验收 `/health/ready` 200、站点 200、前端 `r63`==仓库、admin 未鉴权 401 | 新增迁移 / 部署配置变更 / 前端版本变更时 |
| 09-24 | 生产后台启用(ADMIN_ENABLED) | ✅ | 部署批次写入 `ADMIN_ENABLED=true` 并重建 api;容器内 `printenv` = true;未鉴权 `/api/admin/*` 仍 401(鉴权先行)。登录态 200 待用户会话复验 | env 或后台代码变更时 |
| 09-24 | 生产每日备份定时器 | ✅ | `zouseeking-backup.timer` 安装 + enable;`/etc/zouseeking/backup.env`(600,DATABASE_URL 由 deploy/.env 生成、不回显);试跑 `result=success` / `exec_status=0`;排期**每日 03:10 JST**;产物 15.7 MB + manifest(sha256) | unit / 脚本 / 保留策略变更时 |
| 09-24 | 生产备份服务缺失(更正) | ⚠️ 已修 | 实测主机**原无** `zouseeking-backup.service/.timer`、无 `/var/backups/zouseeking`、无 `/etc/zouseeking/backup.env` → 文档「每日 03:10 备份 / 机侧巡检」在主机上不成立;已安装备份(见上行),`observability-check.timer` 仍未装 | 不再重验 |
| 09-24 | 前端部署漂移 | ✅ 已消除 | 线上 `?v=` 由 `20260917-r61` → **`20260923-r63`** == 仓库 `deploy/frontend-version.txt` | 前端版本变更时 |

| 09-25 | 备份异地化(Cloudflare R2) | ✅ | 桶 `zouseeking-backup`(私有)+ S3 凭据仅限该桶;**本机实测** PUT/HEAD/GET/LIST/DELETE + sha256 往返一致;**生产实测**:aws-cli 2.27.1 容器 + `--endpoint-url` 上传 dump(15,776,182 B)+ manifest → 从 R2 下载回算 sha256 与本地/manifest **三方一致**(`0f57f954…`);持久化于 `/etc/zouseeking/backup.env`(600,含 `.bak-20260925`);手工触发 `zouseeking-backup.service` → **自动上传 R2 成功**(22:09:33Z) | 桶/凭据/端点/保留策略变更时 |
| 09-25 | 备份新鲜度观测(S3 路径) | ✅ | `observability-check.timer` **一直在跑但连续失败**(约 3 小时、每 15 分钟一次 `OBSERVABILITY_ALERT backup_artifact_missing:local:/var/backups/zouseeking`,根因=回落到不存在的本地默认路径);把 6 个 `BACKUP_S3_*` 写入 `/etc/zouseeking/observability.env` 后转 **`backup_age_hours=0 threshold_hours=36` + `failed=0` + `OBSERVABILITY_OK`** | 观测脚本/env/阈值变更时 |
| 09-25 | 更正:observability-check.timer 安装状态 | ⚠️ 已修 | 09-24 夜班记录「`observability-check.timer` 仍未安装」**为误判** —— 实测该 timer 自更早已在运行(每 15 分钟),真实问题是它看不见备份;现已修好并转绿 | 不再重验 |
| 09-25 | **待办**:R2 端保留策略 | 🟡 | 本地保留 14 天,**R2 端目前无保留策略**;实测约 15.8 MB/天 → 约 1.7 年触及 10 GB 免费额度。需加对象生命周期或脚本侧清理 | 加上后重验 |
## 待闭合(未完成项,不属本台账)
| 09-25 | **待办**:R2 端保留策略 | ✅ 已闭合 | `scripts/backup_database.py` 新增 `BACKUP_S3_RETENTION_DAYS`(缺省回落 `BACKUP_RETENTION_DAYS`=14)驱动的 `_prune_remote`:上传成功后按前缀列出对象,**仅删该前缀下且匹配 `zouseeking-*.dump`/`*.manifest.json` 的对象、逐对象显式 Key 删除**(不用通配符);清理失败打印 `BACKUP_S3_PRUNE_FAILED` 但**不改变备份成功与退出码**。新键已登记进 `deploy/.env.example` 与生产配置合同 | 保留策略/脚本变更时 |
| 09-25 | 开放注册(服务端) | ✅ | 邀请码改为**可选**:有码走原路径(零语义变更),无码跳过邀请表但仍强制「限流 → consent → 服务端建号」;`consent_source` 区分两种来源;两侧共用同一建号助手。`test_invite_gate` **13 passed**;`AGENTS.md` 条款改写为开放注册口径 | 注册链路变更时 |
| 09-25 | 开放注册(前端) | ✅ | 邀请码输入框**保留但去 `required`**、label 改「邀请码(选填)」、提交按钮改「注册账号」;4 个 i18n 键值改中性文案(**键数不变**);资源版本 `20260923-r63 → 20260925-r64`(26 个文件)。浏览器套件 **110 passed**,其中 `signup-flow` 拆为「无码成功」+「带码仍转发/消耗」两条 | 注册 UI / i18n / 资源版本变更时 |
| 09-25 | 前端版本源/产物脱钩(CI 红→绿) | ✅ | Release Gate 红于 `web-assets-fresh`(3 个文件 would be updated);根因 = `version-frontend-assets.py` 只改 `web/*.html` 与 `web/js/*.js`、**不改 `web-source/js`** → 升版后重建把旧版本压回产物。修:5 处源引用改 r64 + 脚本递归处理 `web-source/js/**/*.js` + 新增守护测试 `tests/architecture/test_frontend_asset_version_contract.py`(源/产物/version.txt 三方一致)。`check:web-assets` 现零变化 | 版本脚本或资源引用变更时 |
- ~~G2-ENG:邀请制准入 + 试运行标识(工程缺口)~~ → **工程侧已闭合(见本表 09-23 行)**;**生产侧:4 条迁移已应用(09-24 部署批次),邀请表已在生产;仅剩注册门切换**(`disable_signup=true`,需先有邀请码)
| 09-25 | **回滚演练**(生产,代码级) | ✅ | `85bc86f` → `fd13974`(checkout + 重建替换 **22 s**)→ 前滚 `main` `711c73f`(**38 s**);两次替换后 `/health/ready` 200、站点 200、未鉴权 `/api/admin/*` 401、4 容器 Up(nginx 未重启);前端版本随 checkout 由 r63→**r61**→**r64**。全程**零 DB 变更**;落档 `docs/operations/rollback-drill-2026-10.md` | 部署机制 / 迁移策略变更时 |
| 09-25 | D-12 上线(开放注册入生产) | ✅ | 前滚 `main` 后实测:无 `invite_code` + 无效邮箱 → **400 `invite_registration_invalid`**(旧版本此处为 **422** 字段缺失)= 生产证明「邀请码不再必填」;前端资源 **`20260925-r64`**;服务端 `b36d47a` + 前端 `f2e838a` + CI 修复 `3d93427` 全部入生产 | 注册链路 / 前端版本变更时 |
- G3:C01–C14 逐项判定 → **已完成 10-07 口径复核(见 `docs/release/go-no-go-checklist-2026-10-07.md` 文末《2026-09-24 范围对齐复核》)**
| 09-26 | 首发范围面一致性复核(D-11 ② / C02) | 🟡 文字已改,运行时待收敛 | ADR-0002 已改批为「C 端 + 后台管理平台」(2026-09-26 修订,原 C-only 结论作废并保留原论证);**机器契约 `api_allowlist` 42 条 == 运行时 `PHASE_ONE_API_CONTRACT` 逐条相同、零重复**(`tests/architecture/test_authoritative_backend_policy.py` 通过)。**但**该 42 条编码的是修订前的 C-only 范围(注册/登录/查询/我的查询/报告/付费/区域统计路由实测均 `in_phase_one_allowlist=False`),而生产实际 `RELEASE_PHASE=consumer_active`(全放行)+ `ENVIRONMENT=staging`(只读实测)→ 声明的发布边界在生产**未生效**,门禁实际来自服务层鉴权/RLS/额度;B 端页在生产无门禁。未闭合项 U1–U5 见 `docs/release/go-no-go-checklist-2026-10-07.md` §F | phase/首发面决定落地并重跑范围回归后 |
| 09-26 | release-scope 缺口 U2 / U5 / U6 闭合(Codex 派工) | ✅ | commit `6507da1`(夜班通道恢复后交付),Release Gate `36242841047` **success**;**验收方独立实跑**:`tests/architecture/test_release_scope_regression.py` **5 passed**、`tests/unit tests/architecture` **497 passed / 91 skipped**(基线 492,+5 零回归)。**U1 / U3 / U4(首发面 vs allowlist、`ENVIRONMENT=staging` 标签、B 端无门禁)仍待用户决策**,不在本次范围 | allowlist / phase / release_scope 变更时 |
| 09-26 | 首周观察看板定义 + 四语言上线公告草案(D-10,提前一班) | 🟡 定义已交付,生产采集未执行 | `docs/operations/first-week-observation-dashboard.md`(+ 同源机器可读 `…json`,4 域 / 18 指标,`read_only=true`、`production_contacted=false`,全部指标为**只读 `select` 或只读命令**);`docs/release/launch-announcement-2026-10-07.md` **四语言**(zh-CN / zh-Hant / ja / en,未定事实显式占位 `待定`/`未定`/`TBD`)。本班实测:看板唯一可离线实测的一格 `audit_content_library_provenance.py` → 6/6 条、违规 0、两副本 sha256 相同;`pytest tests/unit tests/architecture -q` **492 passed / 91 skipped** 零回归;`check_release_policy` PASS;`compileall` OK。commit `cf226b2` | 上线后首次采集、公告占位填实(待 D-5 法务)后重验 |
| 09-25 | 生产注册门 `disable_signup` 切换 | ✅ | 管理 API `PATCH /v1/projects/<ref>/config/auth`:`disable_signup` **False → True**(HTTP 200),复读确认 `true` 且 `mailer_autoconfirm` 保持 `false`。**双面验证(生产实测)**:① `POST {<project>}/auth/v1/signup` → **422 `signup_disabled`**「Signups not allowed for this instance」=**绕过限流/consent 的 GoTrue 直连注册已关闭**;② 我方 `POST /api/auth/invite-register`(无码)→ **201 + user_id** = **正常注册不受影响**(含 Admin API 建号未受该开关影响);③ 探针账号 `DELETE /auth/v1/admin/users/{id}` → **200**,残留 0。**本行取代 09-24「生产注册门 🔴 未生效」的口径**(邀请制已废弃,改为开放注册 + 关直连旁路) | Auth 配置 / 注册链路变更时 |
- G4:生产迁移/RLS/额度/日志终检 + 回滚预案演练(09-27 ~ 09-30 窗口)
| 09-26 | 生产 `RELEASE_PHASE` → `consumer_launch`(B 端门禁生效) | ✅ | 生产代码前滚 `711c73f` → `cee2b22`;`deploy/.env` `RELEASE_PHASE` **consumer_active → consumer_launch**(备份 `.env.bak-20260926-release-phase`);api 镜像重建(运行时变更仅 `backend/app/release_scope.py` 一文件,零前端变更)。**冒烟 32 项**:A 组 20 条(C 端注册/查询/报告/付费/intake/recognition/账号删除 + 后台 admin 6 条)**零门禁拦截**;B 组 12 条(region-stats±trend、org me/usage/members/exports、exports、analysis、org invitations、service tasks、usage summary、privacy)**全部 `404 GATE`**。判定按**响应体**(门禁 404 含 `release phase` 字样)区分,而非仅看状态码。前置校验:容器内 `/app/backend/app/release_scope.py` 含 `CONSUMER_LAUNCH` 5 处 | release phase / 前端 API 依赖变更时 |
- G5:发布公告 + 首周观察看板 → **看板定义与四语言公告草案已成型(2026-09-26 夜班,commit `cf226b2`)**;剩上线后首次采集与占位填实
- G6/G8:提审材料 / 退款客服流程(用户口径 + Hermes 起草)
- G7:合规评估与备案(并行轨道)
- ~~**新增(09-24 实测)**:一次部署批次(4 条迁移 + r63 前端 + 注册门切换,需用户批准)~~ → **已执行(2026-09-24 夜班,见本表 09-24 行)**;仅注册门切换保留
- **新增(09-24 夜班)**:C13 真实 staging 运行 + 浏览器审计(工程载体已交付;需用户一次性 staging 写入授权 + `SMOKE_ANON_KEY` / `SMOKE_OWNER_TOKEN` / `SMOKE_OTHER_TOKEN`)
