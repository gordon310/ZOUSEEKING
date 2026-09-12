# Rollback / Forward-Fix Checklist

上线前由发布负责人逐项确认；任一项未完成就停止发布。当前主回滚目标按优先级为：**Render 恢复（仅在仍保留可恢复服务时）/ 前一个已批准 commit 的 AWS Lightsail Compose 部署 / 数据库迁移前状态**。数据库已应用 migration 不使用 `git revert` 伪回滚。

- [ ] 记录当前 release tag、commit SHA、candidate/evidence artifact 路径和 SHA-256。
- [ ] 记录 AWS Lightsail 实例/Compose 服务、四站点域名、运行窗口、审批人、rollback owner、告警渠道和停止条件。
- [ ] 记录 Render 当前挂起状态、保留期限和是否具备恢复条件；若退役，先完成替代回滚演练再删除依赖。
- [ ] 在任何线上 SQL 之前生成 schema-only backup，记录加密存储位置、时间和 restore target；不导出客户行、邮箱或 Storage 对象。
- [ ] 确认 Supabase migration history、schema drift、RLS policy 快照、Storage policy 和备份可读性。
- [ ] 先在 disposable 数据库完成 fresh reset 与相关 SQL/RLS 测试；失败时停止后续 migration、部署和流量切换，保留 SQLSTATE、受影响对象和 evidence manifest。
- [ ] 若应用回滚：停止当前 Compose 流量，恢复前一个已批准 commit/artifact，重新生成 frontend config，启动 `api`/`worker`/`scheduler`/`nginx`，并验证四站点与 API health。
- [ ] 若需 Render 恢复：只恢复已批准的旧服务/commit，确认域名、环境变量、数据库连接和 webhook 不会与 Lightsail 双写或争抢流量。
- [ ] 若数据库已变更：使用审核通过的 forward-fix；按需执行 expand/backfill/switch/contract，并保留迁移前 backup 与验证查询。
- [ ] 恢复或 forward-fix 后验证表、约束、索引、RLS/policy、job 状态、支付订单/报告解锁一致性；row count 只作为数量证据，不导出业务内容。
- [ ] 重新运行完整离线 gate、drift 对比、浏览器 smoke、API live/ready 检查和受控支付/报告检查；真实资料测试需单独授权。
- [ ] 线上 Auth、Storage、DNS、Stripe production webhook、真实账号和日志分别记录真实结果；未执行项目保持 `NOT_EXECUTED`。
- [ ] 发布负责人确认 rollback/forward-fix 证据完整，且明确是 Go 还是 No-Go；本 checklist 不替负责人作决定。
