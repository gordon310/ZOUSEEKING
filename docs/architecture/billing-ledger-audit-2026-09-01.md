# Stripe 与用量账本离线审计

**审计日期：** 2026-09-01
**范围：** C17 `backend/app/billing/`、C18 `backend/app/usage/` 及其测试/发布边界。
**结论：** 离线 contract PASS；正式 provider、数据库和商业化上线 BLOCKED。

## 已验证的边界

- billing 默认未配置时所有操作返回安全 `503`，不会创建订单、权益或退款。
- Checkout 只能从服务端价格白名单解析产品、币种、金额和 provider price；浏览器不能提交 `price_id`、customer、金额、币种或跳转 URL。
- webhook 先对原始 request body 验证 `Stripe-Signature`，再按唯一 `event.id` claim/process；重复投递不重复副作用，暂时性失败保留通用重试响应。
- 退款、取消、dunning 和审计使用受限服务端端口；审计值脱敏，客户端不能提交 actor/finance 权限。
- usage ledger 只在离线 in-memory 模型中验证 UTC+08:00 日/月账期、owner/organization scope、幂等、`reserve/commit/release`、冲正语义和并发容量不变性。
- `/api/usage/events` 默认未加入 `consumer_intake_preview` allowlist；客户端不能覆盖 `user_id`、scope 或 limit。

## 可重跑命令

```bash
python3 -m pytest -q tests/billing --confcutdir=tests/billing
python3 -m pytest -q tests/unit/test_usage_ledger.py tests/api/test_usage_routes.py
```

本轮结果：billing `38 passed`；usage/API `15 passed`。完整回归使用仓库测试环境执行，结果 `246 passed`。

## 未完成门槛

本审计没有创建或修改 billing/usage migration，没有连接真实 PostgreSQL、Auth/RLS、Stripe 或其他 billing provider，也没有收费、退款、webhook delivery 或生产配额 UAT。进入正式 V1 前仍需：

1. 完成 baseline reconciliation 后的 reviewed membership/billing/usage forward migration、约束、索引和 owner/organization RLS；
2. 将 in-memory ledger 替换为多实例数据库事务/锁，并验证 crash、重试、重复 webhook、跨周期幂等和账务冲正；
3. 在 Stripe test mode 完成 Dashboard、Customer Portal、税费/收据、取消、退款和 dunning 演练；
4. 取得 provider backup/restore、staging/production billing 与 live-change 明确批准。

因此，本审计只更新离线证据，不改变第一阶段 allowlist，也不授权任何 live billing 或数据库操作。
