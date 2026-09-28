# On-call and alert path

This runbook defines the pre-production response path. It does not authorize a deployment, database mutation, credential change, or customer-data access.

## Ownership and acknowledgement

Hermes is the first responder: acknowledge alerts within 15 minutes, preserve the alert and read-only evidence, and classify impact. Codex investigates and prepares a bounded fix or forward-fix. The user is the final decision-maker（最终决策）for customer communication, any authorized change, traffic reduction, rollback, provider action, or production deployment.

If Hermes has no acknowledgement after 15 minutes, notify the user. If user impact, suspected data exposure, payment loss, or a security boundary failure is indicated, notify the user immediately; do not wait for diagnosis. Codex provides a written mitigation recommendation within 60 minutes of a confirmed actionable incident, subject to access and evidence availability.

## Alert conditions

| Signal | Alert when | Initial action |
| --- | --- | --- |
| health | `/health/ready` fails twice in five minutes, or liveness fails once | Read endpoint/status and correlated logs; do not restart or deploy without authorization. |
| backup freshness | latest manifest exceeds the configured freshness threshold | Read manifest time/checksum and backup job result; user decides recovery action. |
| report outbox | failed, zombie-running, or pending-due count is non-zero | Read queue age/status and worker health; pause intake only with authorization. |
| quota anomaly | rate-limit storage unavailable, unexpected sustained 429s, or entitlement consumption spikes outside invited baseline | Preserve aggregate counts only; no raw IP/email in alert text. |
| payment webhook | any terminal webhook validation/processing failure or retry exhaustion | Preserve provider event identifier only; user decides payment-provider action. |

## 只读 self-check versus 授权变更

Read-only self-checks may inspect health endpoints, logs, metrics, migration ledger, queue aggregate counts, backup metadata, and checksums. They must redact secrets and PII. An authorized change requires the user's explicit approval and a target, rollback/forward-fix path, and verification query; examples include migrations, restarting/scaling services, changing rate-limit parameters, replaying jobs, provider configuration, traffic changes, billing changes, and any deployment. Never put secrets in this document, alerts, tickets, or logs.

## Escalation and closure

Hermes records timestamp, symptom, scope, read-only evidence, and current owner. Codex records the suspected class and proposed remediation. The user either authorizes a specific change or keeps the system in safe degraded mode. Close only after a fresh health/queue/backup or webhook verification appropriate to the incident; document residual risk and any follow-up. Production alert delivery and rehearsal remain `NOT_EXECUTED` until separately authorized.

## 告警链路(2026-09-27 建立)

**分层设计 —— 不重复实现检查逻辑:**

| 层 | 位置 | 频率 | 做什么 |
|---|---|---|---|
| 检查 | 生产主机 `observability-check.timer` (systemd) | **每 15 分钟** | 跑 `deploy/observability-check.sh`:容器状态、`/health/ready`、**R2 备份新鲜度**、数据库指标;结果追加到 `/var/log/zouseeking/observability.log`,失败时非零退出 + 摘要 |
| 派遣 | 本机 Hermes cron `告警·小象生产值守(15分钟)` (`no_agent` 脚本任务) | **每 15 分钟** | SSH 读取该日志的判定,按需推送 |

**关键行为**:
- **静默即正常** —— 脚本 stdout 为空则不投递(不产生噪音);
- **变化才通知** —— 以「故障集合」的规范化指纹去重:同一持续故障**只在首次出现时**报一次,不会每 15 分钟刷屏;故障消失时发一条**恢复通知**;
- **首次运行静默** —— 建立基线,不会为从未报告过的故障发"恢复通知";
- **只读** —— 仅通过 SSH 读一个日志文件,不写、不重启、不部署;
- 一并从本机探测站点与 API 端点,覆盖「SSH 通但整机对外不可达」的情形。

**已验证**:故障注入 → 告警输出;同一故障重跑 → 静默;恢复 → 恢复通知;服务器侧检查停滞 > 90 分钟 → `CHECKER_STALLED` 告警。

**已知边界**:派遣层运行在本机,本机关机期间不会派发(生产侧检查仍在跑并留日志,恢复开机后可见);这是当前单机条件下的取舍,已如实记录而非当作无此问题。
