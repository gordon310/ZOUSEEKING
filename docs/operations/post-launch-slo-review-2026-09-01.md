# 上线后 SLO、容量与成本复盘门槛

**审计日期：** 2026-09-01

**状态：** `BLOCKED_PRE_PRODUCTION`（只完成离线证据整理，未读取客户内容）

## 结论

当前项目没有 production hostname、production 聚合指标或正式流量，因此不能完成
C23 要求的 30/60 日 SLO、成本、错误预算、Storage 增长、worker backlog 和数据库
pool 复盘，也不能声称已经完成上线后优化。当前 Render 配置仍是 staging-only；
本报告不授权远程探测、数据库变更或部署。

## 需要的聚合证据

上线后由负责人提供脱敏、按时间窗口聚合的 30 日和 60 日数据；不导出邮箱、地址、
文件、原始请求体或其他客户内容。

| 轨道 | 最少字段 | 当前状态 | 优化门槛 |
| --- | --- | --- | --- |
| API/SLO | request count、2xx/4xx/5xx、timeout、p50/p95/p99、按 route/region 聚合 | `NOT_AVAILABLE` | 连续 3 个窗口超阈值才开 profile |
| 错误预算 | 窗口错误率、SLO 目标、消耗/剩余预算 | `NOT_AVAILABLE` | 超预算暂停扩流并进入 incident review |
| DB pool | 实例/worker 数、pool 使用率、acquire wait、连接耗尽、慢查询摘要 | `NOT_AVAILABLE` | 先 traced query/profile，再调整 pool/索引 |
| Worker | backlog、最老任务年龄、重试、DLQ、成功/失败类别 | `NOT_AVAILABLE` | backlog > 80% 或 DLQ 增长时暂停接收 |
| Storage | 对象数、总字节、增长率、孤儿对象、清理成功率 | `NOT_AVAILABLE` | 只使用聚合计数，不读取对象内容 |
| 成本 | workspace/API/worker/DB/storage/backup/egress 月度账单 | `NOT_AVAILABLE` | 重新读取 provider 价格并保留 10–20% headroom |

生产指标为空不是零值；在证据缺失时保持 `NOT_ASSESSED`，不以 staging 或本地 synthetic
结果外推 production。

## 已有离线基线

`docs/operations/staging-capacity-baseline-2026-09-01.json` 只覆盖本地 synthetic
ASGI/pool/bounded queue/static inventory：FastAPI `100/100`、pool 上限 `5`、队列
`20 accepted / 20 rejected`。静态总量在总预算内，但 `web/assets/logoELE.png`
为 `945,771B`，超过提议的 `512KiB` 单文件预算，整体 verdict 保持 `FIX`。

该 baseline 不包含真实 PostgreSQL、Render 冷启动、CDN、provider quota、worker
重启或 production error rate。生成资产由脚本拥有，本轮不手工压缩、删除或覆盖。

## 优化规则

- 没有 traced query、profile 或聚合指标，不新增索引、不提高并发、不改缓存策略。
- 每项优化必须记录变更前/后同口径指标、样本窗口、回滚方式和 owner；没有前后对比则保持 `NOT_EXECUTED`。
- `BackgroundTasks`、Edge Function、local worker 和 legacy regional executor 仍是冻结/竞争路径；没有 durable worker、队列深度和 crash/replay 证据前，不为它们分配 production SLO。
- 任何数据库、Auth/RLS/Storage、provider、DNS、billing 或部署动作都要另取明确授权。

## 重新开启顺序

1. 取得 production 聚合指标、region、实例/worker 数和成本账单的只读导出。
2. 对超阈值轨道生成 traced query/profile，形成最小修复并在隔离环境回归。
3. 记录前后对比、错误预算、容量余量、rollback window 和 change owner。
4. 另行评审 [ADR-0002 Render PostgreSQL future migration](../architecture/adr-0002-render-postgres-future-migration.md)；默认结论继续为不迁移。

机器状态见 [`post-launch-slo-review-2026-09-01.json`](post-launch-slo-review-2026-09-01.json)。
