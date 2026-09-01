# Stripe Billing Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不连接 live Stripe 或线上数据库的前提下，为 FastAPI 建立可替换、可审计、可重试的 Stripe 支付与订阅边界。

**Architecture:** 价格目录和业务状态由服务端控制；`BillingService` 依赖 `StripeGateway` 与 `BillingStore` 两个端口。webhook 先对原始 bytes 验签，再由 store 以唯一 event id 原子 claim/process；默认依赖未配置时路由返回 503，避免意外收费。未来 canonical membership/billing migration 完成后，只需提供持久化 store/gateway 实现，不在本计划中猜测物理表。

**Tech Stack:** Python 3.9+、FastAPI、Pydantic v2、asyncpg 端口（本轮不连接）、Python 标准库 `hmac`/`hashlib`/`json`/`datetime`、pytest、FastAPI `TestClient`。

**Spec:** `docs/superpowers/specs/2026-08-31-stripe-billing-boundary-design.md`

## Global Constraints

- FastAPI 是私有计费操作和 webhook 的唯一应用边界；浏览器不直接写 Supabase 或 Stripe。
- webhook 必须在 JSON 解析前读取原始 request bytes，并使用 `Stripe-Signature` 验签。
- provider `event.id` 是幂等主键；重复投递不能重复开通、扣量、退款或审计。
- 只对 transient 错误重试，最多初次执行加两次重试；permanent 错误不重复调用 provider。
- 所有测试只使用固定 fixtures、fake gateway 和 fake store；不安装 Stripe SDK，不发网络请求，不使用 live key，不产生真实收费。
- 当前 `migration_baseline_status = reconciliation_required`；本轮不新增或执行 `supabase/migrations/`，不接入线上数据库、Auth、RLS、Storage、部署、DNS 或 billing 配置。
- 不把金额展示字符串解析为数字；金额以币种最小单位的整数存储和传递。

## File Map

- Create: `backend/app/billing/__init__.py` — billing package exports.
- Create: `backend/app/billing/catalog.py` — immutable product/price definitions and server-side allowlist.
- Create: `backend/app/billing/signatures.py` — raw-body Stripe signature verification and event parsing.
- Create: `backend/app/billing/ports.py` — gateway/store protocols and domain records.
- Create: `backend/app/billing/service.py` — checkout/portal, webhook state machine, cancellation, refund and retry policy.
- Create: `backend/app/billing/routes.py` — FastAPI request/response boundary and safe error mapping.
- Modify: `backend/app/main.py` — include billing router only; no startup schema initialization.
- Create: `tests/billing/conftest.py` — complete fake gateway/store and fixed users/events.
- Create: `tests/billing/test_catalog.py` — price units, currency and allowlist behavior.
- Create: `tests/billing/test_signatures.py` — raw bytes, HMAC, timestamp and malformed headers.
- Create: `tests/billing/test_service.py` — checkout, portal, webhook, status, cancel, refund and retries.
- Create: `tests/billing/test_routes.py` — authenticated routes and raw webhook body contract.
- Modify: `backend/README.md` — safe billing configuration and disabled-by-default runbook.
- Modify: `docs/supabase-setup.md` — future store/migration gate and webhook rollout checklist.

### Task 1: Product Catalog and Domain Models

**Files:**
- Create: `backend/app/billing/catalog.py`
- Create: `backend/app/billing/ports.py`
- Create: `backend/app/billing/__init__.py`
- Test: `tests/billing/test_catalog.py`

**Interfaces:**
- `PriceDefinition(product_code, price_version, currency, amount_minor, mode, stripe_price_id, available)`.
- `PriceCatalog(price_ids: Mapping[str, str])` with `list_public()` and `resolve(product_code, billing_region)`.
- `REGION_CURRENCY = {"CN": "CNY", "JP": "JPY", "US": "USD"}`; unknown/unpublished regions raise `PriceUnavailable`.
- `BillingSubject(subject_type, subject_id, stripe_customer_id, billing_email)`.
- `BillingStatus`, `SubscriptionSnapshot`, `RefundCandidate`, `RefundRequest`, `ProviderEvent`, `EventClaim`, `AuditRecord` dataclasses.

- [ ] **Step 1: Write the failing tests** — assert CNY 49 is `4900`, JPY 3,999 is `3999`, USD 0.99 is `99`; unknown product, client-supplied currency, and HK without a published local price are rejected; missing server price id is not purchasable.
- [ ] **Step 2: Run the catalog test to verify it fails**

