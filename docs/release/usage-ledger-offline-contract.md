# 用量账本与配额离线契约

状态：C18 offline candidate（2026-09-01）。本文件描述可测试的服务边界，不代表已经完成数据库迁移、Auth/RLS 配置或生产配额上线。

## 责任边界

- 客户端只提交 `kind`、正整数 `units`、`operation`、`period` 和必要的 `reservation_key`，并必须提供 `Idempotency-Key`。
- `user_id`、owner/organization scope 和配额上限由已认证的服务端依赖解析；请求体不能覆盖这些字段。
- `backend/app/usage/ledger.py` 是线程安全的内存模型，用于离线测试和候选适配器。默认 API service 未注入时返回 `503 usage service is not configured`。
- `RELEASE_PHASE=consumer_intake_preview` 或受管环境不会把 `/api/usage/events` 加入第一阶段 allowlist；本候选不会扩大正式发布面。

## 账本语义

- 账期按 UTC+08:00（日本时间）计算；支持自然日和自然月，账期结束时间为 exclusive。
- `consume` 原子增加 `consumed_units`；`reserve` 原子增加 `reserved_units`；`commit` 将原 reservation 转为 consumed；`release` 释放 reservation。
- 每个 scope、operation 的 `Idempotency-Key` 记录请求指纹。相同指纹返回 `duplicate`，不同参数返回 `409 idempotency_conflict`。
- 容量按 `consumed + reserved + requested <= limit` 检查，超过时返回 `429 quota_exceeded`，不得改变已提交计数。
- reservation transition 通过服务端 reservation index 找回原始账期，因此跨 UTC+08:00 日界线提交仍计入原账期；transition 指纹包含 `reservation_key`。
- 事件只追加、不覆盖既有事实；未来需要冲正时应新增明确的 reversal 事件，不得直接改历史计数。

## 错误与验证

| 情况 | HTTP | public code |
| --- | ---: | --- |
| 缺少或空白 `Idempotency-Key` | 422 | `invalid_request` |
| 非法 body、reservation 组合或账期 | 422 | `invalid_usage_request` |
| 同 key 不同参数 | 409 | `idempotency_conflict` |
| reservation 不存在或已结束 | 409 | `reservation_not_found` / `reservation_not_active` |
| 配额不足 | 429 | `quota_exceeded` |
| 未配置可信 usage service 或未知服务故障 | 503 | `usage_unavailable`（默认依赖直接返回配置 detail） |

## 未执行与后续门槛

本轮未创建或修改 `supabase/migrations/`，未连接真实 PostgreSQL、Auth、RLS、Storage、Stripe 或 billing provider，未执行 staging/production quota UAT，也未声称多实例数据库原子性。进入真实配额前必须先完成 migration baseline reconciliation，并提供唯一 migration、约束/索引、owner/organization RLS、备份/restore、限额来源、回滚或 forward-fix 以及并发验收证据。计费权益与用量扣减的正式绑定需在后续 provider 授权窗口单独评审。
