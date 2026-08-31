# Stripe 支付与订阅边界设计

**状态：** 已按用户“执行”授权进入离线实现（2026-08-31）

**适用范围：** V1 产品价格、Checkout、Customer Portal、webhook、订阅状态、退款/取消和计费审计。

**上游决策：** [ADR-0001：权威后端与 Schema 所有权](../../architecture/adr-0001-authoritative-backend-and-schema.md)

## 1. 约束与成功标准

- FastAPI 是私有计费操作和 webhook 的唯一应用边界；浏览器不直接写 Supabase 或 Stripe。
- webhook 必须在 JSON 解析前读取原始 request bytes，并使用 `Stripe-Signature` 验签。
- provider `event.id` 是幂等主键；重复投递只能返回已处理结果，不能重复开通、扣量、退款或发审计事件。
- 暂时性处理失败保留可重试状态并返回 5xx；永久无效事件返回 4xx；未知事件安全忽略并记为已处理。
- 所有状态变化和退款操作写结构化审计事件，日志/响应不得含完整邮箱、token、支付凭证或原始 payload。
- 当前 `migration_baseline_status = reconciliation_required`。本轮不新增或执行 `supabase/migrations/`，不连接 live Stripe，不触碰线上数据库、Auth、RLS、Storage、部署或 billing 配置。

## 2. 价格与账单地区

价格目录由服务端构造，客户端只能提交产品代码和经过验证的账单地区，不能提交 `price_id`、金额或币种。V1 仅发布规格中已经确认的三种币种；没有本地价格的地区返回不可购买，不做客户端汇率换算。

| 产品代码 | 模式 | CNY（最小单位） | JPY（最小单位） | USD（最小单位） |
| --- | --- | ---: | ---: | ---: |
| `risk_report_single` | `payment` | 500 | 100 | 99 |
| `c_plus_monthly` | `subscription` | 4,900 | 990 | 990 |
| `b_data_pro_monthly` | `subscription` | 19,900 | 3,999 | 3,990 |

每个价格有不可变 `price_version` 和服务端配置的 Stripe `price_id`。本地化价格的 `effective_from`、税费口径和最终支付金额由后续财务/合规流程确认；本轮只暴露确定性目录，不声称已在 Stripe 账户创建价格。

## 3. 组件与端口

`backend/app/billing/` 拆分为四类职责：

1. `catalog.py`：价格白名单、币种/模式/版本和金额单位。
2. `signatures.py`：原始 bytes 的 `t=...`/`v1=...` 签名解析、常量时间比较和时间容忍度。
3. `ports.py`：Stripe gateway 与 billing store 的最小协议；store 由未来 canonical membership/billing schema 实现。
4. `service.py`、`routes.py`：Checkout/Portal、事件路由、取消/退款策略、重试分类和脱敏审计。

默认服务不会在缺少显式 `BILLING_ENABLED` 和 gateway/store 注入时运行，路由返回 503“billing 未配置”。这样 staging/production 不会因为部署了代码而意外产生收费。

## 4. Checkout 与 Customer Portal

- `risk_report_single` 使用 Checkout `mode=payment`；月费产品使用 `mode=subscription`。
- 复用 store 返回的 `stripe_customer_id`；不存在时才传经认证账户的 `customer_email`，并始终传 `metadata.user_id`、计费主体、产品和价格版本。
- `success_url`、`cancel_url`、Portal `return_url` 来自受信配置，客户端不能覆盖；开启 promotion code 由服务端决定。
- Checkout 只返回 provider session id/url；权益开通以 webhook 为准，不能信任浏览器回跳。
- Portal 只接受当前认证用户对应的 customer；支持更新支付方式、账单历史、取消和计划更新的能力由 Stripe Dashboard 配置另行验收。

## 5. Webhook 状态机

处理顺序固定为：

```text
raw bytes -> verify signature -> parse JSON -> claim unique event id
          -> apply domain state + audit/outbox in one store transaction
          -> mark processed
```

支持的事件及边界动作：

| 事件 | 动作 |
| --- | --- |
| `checkout.session.completed` | 记录订单/customer/subscription 或 payment intent，待业务主体确认后开通权益 |
| `customer.subscription.created/updated` | 同步 plan、period、cancel-at-period-end 和 Stripe status |
| `customer.subscription.deleted` | 记录取消并撤销下一期权益；保留已付周期状态 |
| `invoice.paid` | 标记账单已支付、订阅恢复 `active`，写续费审计 |
| `invoice.payment_failed` | 标记 `past_due`、暂停新的付费操作、创建一次 dunning outbox |
| `refund.created/updated` | 同步退款状态；成功退款撤销对应未用权益 |

事件表的物理实现必须提供 `unique(provider, event_id)`、`status`、`attempt_count`、`next_attempt_at` 和 failure class；这部分等 baseline 和会员 canonical migration 完成后由 forward migration 实现，本轮由 fake store 验证端口契约。

## 6. 取消、退款与审计

- 取消默认调用 provider 的 `cancel_at_period_end=true`，不立即删除当前已付权益；重复取消是幂等的。
- 退款请求只允许在扣款 48 小时内且没有使用付费权益时进入 `requested`。重复请求返回现有请求；已使用权益的普通退款被拒绝。
- 只有受信的 `finance` actor 可以批准退款；gateway 成功后更新 `succeeded`、撤销权益并记录原因。gateway 暂时性失败进入重试，不把成功状态写早。
- 审计记录字段固定为 actor、subject、action、provider object id、event id、reason、时间和 schema version；邮箱、token、完整 provider payload 和异常堆栈经过脱敏或不保存。

## 7. 重试契约

只对 `transient` 错误重试，最多初次执行加两次重试；退避为确定性的指数间隔并设置上限。`permanent` 错误进入 dead-letter/人工处理，不重复调用 provider。webhook 处理失败返回 5xx 让 Stripe 重投；成功、重复和未知事件返回 2xx。

## 8. 测试与上线门槛

- 单元/路由测试只使用固定 JSON fixtures、fake gateway 和 fake store；不安装 Stripe SDK，不发起网络请求，不使用 live key，不产生真实收费。
- 必测：金额/币种单位、price allowlist、customer 复用、原始 body 验签、时钟容忍度、重复 event、transient replay、订阅/发票状态、取消幂等、48 小时退款窗口、已用权益拒绝、finance 审批和脱敏审计。
- 本轮不验证 Stripe Dashboard Portal 配置、provider backup、线上 webhook delivery、数据库 RLS/migration、支付渠道税费或真实退款；这些是上线前 blocker。