Run: `python3 -m pytest -q tests/billing/test_catalog.py`
Expected: FAIL because `backend.app.billing.catalog` and its catalog contract do not exist.

- [ ] **Step 3: Implement the minimal catalog and records** — use integer minor units and immutable dataclasses; do not add Stripe API calls or database code.
- [ ] **Step 4: Run the catalog test to verify it passes**

Run: `python3 -m pytest -q tests/billing/test_catalog.py`
Expected: PASS with no network access.

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing tests/billing/test_catalog.py
git commit -m "feat: define offline billing catalog contract"
```

### Task 2: Raw Webhook Signature Verification

**Files:**
- Create: `backend/app/billing/signatures.py`
- Test: `tests/billing/test_signatures.py`

**Interfaces:**
- `construct_event(payload: bytes, signature_header: str, secret: str, *, now: datetime, tolerance_seconds: int = 300) -> ProviderEvent`.
- `SignatureVerificationError` has no raw payload in its public message.

- [ ] **Step 1: Write the failing tests** — sign a fixed raw UTF-8 JSON fixture with `t=<unix>`, `v1=<HMAC-SHA256>` and assert valid parsing; mutate one byte, use stale timestamp, omit `t`/`v1`, and provide invalid JSON to assert rejection. Include a JSON string whose escaped/Unicode bytes prove the HMAC uses the exact raw bytes.
- [ ] **Step 2: Run the signature test to verify it fails**

Run: `python3 -m pytest -q tests/billing/test_signatures.py`
Expected: FAIL because the verifier is absent.

- [ ] **Step 3: Implement the minimal verifier** — parse only header tokens, compare every `v1` with `hmac.compare_digest`, check absolute timestamp tolerance, verify bytes before `json.loads`, then return a validated event envelope with id/type/data.
- [ ] **Step 4: Run the signature test to verify it passes**

Run: `python3 -m pytest -q tests/billing/test_signatures.py`
Expected: PASS; no HTTP or Stripe SDK call is made.

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/signatures.py tests/billing/test_signatures.py
git commit -m "feat: verify raw Stripe webhook signatures"
```

### Task 3: Billing Service, Idempotency, Status, Cancellation and Refunds

**Files:**
- Create: `backend/app/billing/service.py`
- Test: `tests/billing/conftest.py`
- Test: `tests/billing/test_service.py`

**Interfaces:**
- `StripeGateway.create_checkout_session(params)`, `create_portal_session(customer_id, return_url)`, `cancel_subscription(subscription_id, at_period_end)`, `create_refund(payment_intent_id, reason)`.
- `BillingStore.get_subject(user_id, product_code)`, `claim_provider_event(event)`, `process_provider_event(event, audit, outbox)`, `mark_provider_event_failed(...)`, `get_status(user_id)`, `get_subscription(user_id)`, `record_cancel(...)`, `get_refund_candidate(...)`, `create_refund_request(...)`, `get_refund_request(...)`, `mark_refund_succeeded(...)`, `mark_refund_retry(...)`, `append_audit(...)`.
- `BillingService.create_checkout(user_id, email, product_code, billing_region)` returns a provider session result plus price metadata.
- `BillingService.create_portal(user_id)` never accepts a client customer id or return URL.
- `BillingService.handle_webhook(raw_body, signature_header, now)` returns `WebhookResult(status, event_id, duplicate, ignored)` and raises typed public-safe errors.
- `BillingService.request_cancel(user_id)` uses period-end cancellation and is idempotent.
- `BillingService.request_refund(user_id, payment_intent_id, now)` enforces 48-hour unused window; `approve_refund(actor, request_id, reason, now)` requires `finance` role.
- `RetryPolicy(max_attempts=3, base_delay_seconds=5, max_delay_seconds=300)` schedules only transient failures.

- [ ] **Step 1: Write the failing tests** — use complete fakes (not mock-only assertions) to cover server price allowlist and customer reuse, payment/subscription mode and metadata, portal customer ownership, duplicate event processing exactly once, unsupported event acknowledgement, transient failure then replay, invoice paid/failed status changes, cancel-at-period-end idempotency, refund window/used rejection, finance-only approval, gateway retry state, and redacted audit metadata.
- [ ] **Step 2: Run the service test to verify it fails**

Run: `python3 -m pytest -q tests/billing/test_service.py`
Expected: FAIL because `BillingService` and its ports are absent.

