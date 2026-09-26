# 上线首周观察看板(数据 / 支付 / 任务 / 错误)

> 交付自倒排 **D-10**(2026-09-27,`docs/superpowers/plans/2026-09-24-launch-countdown-10-07.md`)。
> 机器可读口径:[`first-week-observation-dashboard.json`](./first-week-observation-dashboard.json)(由 `scripts/check_first_week_observation.py` 守护)。
> 口径:**只读**;本条目的当前状态是「已定义、未采集生产数据」(`production_contacted = false`)。

## 0. 用途与边界

- 用途:上线首周(2026-10-07 起)用**同一套固定口径**回答四个问题——数据是否可信、钱是否对得上、任务是否跑完、错误是否可归因。
- 边界:看板**不**改变任何门禁。配额、RLS、鉴权、发布门禁仍由服务端与数据库承担;看板只做观测与判读。
- 红线:所有查询只允许 `select`;所有命令只允许只读(`docker compose ps/logs`、`curl` 只读 GET、既有只读脚本)。**不允许**在看板里出现写库、改状态、改配置的动作。
- 隐私:看板只出**聚合数**。不落姓名、邮箱、令牌、连接串、原始请求体;限流相关只允许走已哈希的 `subject_hash`。

## 1. 观察窗口与节奏

| 窗口 | 时间 | 频次 | 汇总方式 |
|---|---|---|---|
| `first_hour` | 上线首小时 | 每 15 分钟 | QQ 值班汇报(只报与阈值不符项 + 一行总数) |
| `first_24h` | 上线后 24 小时 | 每 2 小时 | 同上 |
| `first_week` | 上线首周 | 每日 09:30 巡检 + 每日 20:30 值班 | 每日一条日汇总(含前一日判读) |

既有载体(不重复造第二套):

| 载体 | 覆盖 | 现状 |
|---|---|---|
| `deploy/observability-check.sh` | 容器存活、就绪探针、备份新鲜度、僵尸/待办计数 | 已在生产每 15 分钟运行(systemd timer) |
| 后台管理平台健康 / KPI 区 | 采集运行、质量、服务任务、财务 | 已接真实数据(8 区) |
| Hermes 每日 09:30 生产巡检 + 每日 20:30 值班 | 人工判读与升级 | 已在跑 |
| 支付对账专项(倒排 D-11,09-26 20:00) | live 遗留单 / webhook / 价格 ID | 已排定 |

## 2. 数据域

| 指标 | 来源 | 只读口径 | 阈值 | 降级动作 | 责任人 |
|---|---|---|---|---|---|
| MLIT 成交价新鲜度 | `public.mlit_transactions`(官方开放数据) | `select max(trade_quarter), max(imported_at) from public.mlit_transactions` | 导入距今 ≤ 45 天;季度不低于官方最近发布 | 标注「该季度」并禁止「最新行情」表述 | 数据责任人 |
| 租金参考统计年份 | `public.rent_reference_stats`(官方免费源) | `select max(survey_year), max(fetched_at) from public.rent_reference_stats` | 抓取 ≤ 45 天;页面必须带 `survey_year` | 缺年份即下线该指标,保留空态 | 数据责任人 |
| 统计查询计量 | `public.usage_events`(`usage_kind = 'stats_query'`,`operation = 'consume'`) | 见 JSON 契约 | 与 `/api/org/region-stats` 的 200 响应数差额 = 0 | 出现无计量响应即列当日阻断 | Hermes 值班 |
| 发布门禁违规 | 两份内容库 provenance | `python3 scripts/audit_content_library_provenance.py --output /tmp/first-week-provenance.json` | `non_synthetic_violations = 0` 且两副本 hash 一致 | 违规 > 0 即停止对外展示 | 数据责任人 |
| 来源授权覆盖 | `public.collection_sources` | `select count(*) filter (where enabled and not rights_confirmed) from public.collection_sources` | 启用中未确认授权 = 0 | 停用未授权来源,不得先发布后补授权 | 数据责任人 |

**本班离线实跑(真实输出)**:`scripts/audit_content_library_provenance.py` → `canonical_record_count = 6`、`web_record_count = 6`、`non_synthetic_violations = []`、两副本 `sha256` 相同(`301cf824…a1a7a`)、退出码 0。这是本条目**唯一已实测**的一格,其余格子均为定义,生产数据待上线后采集。

## 3. 支付域

| 指标 | 来源 | 只读口径 | 阈值 | 降级动作 | 责任人 |
|---|---|---|---|---|---|
| live 超期未终态单 | `public.payment_orders`(`provider = 'stripe'`) | `select count(*) ... where status in ('pending','failed') and created_at < now() - interval '1 hour'` | 0;非 0 每单可追溯 | 与支付平台逐单核对并留处置记录,**禁止直接改库状态** | 财务角色 |
| webhook 处理 | `public.payment_events` | 失败数与 `received` 滞留 ≥ 15 分钟数 | 两项均为 0 | 检查端点与签名校验;补单走审计路径 | 财务角色 |
| 价格 ID 一致性 | `public.pricing_prices` ↔ 支付平台 active price | 两侧 active 集合逐条比对 | 集合相同、币种金额一致 | 冻结该价格售卖入口并通知用户 | 财务角色 |
| 退款积压 | `public.refunds` | `select count(*) ... where status = 'pending'` | 0 | 超 3 个工作日未终态升级给用户 | 财务角色 |

