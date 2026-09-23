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
| 09-23 | ⚠️ 静态资源超预算 | ❌ 待修 | 总量 2,366,624 B、最大 logo 945,771 B,容量判定 `FIX` | 优化后重验(排入本轮) |
| 09-23 | 正式上线口径 | ✅ | 用户拍板:Web/PWA 先行,硬出口 **2026-10-07**;商店/备案为并行轨道 | 用户改口径时 |

## 待闭合(未完成项,不属本台账)
- G2-ENG:邀请制准入 + 试运行标识(工程缺口)
- G3:C01–C14 Go/No-Go 逐项判定(审计进行中)
- G4:生产迁移/RLS/额度/日志终检 + 回滚预案演练
- G5:发布公告 + 首周观察看板
- G6/G8:提审材料 / 退款客服流程(用户口径 + Hermes 起草)
- G7:合规评估与备案(并行轨道)
