# 2026-10-11：保留审计事实的 Auth 删除修补

## 问题与范围

独立本地 Supabase 上真实注册（201）、登录（200）、确认 privacy-2026-10（200）后，Auth Admin DELETE 返回 500。原因是 `audit_events.actor_user_id ON DELETE SET NULL` 的外键动作触发了拒绝全部 UPDATE 的审计触发器。该冲突也影响受控账户删除路径，因此在修补生效前保持 No-Go。

前向迁移 `20261011000200_audit_events_anonymization_allowance.sql` 只替换现有触发器函数。只允许嵌套触发器执行时，已删除 Auth 身份的非空 actor UUID 变为空，且整行其他字段完全一致。直接更新 actor、更新事件事实、DELETE、TRUNCATE 继续拒绝；表权限与 RLS 不变。既有同意历史仍保留。

## 本地证据

`tests/integration/test_policy_consent_postgres.py` 在修补前复现 Auth DELETE 的 append-only 错误，修补后通过；测试检查每个保留字段、并发幂等、其他用户隔离，以及直接 actor/action/time 更新、DELETE、TRUNCATE 都被拒绝。

独立 local Supabase 已按 canonical migration history 应用本迁移。真实 Auth Admin 删除测试账号返回 200；完整 API 注册→登录→确认→受控删除返回 202/completed→旧令牌再次访问返回 401。测试 Auth 身份已清理，脱敏审计事实保留。生产尚未执行本迁移。

## 发布与恢复要求

生产仍为 54 migrations，本迁移新增为第 55 条。先保留已核验的 R2 生产逻辑备份及当前发布版本；以经营者对这一具体在线数据库变更的明确授权为门槛。仅执行此已审查前向迁移，不使用 linked repair、reset 或批量 push。记录事务成功、版本账本新增一条、函数与权限读回、审计行数未减少。

应用回滚到 r67 不会撤销已完成的身份删除或重建 actor UUID。若迁移需撤销，应准备并复核新的前向迁移恢复原触发器函数，重新标记账户删除不可用/No-Go；不得编辑已应用迁移或恢复已删除个人资料。灾难恢复使用已核验备份的独立恢复路径，并按恢复后的账本补做该前向迁移。

真实账户与交易、双真机 PWA、生产告警自动投递、发布观察仍需独立验收。独立本地环境结果不替代生产结果。
