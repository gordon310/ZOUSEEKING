# Rollback / Forward-Fix Checklist

上线前由发布负责人逐项确认；未完成任一项就停止发布。

- [ ] 记录 `release_tag`、commit SHA、candidate/evidence artifact 路径和 SHA-256。
- [ ] 记录变更范围、migration ID、运行窗口、审批人和停止条件。
- [ ] 在任何线上 SQL 之前生成 schema-only backup，记录加密存储位置、时间和 restore target；不导出客户行、邮箱或 Storage 对象。
- [ ] 确认当前 migration history、schema drift、RLS policy 快照和备份可读性。
- [ ] 先在 disposable 数据库完成 fresh reset、`tests/sql/test_foundation_schema.sql`、`tests/sql/test_property_intake_schema.sql` 和 `tests/security/test_rls_private_projects.sql`。
- [ ] 失败时停止后续 migration、部署和流量切换；保留 SQLSTATE、受影响对象和证据 manifest。
- [ ] 已应用的 SQL migration 不使用 `git revert` 回滚；通过审核的新 forward migration 修复，必要时 expand/backfill/switch/contract。
- [ ] forward-fix 在 disposable 环境通过后，重新生成 schema-only backup 并取得新的明确批准。
- [ ] 恢复演练指定恢复目标，执行验证查询（表/约束/索引/RLS/policy/job 状态），记录 row count 只作为数量证据，不导出业务内容。
- [ ] 恢复或 forward-fix 后重新运行完整 CI gate、drift 对比和 smoke checks。
- [ ] 线上 Auth、Storage、DNS、billing、部署和真实账号验证分别记录真实结果；未执行项目保持 `NOT_EXECUTED`，不得从 staging 推断 production。
- [ ] 发布负责人确认 rollback/forward-fix 证据完整后，才允许后续受控发布动作。