金额口径:一律带**币种 + 最小单位**(表内为 `amount_minor` + `currency`),不使用展示字符串反算。

## 4. 任务域

| 指标 | 来源 | 只读口径 | 阈值 | 降级动作 | 责任人 |
|---|---|---|---|---|---|
| outbox 五态分布 | `public.report_generation_outbox` | `select status, count(*) ... group by status` | `failed = 0`;`pending`/`running` 与在飞请求相符 | 按 `last_error_code` 归类并通知用户,**禁止手工插报告** | 工程值守 |
| 最老到期等待 | 同上 | `select coalesce(extract(epoch from now() - min(next_attempt_at))/60, 0) ... where status = 'pending'` | ≤ 5 分钟 | 检查 `report-worker` 存活与租约回收;重启需用户批准 | 工程值守 |
| 失败分类 | 同上(`last_error_code`,不含异常原文) | 见 JSON 契约 | 全部失败均已登记分类码 | 未登记分类码即补登记并评估重放 | 工程值守 |
| worker 存活 | 生产 compose(只读) | `docker compose -f deploy/docker-compose.prod.yml ps --services --filter status=running` | `api` / `report-worker` / `worker` / `nginx` 全在 running,重启次数当日不再增长 | 缺失即当日阻断 | 工程值守 |

队列语义以 `docs/architecture/report-job-queue-contract.md` 为准(五态、原子认领、租约 15 分钟、三个幂等边界)。

## 5. 错误域

| 指标 | 来源 | 只读口径 | 阈值 | 降级动作 | 责任人 |
|---|---|---|---|---|---|
| 就绪探针 | 生产 | `curl --fail --silent --show-error --max-time 10 https://api.zoubeacon.com/health/ready` | HTTP 200 | 非 200 立即升阻断并按回滚预案判断 | 事故责任人 |
| 结构化错误日志 | api 容器日志(逐行 JSON,脱敏) | `docker compose -f deploy/docker-compose.prod.yml logs --since 15m api` | 每条错误可归类、可关联请求;无异常原文与个人信息 | 未归因错误即当日阻断 | 事故责任人 |
| 限流 fail-closed | `public.shared_rate_limits` + 端点响应 | `select count(*), min(expires_at) ... where expires_at > now()` | 计数正常滚动;存储不可用时返回 503 而非放行 | 放行嫌疑按事故处理,禁止临时放宽限流 | 事故责任人 |
| 备份新鲜度 | 既有观测脚本 | `deploy/observability-check.sh`(需 `DATABASE_URL`,只读) | `backup_age_hours ≤ 36`、`OBSERVABILITY_OK` | 核对定时器与对象存储连通性并通知用户 | 事故责任人 |
| 容器重启 / 僵尸任务 | 同上 | `deploy/observability-check.sh` | 摘要 `failed = 0`、`zombie_running = 0`、`pending_due = 0` | 定位根因后升级,禁止仅重启掩盖 | 工程值守 |

## 6. 判读纪律(与项目红线一致)

1. 单月不称趋势;跨区域不得因同月而平均;每项指标必须能给出**样本量、期间、数据类别、口径、单位、局限**。
2. 官方成交价/租金为季度或年度口径且有发布滞后,**不得**呈现为实时行情;`modeled_estimate` 与 `synthetic_fixture` 不得当作采集事实。
3. 缺件即记「未采集」——**不得估算补齐**,不得用本地结果替代生产证据。
4. 任一指标触发降级动作时,值班汇报只写三件事:事实(实测值)、影响面、需要的决策(含编号选项)。

## 7. 升级路径

- 第一层:Hermes 值班按本表判读 → 命中阈值即在 QQ 值班汇报中单列。
- 第二层:阻断类(就绪非 200、支付遗留、outbox 失败、备份过期)即时通知用户,不等待下一个窗口。
- 责任人角色见 `docs/operations/oncall.md`;**具体责任人姓名与响应 SLA 仍待用户确认**(见待批清单)。

## 8. 缺口(不粉饰)

- 生产数据 **尚未采集**:本看板目前只有定义与一次离线 provenance 实测,不能作为上线健康证据。
- 支付域与任务域的多数指标需要生产只读通道或 live 凭据;缺件时按「未采集」记录。
- 邮件送达率、对象存储配额、CDN 命中率不在本表,分别属通知链路与 C04/C11 范围。
- 首周结束后的收口(哪些指标转常驻、哪些下线)需在 D-1 冻结前确认。

## 9. 待批清单(需用户决策)

1. 首周值班的**责任人姓名与响应 SLA**(与 `oncall.md` 一致);
2. 每 15 分钟窗口的**通知阈值**(是否只报超标项,还是带一行全量计数);
3. 上线公告(见 `docs/release/launch-announcement-2026-10-07.md`)中客服渠道 / 删除 SLA 等占位内容,待法务(D-5)定稿后一并填实。
