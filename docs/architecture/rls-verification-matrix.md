# M1 staging RLS、Auth 与 Storage 验收矩阵

**验收日期：** 2026-09-02

**环境：** 明确授权的 Supabase staging

**结论：** `PASS`（仅 M1 staging）；production 为 `NOT_EXECUTED`

## 身份矩阵

| 身份 | 数据库预期与结果 | 私有 Storage 预期与结果 | 状态 |
| --- | --- | --- | --- |
| 匿名 | 只能读取 active `query_field_options`；不能读取或写入会员、项目、查询、报告、任务或 provenance 私有记录 | bucket 不公开；list/download/upload/delete 均拒绝 | `PASS` |
| 本人 | 只能读取自己的私有记录；只允许新增/读取自己的 profile 并修改 preference，不能修改 `membership_tier`、额度或 owner 字段 | 浏览器不直连对象；list/download/upload/delete 均拒绝，由 FastAPI/worker 代办 | `PASS` |
| 他人 | 不能读取或修改 owner fixture，也不能通过 owner ID、email 或路径猜测越权 | 不能读取或修改 owner 对象 | `PASS` |
| worker | service role 可完成受信读写；PK/FK/UNIQUE/CHECK、provenance rights、policy overlap 和 append-only constraints 继续生效 | 完成 upload、download、delete、restore、delete；恢复内容 hash 一致 | `PASS` |

owner 的 Storage direct access 被拒绝是当前架构契约：浏览器只使用 Supabase Auth
和公开 field options，私有上传/下载通过 FastAPI 与受信 worker。它不是“owner
policy 缺失”，也不能为了前端方便新增宽泛 `storage.objects` policy。

## Auth 生命周期

| 检查 | 结果 | 状态 |
| --- | --- | --- |
| staging 要求 email confirmation | 设置与未确认登录拒绝一致 | `PASS` |
| signup token verify 与确认后登录 | 合成 `.invalid` 用户完成确认，随后可登录 | `PASS` |
| 重复注册与无效登录枚举安全 | 响应不暴露既有 user ID，错误形状保持统一 | `PASS` |
| password recovery | Admin 生成 recovery token、verify、更新密码；旧密码拒绝，新密码接受 | `PASS` |
| refresh rotation 与 global logout | refresh 成功轮换；global logout 后 refresh token 被撤销 | `PASS` |
| hard delete 与 profile cascade | Auth Admin 删除后无法 refresh/登录，profile 已级联清理 | `PASS` |
| 公开恢复邮件真实投递 | 没有专用 SMTP sink；未向真实地址发送 | `NOT_EXECUTED` |

Supabase access JWT 在签发后可能持续有效到自身过期；global logout 主要撤销 refresh
session。本验收不把“refresh 已撤销”误写为“所有已签发 access JWT 立即失效”。

## Storage 与恢复边界

- bucket `property-intake` 为 private，允许类型为 PDF/JPEG/PNG，单对象上限 20 MiB。
- 数据库 logical backup 只覆盖 Storage metadata，不包含对象 blob。
- staging 原有 object count 为 0；M1 使用单一 synthetic fixture 做对象
  upload/download/delete/restore/delete 和 hash 校验，最终 object count 回到 0。
- 该结果证明权限与最小恢复闭环，不证明 production 批量对象备份、保留或 RPO/RTO。

## 数据库最终断言

- 22 张 application table 全部启用 RLS。
- selected-role grant count：`anon=1`、`authenticated=15`、`service_role=154`。
- 只有 active field-options anonymous policy；property client write policies 已移除。
- staging ledger 只在原三条 ID 后增加
  `20260902000100_staging_baseline_reconciliation.sql`，未执行 migration repair。
- 最终 fixture 清理：Auth users `0`、public 业务行 `0`、Storage objects `0`。

## 可重跑入口与限制

本地静态/单元测试入口为 `tests/unit/test_staging_m1_acceptance.py`；获批 staging
行为入口为 `scripts/staging_m1_acceptance.py`，要求 exact staging target 和显式
live-write 开关，运行过程中不打印 key/token/email。任何再次运行仍需要新的 live
授权，不能把本文件当作长期写权限。

详细 migration、backup/restore、hash 和 catalog 证据见
[`migration-reconciliation-report.md`](migration-reconciliation-report.md)；生产恢复
边界见 [`database-recovery-runbook.md`](../operations/database-recovery-runbook.md)。