- [ ] **Step 3: Implement minimal service and retry policy** — build Checkout params only from catalog/store/config; include `metadata.user_id`, subject id, product and price version; call `claim_provider_event` before any side effect; route the six supported event types; mark transient failures without exposing exception text; call gateway only after eligibility/role checks; sanitize audit values by key and email pattern.
- [ ] **Step 4: Run the service test to verify it passes**

Run: `python3 -m pytest -q tests/billing/test_service.py`
Expected: PASS and fake gateway call counts prove no duplicate provider side effects.

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/service.py backend/app/billing/ports.py tests/billing/conftest.py tests/billing/test_service.py
git commit -m "feat: add idempotent billing service boundary"
```

### Task 4: FastAPI Billing Routes and Safe Default

**Files:**
- Create: `backend/app/billing/routes.py`
- Modify: `backend/app/main.py`
- Test: `tests/billing/test_routes.py`

**Interfaces:**
- `get_billing_service()` raises `BillingNotConfigured` unless a caller/test explicitly overrides the dependency.
- `POST /api/billing/checkout` accepts only `product_code` and `billing_region`; returns session id/url and catalog metadata.
- `POST /api/billing/portal` returns a provider portal URL for the authenticated user.
- `GET /api/billing/status` returns server-owned subscription/payment state.
- `POST /api/billing/cancel` requests period-end cancellation.
- `POST /api/billing/refunds` creates a refund request; no client actor or approval role is trusted.
- `POST /api/billing/webhook` reads `await request.body()` exactly once and passes raw bytes plus `Stripe-Signature`; it has no `require_user` dependency.

- [ ] **Step 1: Write the failing tests** — assert disabled routes return 503, authenticated routes cannot inject `price_id`, `amount`, `currency`, customer id or URLs, webhook invalid signature returns 400 without store calls, valid fixture returns 200, duplicate returns 200, and transient processing returns 500 with a generic body.
- [ ] **Step 2: Run the route test to verify it fails**

Run: `python3 -m pytest -q tests/billing/test_routes.py`
Expected: FAIL because the router and dependency are absent.

- [ ] **Step 3: Implement minimal routes and include them in `app`** — map typed errors to 400/401/403/404/409/500/503 without raw exception text; never log or return the body, signature secret, email, or token.
- [ ] **Step 4: Run the route test to verify it passes**

Run: `python3 -m pytest -q tests/billing/test_routes.py`
Expected: PASS with fake service override and no network.

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/routes.py backend/app/main.py tests/billing/test_routes.py
git commit -m "feat: expose disabled-by-default billing routes"
```

### Task 5: Documentation, Configuration and Regression Verification

**Files:**
- Modify: `backend/README.md`
- Modify: `docs/supabase-setup.md`
- Test: all `tests/billing/*.py` plus existing backend tests

- [ ] **Step 1: Write the failing documentation/contract test** — assert README states `BILLING_ENABLED` is absent/false by default, no live keys or charges are used in tests, webhook raw-body/unique-event requirements, and migration baseline blocker remains explicit.
- [ ] **Step 2: Run the documentation test to verify it fails**

Run: `python3 -m pytest -q tests/billing/test_documentation.py`
Expected: FAIL because the safety/runbook text is absent.

- [ ] **Step 3: Update the runbooks** — document test fixture commands, future Stripe Dashboard checks, provider backup/restore and RLS/migration approvals as pre-production blockers; do not add secrets, URLs, or live commands.
- [ ] **Step 4: Run focused and offline regression checks**

Run:

```bash
python3 -m pytest -q tests/billing --confcutdir=tests/billing
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src
node --check web/app.js
python3 -m pytest -q
git diff --check
```

Expected: focused billing tests and available existing Python tests pass; if the environment lacks pytest/dependencies, report the exact command and failure instead of claiming success. No command may contact Stripe or a live database.

- [ ] **Step 5: Commit**

```bash
git add backend/README.md docs/supabase-setup.md tests/billing/test_documentation.py
git commit -m "docs: record offline billing safety gates"
```

## Self-Review Checklist

- Spec coverage: catalog/Checkout/Portal are Tasks 1 and 4; raw signature, event id uniqueness, supported events and retries are Tasks 2–3; cancel/refund/status/audit are Task 3; safety and blockers are Task 5.
- No physical billing migration is proposed while `reconciliation_required` remains active.
- No task trusts client `price_id`, amount, currency, customer id, role or redirect URL.
- No task stores or returns raw provider payload, signature, token, complete email or exception text.
- Retry limits and event status transitions are explicit and testable with deterministic clocks.
