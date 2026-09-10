# 支付接线设计 · Billing Rollout(2026-09-10,D1=境外主体已定)

## 现状与断点(全部代码实测)

- billing 服务层完整但**从未真接线**:`routes.get_billing_service()` 明写 "wiring intentionally absent until an approved rollout",一律 503 BillingNotConfigured。
- **契约断点**:`BillingService`(service.py,7 个 public 同步方法 + 构造)与 `StripeGateway` Protocol(ports.py,同步)同步调用 `self.store.*`/`self.gateway.*`;但唯一真实实现 `PostgresBillingStore`(store.py 1469 行,功能完整)所有方法均为 **`async def`**。若按现签名接线,service 拿到未 await 的 coroutine → 必然坏。
- 附带缺口:无 StripeGateway 具体实现;无任何 STRIPE_* env 读取;`requirements.txt` 无 HTTP 客户端(无 stripe/httpx/requests)。

## 目标架构:全异步化(最小契约修正)

统一为 async 链:**routes(async,已是)→ service(async)→ store(async,已是)/ gateway(async,新)**。

1. **ports.py 契约修正**:`BillingStore` Protocol 方法声明 `async def`(与 PostgresBillingStore 实现一致);`StripeGateway` Protocol 4 方法改 `async def`(create_checkout_session / create_portal_session / cancel_subscription / create_refund)。
2. **service.py async 化**:7 个 public 方法加 `async`;内部全部 `self.store.*`、`self.gateway.*` 调用前加 `await`(~20 处);`_event_side_effects` 若调 store 同步处同步处理(它不调 store,返回元组,不需改——实施时核对)。构造不变。
3. **gateway.py 新建 `StripeHttpGateway`**(实现 async Protocol):
   - 构造:`StripeHttpGateway(secret_key: str, *, timeout: float = 30)`(不读 env,env 由 wiring 读后传入——保持可测)
   - 出站:标准库 `urllib.request` 包 `asyncio.to_thread`(不加第三方依赖;AGENTS:标准库够用);base `https://api.stripe.com/v1`,Basic Auth(secret_key),form-encoded body
   - `create_checkout_session(params)` → POST /checkout/sessions → CheckoutSessionResult(session_id, url, 错误时抛 BillingGatewayError 语义——沿用 service 现有异常处理:BillingError)
   - `create_portal_session(customer_id, return_url)` → POST /billing_portal/sessions
   - `cancel_subscription(subscription_id, *, at_period_end)` → DELETE /subscriptions/{id}(at_period_end 用 query 或 update;实现按 Stripe API:DELETE /v1/subscriptions/{id}?at_period_end=true)
   - `create_refund(payment_intent_id, *, reason)` → POST /refunds
   - 非 2xx:读 error json message → 抛 BillingError(status_code 502?与 _http_error 兼容;设计:BillingGatewayError 归入 BillingError 500 系)
4. **routes.py**:`create_checkout`/`create_portal`/…/`handle_webhook` 内 `service.*` 调用加 `await`(get_status/request_cancel 等所有 service 调用点)。
5. **wiring(get_billing_service)**:读 env 后构造;任一必需 env 缺失 → 保持 503 BillingNotConfigured(优雅降级,不炸启动):
   - `STRIPE_SECRET_KEY`(test 或生产 key)
   - `STRIPE_WEBHOOK_SECRET`(webhook 签名验)
   - `STRIPE_PRICE_IDS`(JSON 对象,key=`{product_code}:{currency}` → Stripe price id;缺的 price → PriceUnavailable/409,不整体 503)
   - `BILLING_SUCCESS_URL` / `BILLING_CANCEL_URL` / `BILLING_PORTAL_RETURN_URL`(回落默认 staging 页)
   - store:`PostgresBillingStore()`(自取 get_pool)
6. **catalog**:不改(PriceCatalog(price_ids) 已按 `{product}:{currency}` 键设计,由 wiring 喂 env 解析的 map)。

## 实施步骤(每步独立验收,codex 分步派工)

| 步 | 内容 | 验收 |
|---|---|---|
| S1 | ports.py:Store/Gateway Protocol async 化 | compileall + 类型核对 |
| S2 | service.py async 化 + 全部 await | 既有 billing 单测改 AsyncMock 后绿 |
| S3 | gateway.py StripeHttpGateway(标准库+to_thread)+ 单测(固定 fixture 回放:2xx/4xx/网络错) | gateway 单测绿 |
| S4 | routes.py service 调用加 await + get_billing_service wiring(env→构造;缺 env 503) | 缺 env 时 /billing/* 503;mock env+monkeypatch gateway 时 checkout 202 |
| S5 | 测试全量对齐(tests/billing conftest 同步→async mock;pytest-asyncio 是否已在?无则加配置或 tests 用 asyncio.run) | tests/billing + tests/unit 全绿 |
| S6 | 真验(需 Stripe test key,后补):本地起服务 + test key → 真实 checkout session 创建 → webhook 本地转发验签 | 真 key 验收 |

## 风险与回滚
- service async 化是全文件改动(508 行):分方法提交(每方法独立 commit 检查点),git 可逐方法回退。
- 现有 billing 测试若大量同步 mock → S5 工作量在测试改造;先跑 `pytest tests/billing -q` 摸底再定。
- 不发生产 key、不在 staging 开真收款,直到境外主体 Stripe 生产账户 KYC 完成(用户侧)。
- test key 阶段:webhook 用 Stripe CLI 本地转发(stripe listen → http://127.0.0.1/stripe/webhook?按部署)或 staging 配 webhook endpoint。

## 决策记录
- D1(2026-09-10 用户):境外主体开 Stripe 生产账户;开发/验收先行 test key。
- 本设计待用户批准后入库并排实施;D10(a 查询预填)与支付接线同属 09-15 主工期单元。
