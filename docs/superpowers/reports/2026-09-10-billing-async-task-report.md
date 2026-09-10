# 支付接线批次 A：billing 层 async 化报告

日期：2026-09-10

## 改动摘要

- `backend/app/billing/ports.py`：StripeGateway 四个方法、BillingStore 全部方法改为 `async def`，数据类和常量未改。
- `backend/app/billing/service.py`：七个 public 方法改为 async；所有 store/gateway 调用加 `await`；同步的 `_event_side_effects` 保持不变。
- `backend/app/billing/routes.py`：checkout、portal、status、cancel、refunds、webhook 的 service 调用加 `await`；`get_billing_service` 未改。
- `tests/billing/conftest.py`：FakeGateway/FakeStore 的 Protocol 实现改为 async，构造和返回语义保持不变。
- `tests/billing/test_service.py`：service 调用用 `asyncio.run(...)` 包装；未添加依赖，未改 CI。

工作树中原有的未跟踪设计文档 `docs/superpowers/plans/2026-09-10-billing-rollout-design.md` 未修改；未提交、未建分支、未连接数据库或启动服务。

## 验证输出

### 1. 任务书原样 compileall 命令

命令：

```bash
PYTHONPATH=backend backend/.venv/bin/python -m compileall -q backend/app/billing/ports.py backend/app/billing/service.py backend/app/billing/routes.py tests/billing
```

结果：失败，退出码 1。环境将 pyc 写入受限路径 `/Users/gordonmac/Library/Caches/com.apple.python/...`，每个目标文件报告 `PermissionError: [Errno 1] Operation not permitted`。这不是源码语法错误。

### 1b. 使用仓库既有临时 pycache 方式重新验证

命令：

```bash
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache PYTHONPATH=backend backend/.venv/bin/python -m compileall -q backend/app/billing/ports.py backend/app/billing/service.py backend/app/billing/routes.py tests/billing
```

结果：通过，退出码 0，无输出。

### 2. 测试

命令：

```bash
backend/.venv/bin/python -m pytest tests/billing tests/unit -q
```

输出：

```
283 passed, 83 skipped in 2.61s
```

退出码：0。

### 3. git diff --stat

```
backend/app/billing/ports.py   | 36 ++++++++++++------------
 backend/app/billing/routes.py  | 12 ++++----
 backend/app/billing/service.py | 62 +++++++++++++++++++++---------------------
 tests/billing/conftest.py      | 36 ++++++++++++------------
 tests/billing/test_service.py  | 61 +++++++++++++++++++++--------------------
 5 files changed, 104 insertions(+), 103 deletions(-)
diff --git a/backend/app/billing/ports.py b/backend/app/billing/ports.py
index e28834e..30ace8e 100644
--- a/backend/app/billing/ports.py
+++ b/backend/app/billing/ports.py
@@ -116,32 +116,32 @@ class InternalActor:


 class StripeGateway(Protocol):
-    def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
+    async def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
         ...

-    def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
+    async def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
         ...

-    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
+    async def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
         ...

-    def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
+    async def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
         ...


 class BillingStore(Protocol):
     """Persistence boundary; production implementations must use one DB transaction."""

-    def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
+    async def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
         ...

-    def get_portal_subject(self, user_id: UUID) -> BillingSubject:
+    async def get_portal_subject(self, user_id: UUID) -> BillingSubject:
         ...

-    def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
+    async def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
         ...

-    def process_provider_event(
+    async def process_provider_event(
         self,
         event: ProviderEvent,
         audit: AuditRecord,
@@ -149,7 +149,7 @@ class BillingStore(Protocol):
     ) -> None:
         ...

-    def mark_provider_event_failed(
+    async def mark_provider_event_failed(
         self,
         event_id: str,
         *,
@@ -159,37 +159,37 @@ class BillingStore(Protocol):
     ) -> None:
         ...

-    def get_status(self, user_id: UUID) -> BillingStatus:
+    async def get_status(self, user_id: UUID) -> BillingStatus:
         ...

-    def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
+    async def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
         ...

-    def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
+    async def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
         ...

-    def get_refund_candidate(
+    async def get_refund_candidate(
         self, user_id: UUID, payment_intent_id: str
     ) -> Optional[RefundCandidate]:
         ...

-    def create_refund_request(
+    async def create_refund_request(
         self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
     ) -> RefundRequest:
         ...

-    def get_refund_request(self, request_id: str) -> RefundRequest:
+    async def get_refund_request(self, request_id: str) -> RefundRequest:
         ...

-    def mark_refund_succeeded(
+    async def mark_refund_succeeded(
         self, request_id: str, refund_id: str, completed_at: datetime
     ) -> None:
         ...

-    def mark_refund_retry(
+    async def mark_refund_retry(
         self, request_id: str, *, error_code: str, next_attempt_at: datetime
     ) -> None:
         ...

-    def append_audit(self, record: AuditRecord) -> None:
+    async def append_audit(self, record: AuditRecord) -> None:
         ...
diff --git a/backend/app/billing/routes.py b/backend/app/billing/routes.py
index 9fe4ac2..c672159 100644
--- a/backend/app/billing/routes.py
+++ b/backend/app/billing/routes.py
@@ -79,7 +79,7 @@ async def create_checkout(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        outcome = service.create_checkout(
+        outcome = await service.create_checkout(
             user.user_id,
             user.email,
             request.product_code,
@@ -105,7 +105,7 @@ async def create_portal(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, str]:
     try:
-        outcome = service.create_portal(user.user_id)
+        outcome = await service.create_portal(user.user_id)
     except BillingError as error:
         raise _http_error(error) from error
     return {"url": outcome.url}
@@ -117,7 +117,7 @@ async def get_status(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        return _status_payload(service.get_status(user.user_id))
+        return _status_payload(await service.get_status(user.user_id))
     except BillingError as error:
         raise _http_error(error) from error

@@ -128,7 +128,7 @@ async def cancel_subscription(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        outcome = service.request_cancel(user.user_id)
+        outcome = await service.request_cancel(user.user_id)
     except BillingError as error:
         raise _http_error(error) from error
     return {
@@ -145,7 +145,7 @@ async def request_refund(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        result = service.request_refund(
+        result = await service.request_refund(
             user.user_id,
             request.payment_intent_id,
             now=datetime.now(timezone.utc),
@@ -167,7 +167,7 @@ async def receive_webhook(
 ) -> dict[str, Any]:
     raw_body = await request.body()
     try:
-        result = service.handle_webhook(
+        result = await service.handle_webhook(
             raw_body,
             stripe_signature or "",
             now=datetime.now(timezone.utc),
diff --git a/backend/app/billing/service.py b/backend/app/billing/service.py
index 201cbad..4558020 100644
--- a/backend/app/billing/service.py
+++ b/backend/app/billing/service.py
@@ -181,7 +181,7 @@ class BillingService:
         self.portal_return_url = portal_return_url
         self.retry_policy = retry_policy or RetryPolicy()

-    def create_checkout(
+    async def create_checkout(
         self,
         user_id: UUID,
         email: str,
@@ -192,7 +192,7 @@ class BillingService:
     ) -> CheckoutOutcome:
         price = self.catalog.resolve(product_code, billing_region)
         try:
-            subject = self.store.get_subject(user_id, product_code)
+            subject = await self.store.get_subject(user_id, product_code)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc

@@ -223,12 +223,12 @@ class BillingService:
             params["customer_email"] = customer_email

         try:
-            result = self.gateway.create_checkout_session(params)
+            result = await self.gateway.create_checkout_session(params)
         except TransientBillingError:
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.append_audit(
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(subject.subject_id),
@@ -256,20 +256,20 @@ class BillingService:
             mode=price.mode,
         )

-    def create_portal(self, user_id: UUID) -> PortalOutcome:
+    async def create_portal(self, user_id: UUID) -> PortalOutcome:
         try:
-            subject = self.store.get_portal_subject(user_id)
+            subject = await self.store.get_portal_subject(user_id)
         except (AttributeError, KeyError, LookupError) as exc:
             raise BillingNotFound() from exc
         if not subject.stripe_customer_id:
             raise BillingConflict()
         try:
-            result = self.gateway.create_portal_session(subject.stripe_customer_id, self.portal_return_url)
+            result = await self.gateway.create_portal_session(subject.stripe_customer_id, self.portal_return_url)
         except TransientBillingError:
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.append_audit(
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(subject.subject_id),
@@ -283,15 +283,15 @@ class BillingService:
         )
         return PortalOutcome(result.url)

-    def get_status(self, user_id: UUID) -> BillingStatus:
+    async def get_status(self, user_id: UUID) -> BillingStatus:
         try:
-            return self.store.get_status(user_id)
+            return await self.store.get_status(user_id)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc

-    def request_cancel(self, user_id: UUID) -> CancelOutcome:
+    async def request_cancel(self, user_id: UUID) -> CancelOutcome:
         try:
-            subscription = self.store.get_subscription(user_id)
+            subscription = await self.store.get_subscription(user_id)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc
         if not subscription:
@@ -299,13 +299,13 @@ class BillingService:
         if subscription.cancel_at_period_end:
             return CancelOutcome(subscription.subscription_id, True, True)
         try:
-            self.gateway.cancel_subscription(subscription.subscription_id, at_period_end=True)
+            await self.gateway.cancel_subscription(subscription.subscription_id, at_period_end=True)
         except TransientBillingError:
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.record_cancel(user_id, at_period_end=True)
-        self.store.append_audit(
+        await self.store.record_cancel(user_id, at_period_end=True)
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(user_id),
@@ -319,9 +319,9 @@ class BillingService:
         )
         return CancelOutcome(subscription.subscription_id, True, False)

-    def request_refund(self, user_id: UUID, payment_intent_id: str, *, now: datetime) -> RefundRequest:
+    async def request_refund(self, user_id: UUID, payment_intent_id: str, *, now: datetime) -> RefundRequest:
         try:
-            candidate = self.store.get_refund_candidate(user_id, payment_intent_id)
+            candidate = await self.store.get_refund_candidate(user_id, payment_intent_id)
         except (KeyError, LookupError) as exc:
             raise RefundNotEligible() from exc
         if not candidate:
@@ -334,8 +334,8 @@ class BillingService:
             or candidate.used_entitlement
         ):
             raise RefundNotEligible()
-        request = self.store.create_refund_request(user_id, candidate, _as_utc(now))
-        self.store.append_audit(
+        request = await self.store.create_refund_request(user_id, candidate, _as_utc(now))
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(user_id),
@@ -349,7 +349,7 @@ class BillingService:
         )
         return request

-    def approve_refund(
+    async def approve_refund(
         self,
         actor: InternalActor,
         request_id: str,
@@ -360,22 +360,22 @@ class BillingService:
         if "finance" not in set(actor.roles):
             raise ForbiddenBillingOperation()
         try:
-            request = self.store.get_refund_request(request_id)
+            request = await self.store.get_refund_request(request_id)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc
         if request.status == "succeeded":
             return request
         try:
-            result = self.gateway.create_refund(request.payment_intent_id, reason=sanitize_reason(reason) or "approved")
+            result = await self.gateway.create_refund(request.payment_intent_id, reason=sanitize_reason(reason) or "approved")
         except TransientBillingError:
             retry_at = self.retry_policy.next_retry_at(1, now)
             if retry_at is not None:
-                self.store.mark_refund_retry(request_id, error_code="provider_transient", next_attempt_at=retry_at)
+                await self.store.mark_refund_retry(request_id, error_code="provider_transient", next_attempt_at=retry_at)
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.mark_refund_succeeded(request_id, result.refund_id, _as_utc(now))
-        self.store.append_audit(
+        await self.store.mark_refund_succeeded(request_id, result.refund_id, _as_utc(now))
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(actor.actor_id),
                 subject_id=None,
@@ -396,7 +396,7 @@ class BillingService:
             provider_refund_id=result.refund_id,
         )

-    def handle_webhook(
+    async def handle_webhook(
         self,
         raw_body: bytes,
         signature_header: str,
@@ -405,7 +405,7 @@ class BillingService:
     ) -> WebhookResult:
         event = construct_event(raw_body, signature_header, self.webhook_secret, now=_as_utc(now))
         try:
-            claim = self.store.claim_provider_event(event)
+            claim = await self.store.claim_provider_event(event)
         except TransientBillingError:
             raise
         except Exception as exc:
@@ -421,9 +421,9 @@ class BillingService:

         try:
             audit, outbox, ignored = self._event_side_effects(event)
-            self.store.process_provider_event(event, audit, outbox)
+            await self.store.process_provider_event(event, audit, outbox)
         except PermanentBillingError:
-            self.store.mark_provider_event_failed(
+            await self.store.mark_provider_event_failed(
                 event.event_id,
                 failure_class="permanent",
                 error_code="invalid_event",
@@ -432,7 +432,7 @@ class BillingService:
             raise
         except TransientBillingError:
             retry_at = self.retry_policy.next_retry_at(claim.attempt_count, _as_utc(now))
-            self.store.mark_provider_event_failed(
+            await self.store.mark_provider_event_failed(
                 event.event_id,
                 failure_class="transient" if retry_at is not None else "permanent",
                 error_code="event_processing_failed",
@@ -441,7 +441,7 @@ class BillingService:
             raise
         except Exception as exc:
             retry_at = self.retry_policy.next_retry_at(claim.attempt_count, _as_utc(now))
-            self.store.mark_provider_event_failed(
+            await self.store.mark_provider_event_failed(
                 event.event_id,
                 failure_class="transient" if retry_at is not None else "permanent",
                 error_code="event_processing_failed",
diff --git a/tests/billing/conftest.py b/tests/billing/conftest.py
index 93b53c5..490b53e 100644
--- a/tests/billing/conftest.py
+++ b/tests/billing/conftest.py
@@ -38,18 +38,18 @@ class FakeGateway:
         self.refund_calls: List[tuple[str, str]] = []
         self.fail_refund_once = False

-    def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
+    async def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
         self.checkout_calls.append(dict(params))
         return CheckoutSessionResult("cs_test_123", "https://checkout.test/session/cs_test_123")

-    def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
+    async def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
         self.portal_calls.append((customer_id, return_url))
         return PortalSessionResult("https://billing.test/session/bps_test_123")

-    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
+    async def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
         self.cancel_calls.append((subscription_id, at_period_end))

-    def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
+    async def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
         self.refund_calls.append((payment_intent_id, reason))
         if self.fail_refund_once:
             self.fail_refund_once = False
@@ -88,18 +88,18 @@ class FakeStore:
         self.refund_requests: Dict[str, RefundRequest] = {}
         self.refund_retries: List[Dict[str, Any]] = []

-    def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
+    async def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
         subject = self.subjects[product_code]
         if subject.subject_type == "user" and subject.subject_id != user_id:
             raise LookupError("subject not found")
         return subject

-    def get_portal_subject(self, user_id: UUID) -> BillingSubject:
+    async def get_portal_subject(self, user_id: UUID) -> BillingSubject:
         if self.portal_subject.subject_type == "user" and self.portal_subject.subject_id != user_id:
             raise LookupError("subject not found")
         return self.portal_subject

-    def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
+    async def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
         if self.fail_claim_once:
             self.fail_claim_once = False
             raise RuntimeError("database claim unavailable")
@@ -117,7 +117,7 @@ class FakeStore:
         self.events[event.event_id] = {"state": "in_progress", "attempt_count": 1}
         return EventClaim("new", 1)

-    def process_provider_event(
+    async def process_provider_event(
         self,
         event: ProviderEvent,
         audit: AuditRecord,
@@ -147,7 +147,7 @@ class FakeStore:
                 entitlement_active=str(event_object.get("status") or "") in {"active", "trialing"},
             )

-    def mark_provider_event_failed(
+    async def mark_provider_event_failed(
         self,
         event_id: str,
         *,
@@ -165,27 +165,27 @@ class FakeStore:
         )
         self.events[event_id]["state"] = "dead_letter" if failure_class == "permanent" else "failed"

-    def get_status(self, user_id: UUID) -> BillingStatus:
+    async def get_status(self, user_id: UUID) -> BillingStatus:
         if self.status.subject_id != user_id:
             raise LookupError("status not found")
         return self.status

-    def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
+    async def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
         if user_id != TEST_USER_ID:
             return None
         return self.subscription

-    def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
+    async def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
         self.subscription = replace(self.subscription, cancel_at_period_end=at_period_end)
         self.status = replace(self.status, cancel_at_period_end=at_period_end)

-    def get_refund_candidate(self, user_id: UUID, payment_intent_id: str) -> Optional[RefundCandidate]:
+    async def get_refund_candidate(self, user_id: UUID, payment_intent_id: str) -> Optional[RefundCandidate]:
         candidate = self.refund_candidates.get(payment_intent_id)
         if candidate and candidate.request_id.startswith(str(user_id)):
             return candidate
         return None

-    def create_refund_request(
+    async def create_refund_request(
         self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
     ) -> RefundRequest:
         existing = self.refund_requests.get(candidate.request_id)
@@ -195,19 +195,19 @@ class FakeStore:
         self.refund_requests[candidate.request_id] = request
         return request

-    def get_refund_request(self, request_id: str) -> RefundRequest:
+    async def get_refund_request(self, request_id: str) -> RefundRequest:
         return self.refund_requests[request_id]

-    def mark_refund_succeeded(self, request_id: str, refund_id: str, completed_at: datetime) -> None:
+    async def mark_refund_succeeded(self, request_id: str, refund_id: str, completed_at: datetime) -> None:
         current = self.refund_requests[request_id]
         self.refund_requests[request_id] = replace(current, status="succeeded", provider_refund_id=refund_id)

-    def mark_refund_retry(self, request_id: str, *, error_code: str, next_attempt_at: datetime) -> None:
+    async def mark_refund_retry(self, request_id: str, *, error_code: str, next_attempt_at: datetime) -> None:
         self.refund_retries.append(
             {"request_id": request_id, "error_code": error_code, "next_attempt_at": next_attempt_at}
         )

-    def append_audit(self, record: AuditRecord) -> None:
+    async def append_audit(self, record: AuditRecord) -> None:
         self.audits.append(record)


diff --git a/tests/billing/test_service.py b/tests/billing/test_service.py
index 29b30a6..1048610 100644
--- a/tests/billing/test_service.py
+++ b/tests/billing/test_service.py
@@ -3,6 +3,7 @@ from __future__ import annotations
 import hashlib
 import hmac
 import json
+import asyncio
 from datetime import timedelta

 import pytest
@@ -66,13 +67,13 @@ def billing_service(fake_gateway, fake_store) -> BillingService:
 def test_checkout_reuses_existing_customer_and_server_owned_subscription_metadata(
     billing_service, fake_gateway
 ) -> None:
-    result = billing_service.create_checkout(
+    result = asyncio.run(billing_service.create_checkout(
         TEST_USER_ID,
         "ignored@example.com",
         "c_plus_monthly",
         "JP",
         now=FIXED_NOW,
-    )
+    ))

     params = fake_gateway.checkout_calls[0]
     assert result.mode == "subscription"
@@ -92,13 +93,13 @@ def test_checkout_reuses_existing_customer_and_server_owned_subscription_metadat
 def test_checkout_uses_authenticated_email_only_when_customer_does_not_exist(
     billing_service, fake_gateway
 ) -> None:
-    result = billing_service.create_checkout(
+    result = asyncio.run(billing_service.create_checkout(
         TEST_USER_ID,
         "member@example.com",
         "risk_report_single",
         "CN",
         now=FIXED_NOW,
-    )
+    ))

     params = fake_gateway.checkout_calls[0]
     assert result.mode == "payment"
@@ -111,13 +112,13 @@ def test_checkout_cannot_select_an_unapproved_price_or_currency(
     billing_service,
 ) -> None:
     with pytest.raises(PriceUnavailable):
-        billing_service.create_checkout(TEST_USER_ID, "member@example.com", "unknown", "CN", now=FIXED_NOW)
+        asyncio.run(billing_service.create_checkout(TEST_USER_ID, "member@example.com", "unknown", "CN", now=FIXED_NOW))
     with pytest.raises(PriceUnavailable):
-        billing_service.create_checkout(TEST_USER_ID, "member@example.com", "c_plus_monthly", "HK", now=FIXED_NOW)
+        asyncio.run(billing_service.create_checkout(TEST_USER_ID, "member@example.com", "c_plus_monthly", "HK", now=FIXED_NOW))


 def test_portal_uses_store_owned_customer_and_return_url(billing_service, fake_gateway) -> None:
-    result = billing_service.create_portal(TEST_USER_ID)
+    result = asyncio.run(billing_service.create_portal(TEST_USER_ID))

     assert result.url.endswith("bps_test_123")
     assert fake_gateway.portal_calls == [("cus_existing", "https://app.test/billing")]
@@ -126,8 +127,8 @@ def test_portal_uses_store_owned_customer_and_return_url(billing_service, fake_g
 def test_webhook_duplicate_event_is_processed_once(billing_service, fake_store) -> None:
     body, header = signed_event("evt_duplicate", "invoice.paid", {"id": "in_123", "customer": "cus_existing"})

-    first = billing_service.handle_webhook(body, header, now=FIXED_NOW)
-    second = billing_service.handle_webhook(body, header, now=FIXED_NOW)
+    first = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))
+    second = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert (first.status, first.duplicate) == ("processed", False)
     assert (second.status, second.duplicate) == ("duplicate", True)
@@ -141,7 +142,7 @@ def test_webhook_in_progress_event_is_retryable_not_acknowledged(
     fake_store.events["evt_in_progress"] = {"state": "in_progress", "attempt_count": 1}

     with pytest.raises(TransientBillingError):
-        billing_service.handle_webhook(body, header, now=FIXED_NOW)
+        asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.processed_events == []
     assert fake_store.failed_events == []
@@ -153,7 +154,7 @@ def test_webhook_rejects_a_non_mapping_event_object_as_permanent(
     body, header = signed_event("evt_malformed_object", "invoice.paid", "not-an-object")

     with pytest.raises(PermanentBillingError):
-        billing_service.handle_webhook(body, header, now=FIXED_NOW)
+        asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.failed_events[0]["failure_class"] == "permanent"
     assert fake_store.processed_events == []
@@ -166,10 +167,10 @@ def test_webhook_transient_failure_is_recorded_and_replay_succeeds(
     body, header = signed_event("evt_retry", "invoice.paid", {"id": "in_retry", "customer": "cus_existing"})

     with pytest.raises(TransientBillingError):
-        billing_service.handle_webhook(body, header, now=FIXED_NOW)
+        asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.failed_events[0]["failure_class"] == "transient"
-    result = billing_service.handle_webhook(body, header, now=FIXED_NOW + timedelta(seconds=6))
+    result = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW + timedelta(seconds=6)))

     assert result.status == "processed"
     assert fake_store.processed_events == ["evt_retry"]
@@ -184,7 +185,7 @@ def test_failed_invoice_updates_status_and_enqueues_one_dunning_action(
         {"id": "in_failed", "customer": "cus_existing", "subscription": "sub_test_123"},
     )

-    billing_service.handle_webhook(body, header, now=FIXED_NOW)
+    asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.status.subscription_status == "past_due"
     assert fake_store.status.entitlement_active is False
@@ -198,7 +199,7 @@ def test_unknown_webhook_is_acknowledged_without_provider_side_effects(
 ) -> None:
     body, header = signed_event("evt_unknown", "product.created", {"id": "prod_123"})

-    result = billing_service.handle_webhook(body, header, now=FIXED_NOW)
+    result = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert (result.status, result.ignored) == ("ignored", True)
     assert fake_store.processed_events == ["evt_unknown"]
@@ -208,8 +209,8 @@ def test_unknown_webhook_is_acknowledged_without_provider_side_effects(
 def test_cancel_is_at_period_end_and_repeated_request_is_idempotent(
     billing_service, fake_gateway, fake_store
 ) -> None:
-    first = billing_service.request_cancel(TEST_USER_ID)
-    second = billing_service.request_cancel(TEST_USER_ID)
+    first = asyncio.run(billing_service.request_cancel(TEST_USER_ID))
+    second = asyncio.run(billing_service.request_cancel(TEST_USER_ID))

     assert first.at_period_end is True
     assert second.at_period_end is True
@@ -230,8 +231,8 @@ def test_refund_request_requires_unused_payment_within_48_hours(
         amount_minor=990,
     )

-    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
-    duplicate = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+    request = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))
+    duplicate = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))

     assert request.status == "requested"
     assert duplicate.request_id == request.request_id
@@ -258,7 +259,7 @@ def test_refund_request_rejects_expired_or_used_payment(
     )

     with pytest.raises(RefundNotEligible):
-        billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+        asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))


 def test_refund_request_rejects_a_payment_that_is_not_still_eligible(
@@ -276,7 +277,7 @@ def test_refund_request_rejects_a_payment_that_is_not_still_eligible(
     )

     with pytest.raises(RefundNotEligible):
-        billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+        asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))


 def test_refund_request_cannot_cross_user_ownership_boundary(billing_service, fake_store) -> None:
@@ -291,7 +292,7 @@ def test_refund_request_cannot_cross_user_ownership_boundary(billing_service, fa
     )

     with pytest.raises(RefundNotEligible):
-        billing_service.request_refund(OTHER_USER_ID, payment_id, now=FIXED_NOW)
+        asyncio.run(billing_service.request_refund(OTHER_USER_ID, payment_id, now=FIXED_NOW))


 def test_refund_approval_requires_finance_and_redacts_audit(
@@ -306,16 +307,16 @@ def test_refund_approval_requires_finance_and_redacts_audit(
         currency="JPY",
         amount_minor=990,
     )
-    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+    request = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))

     with pytest.raises(ForbiddenBillingOperation):
-        billing_service.approve_refund(
+        asyncio.run(billing_service.approve_refund(
             InternalActor(TEST_USER_ID, ("member",)), request.request_id, "member@example.com duplicate", now=FIXED_NOW
-        )
+        ))

-    approved = billing_service.approve_refund(
+    approved = asyncio.run(billing_service.approve_refund(
         InternalActor(TEST_USER_ID, ("finance",)), request.request_id, "member@example.com duplicate", now=FIXED_NOW
-    )
+    ))

     assert approved.status == "succeeded"
     assert fake_gateway.refund_calls == [(payment_id, "[redacted-email] duplicate")]
@@ -334,13 +335,13 @@ def test_refund_provider_timeout_is_retryable_without_premature_success(
         currency="JPY",
         amount_minor=990,
     )
-    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+    request = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))
     fake_gateway.fail_refund_once = True

     with pytest.raises(TransientBillingError):
-        billing_service.approve_refund(
+        asyncio.run(billing_service.approve_refund(
             InternalActor(TEST_USER_ID, ("finance",)), request.request_id, "duplicate", now=FIXED_NOW
-        )
+        ))

     assert fake_store.refund_requests[request.request_id].status == "requested"
     assert len(fake_store.refund_retries) == 1
```

## git diff

```diff
 backend/app/billing/ports.py   | 36 ++++++++++++------------
 backend/app/billing/routes.py  | 12 ++++----
 backend/app/billing/service.py | 62 +++++++++++++++++++++---------------------
 tests/billing/conftest.py      | 36 ++++++++++++------------
 tests/billing/test_service.py  | 61 +++++++++++++++++++++--------------------
 5 files changed, 104 insertions(+), 103 deletions(-)
diff --git a/backend/app/billing/ports.py b/backend/app/billing/ports.py
index e28834e..30ace8e 100644
--- a/backend/app/billing/ports.py
+++ b/backend/app/billing/ports.py
@@ -116,32 +116,32 @@ class InternalActor:


 class StripeGateway(Protocol):
-    def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
+    async def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
         ...

-    def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
+    async def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
         ...

-    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
+    async def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
         ...

-    def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
+    async def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
         ...


 class BillingStore(Protocol):
     """Persistence boundary; production implementations must use one DB transaction."""

-    def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
+    async def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
         ...

-    def get_portal_subject(self, user_id: UUID) -> BillingSubject:
+    async def get_portal_subject(self, user_id: UUID) -> BillingSubject:
         ...

-    def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
+    async def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
         ...

-    def process_provider_event(
+    async def process_provider_event(
         self,
         event: ProviderEvent,
         audit: AuditRecord,
@@ -149,7 +149,7 @@ class BillingStore(Protocol):
     ) -> None:
         ...

-    def mark_provider_event_failed(
+    async def mark_provider_event_failed(
         self,
         event_id: str,
         *,
@@ -159,37 +159,37 @@ class BillingStore(Protocol):
     ) -> None:
         ...

-    def get_status(self, user_id: UUID) -> BillingStatus:
+    async def get_status(self, user_id: UUID) -> BillingStatus:
         ...

-    def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
+    async def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
         ...

-    def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
+    async def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
         ...

-    def get_refund_candidate(
+    async def get_refund_candidate(
         self, user_id: UUID, payment_intent_id: str
     ) -> Optional[RefundCandidate]:
         ...

-    def create_refund_request(
+    async def create_refund_request(
         self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
     ) -> RefundRequest:
         ...

-    def get_refund_request(self, request_id: str) -> RefundRequest:
+    async def get_refund_request(self, request_id: str) -> RefundRequest:
         ...

-    def mark_refund_succeeded(
+    async def mark_refund_succeeded(
         self, request_id: str, refund_id: str, completed_at: datetime
     ) -> None:
         ...

-    def mark_refund_retry(
+    async def mark_refund_retry(
         self, request_id: str, *, error_code: str, next_attempt_at: datetime
     ) -> None:
         ...

-    def append_audit(self, record: AuditRecord) -> None:
+    async def append_audit(self, record: AuditRecord) -> None:
         ...
diff --git a/backend/app/billing/routes.py b/backend/app/billing/routes.py
index 9fe4ac2..c672159 100644
--- a/backend/app/billing/routes.py
+++ b/backend/app/billing/routes.py
@@ -79,7 +79,7 @@ async def create_checkout(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        outcome = service.create_checkout(
+        outcome = await service.create_checkout(
             user.user_id,
             user.email,
             request.product_code,
@@ -105,7 +105,7 @@ async def create_portal(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, str]:
     try:
-        outcome = service.create_portal(user.user_id)
+        outcome = await service.create_portal(user.user_id)
     except BillingError as error:
         raise _http_error(error) from error
     return {"url": outcome.url}
@@ -117,7 +117,7 @@ async def get_status(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        return _status_payload(service.get_status(user.user_id))
+        return _status_payload(await service.get_status(user.user_id))
     except BillingError as error:
         raise _http_error(error) from error

@@ -128,7 +128,7 @@ async def cancel_subscription(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        outcome = service.request_cancel(user.user_id)
+        outcome = await service.request_cancel(user.user_id)
     except BillingError as error:
         raise _http_error(error) from error
     return {
@@ -145,7 +145,7 @@ async def request_refund(
     service: BillingService = Depends(get_billing_service),
 ) -> dict[str, Any]:
     try:
-        result = service.request_refund(
+        result = await service.request_refund(
             user.user_id,
             request.payment_intent_id,
             now=datetime.now(timezone.utc),
@@ -167,7 +167,7 @@ async def receive_webhook(
 ) -> dict[str, Any]:
     raw_body = await request.body()
     try:
-        result = service.handle_webhook(
+        result = await service.handle_webhook(
             raw_body,
             stripe_signature or "",
             now=datetime.now(timezone.utc),
diff --git a/backend/app/billing/service.py b/backend/app/billing/service.py
index 201cbad..4558020 100644
--- a/backend/app/billing/service.py
+++ b/backend/app/billing/service.py
@@ -181,7 +181,7 @@ class BillingService:
         self.portal_return_url = portal_return_url
         self.retry_policy = retry_policy or RetryPolicy()

-    def create_checkout(
+    async def create_checkout(
         self,
         user_id: UUID,
         email: str,
@@ -192,7 +192,7 @@ class BillingService:
     ) -> CheckoutOutcome:
         price = self.catalog.resolve(product_code, billing_region)
         try:
-            subject = self.store.get_subject(user_id, product_code)
+            subject = await self.store.get_subject(user_id, product_code)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc

@@ -223,12 +223,12 @@ class BillingService:
             params["customer_email"] = customer_email

         try:
-            result = self.gateway.create_checkout_session(params)
+            result = await self.gateway.create_checkout_session(params)
         except TransientBillingError:
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.append_audit(
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(subject.subject_id),
@@ -256,20 +256,20 @@ class BillingService:
             mode=price.mode,
         )

-    def create_portal(self, user_id: UUID) -> PortalOutcome:
+    async def create_portal(self, user_id: UUID) -> PortalOutcome:
         try:
-            subject = self.store.get_portal_subject(user_id)
+            subject = await self.store.get_portal_subject(user_id)
         except (AttributeError, KeyError, LookupError) as exc:
             raise BillingNotFound() from exc
         if not subject.stripe_customer_id:
             raise BillingConflict()
         try:
-            result = self.gateway.create_portal_session(subject.stripe_customer_id, self.portal_return_url)
+            result = await self.gateway.create_portal_session(subject.stripe_customer_id, self.portal_return_url)
         except TransientBillingError:
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.append_audit(
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(subject.subject_id),
@@ -283,15 +283,15 @@ class BillingService:
         )
         return PortalOutcome(result.url)

-    def get_status(self, user_id: UUID) -> BillingStatus:
+    async def get_status(self, user_id: UUID) -> BillingStatus:
         try:
-            return self.store.get_status(user_id)
+            return await self.store.get_status(user_id)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc

-    def request_cancel(self, user_id: UUID) -> CancelOutcome:
+    async def request_cancel(self, user_id: UUID) -> CancelOutcome:
         try:
-            subscription = self.store.get_subscription(user_id)
+            subscription = await self.store.get_subscription(user_id)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc
         if not subscription:
@@ -299,13 +299,13 @@ class BillingService:
         if subscription.cancel_at_period_end:
             return CancelOutcome(subscription.subscription_id, True, True)
         try:
-            self.gateway.cancel_subscription(subscription.subscription_id, at_period_end=True)
+            await self.gateway.cancel_subscription(subscription.subscription_id, at_period_end=True)
         except TransientBillingError:
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.record_cancel(user_id, at_period_end=True)
-        self.store.append_audit(
+        await self.store.record_cancel(user_id, at_period_end=True)
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(user_id),
@@ -319,9 +319,9 @@ class BillingService:
         )
         return CancelOutcome(subscription.subscription_id, True, False)

-    def request_refund(self, user_id: UUID, payment_intent_id: str, *, now: datetime) -> RefundRequest:
+    async def request_refund(self, user_id: UUID, payment_intent_id: str, *, now: datetime) -> RefundRequest:
         try:
-            candidate = self.store.get_refund_candidate(user_id, payment_intent_id)
+            candidate = await self.store.get_refund_candidate(user_id, payment_intent_id)
         except (KeyError, LookupError) as exc:
             raise RefundNotEligible() from exc
         if not candidate:
@@ -334,8 +334,8 @@ class BillingService:
             or candidate.used_entitlement
         ):
             raise RefundNotEligible()
-        request = self.store.create_refund_request(user_id, candidate, _as_utc(now))
-        self.store.append_audit(
+        request = await self.store.create_refund_request(user_id, candidate, _as_utc(now))
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(user_id),
                 subject_id=str(user_id),
@@ -349,7 +349,7 @@ class BillingService:
         )
         return request

-    def approve_refund(
+    async def approve_refund(
         self,
         actor: InternalActor,
         request_id: str,
@@ -360,22 +360,22 @@ class BillingService:
         if "finance" not in set(actor.roles):
             raise ForbiddenBillingOperation()
         try:
-            request = self.store.get_refund_request(request_id)
+            request = await self.store.get_refund_request(request_id)
         except (KeyError, LookupError) as exc:
             raise BillingNotFound() from exc
         if request.status == "succeeded":
             return request
         try:
-            result = self.gateway.create_refund(request.payment_intent_id, reason=sanitize_reason(reason) or "approved")
+            result = await self.gateway.create_refund(request.payment_intent_id, reason=sanitize_reason(reason) or "approved")
         except TransientBillingError:
             retry_at = self.retry_policy.next_retry_at(1, now)
             if retry_at is not None:
-                self.store.mark_refund_retry(request_id, error_code="provider_transient", next_attempt_at=retry_at)
+                await self.store.mark_refund_retry(request_id, error_code="provider_transient", next_attempt_at=retry_at)
             raise
         except Exception as exc:
             raise TransientBillingError() from exc
-        self.store.mark_refund_succeeded(request_id, result.refund_id, _as_utc(now))
-        self.store.append_audit(
+        await self.store.mark_refund_succeeded(request_id, result.refund_id, _as_utc(now))
+        await self.store.append_audit(
             AuditRecord(
                 actor_id=str(actor.actor_id),
                 subject_id=None,
@@ -396,7 +396,7 @@ class BillingService:
             provider_refund_id=result.refund_id,
         )

-    def handle_webhook(
+    async def handle_webhook(
         self,
         raw_body: bytes,
         signature_header: str,
@@ -405,7 +405,7 @@ class BillingService:
     ) -> WebhookResult:
         event = construct_event(raw_body, signature_header, self.webhook_secret, now=_as_utc(now))
         try:
-            claim = self.store.claim_provider_event(event)
+            claim = await self.store.claim_provider_event(event)
         except TransientBillingError:
             raise
         except Exception as exc:
@@ -421,9 +421,9 @@ class BillingService:

         try:
             audit, outbox, ignored = self._event_side_effects(event)
-            self.store.process_provider_event(event, audit, outbox)
+            await self.store.process_provider_event(event, audit, outbox)
         except PermanentBillingError:
-            self.store.mark_provider_event_failed(
+            await self.store.mark_provider_event_failed(
                 event.event_id,
                 failure_class="permanent",
                 error_code="invalid_event",
@@ -432,7 +432,7 @@ class BillingService:
             raise
         except TransientBillingError:
             retry_at = self.retry_policy.next_retry_at(claim.attempt_count, _as_utc(now))
-            self.store.mark_provider_event_failed(
+            await self.store.mark_provider_event_failed(
                 event.event_id,
                 failure_class="transient" if retry_at is not None else "permanent",
                 error_code="event_processing_failed",
@@ -441,7 +441,7 @@ class BillingService:
             raise
         except Exception as exc:
             retry_at = self.retry_policy.next_retry_at(claim.attempt_count, _as_utc(now))
-            self.store.mark_provider_event_failed(
+            await self.store.mark_provider_event_failed(
                 event.event_id,
                 failure_class="transient" if retry_at is not None else "permanent",
                 error_code="event_processing_failed",
diff --git a/tests/billing/conftest.py b/tests/billing/conftest.py
index 93b53c5..490b53e 100644
--- a/tests/billing/conftest.py
+++ b/tests/billing/conftest.py
@@ -38,18 +38,18 @@ class FakeGateway:
         self.refund_calls: List[tuple[str, str]] = []
         self.fail_refund_once = False

-    def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
+    async def create_checkout_session(self, params: Mapping[str, Any]) -> CheckoutSessionResult:
         self.checkout_calls.append(dict(params))
         return CheckoutSessionResult("cs_test_123", "https://checkout.test/session/cs_test_123")

-    def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
+    async def create_portal_session(self, customer_id: str, return_url: str) -> PortalSessionResult:
         self.portal_calls.append((customer_id, return_url))
         return PortalSessionResult("https://billing.test/session/bps_test_123")

-    def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
+    async def cancel_subscription(self, subscription_id: str, *, at_period_end: bool) -> None:
         self.cancel_calls.append((subscription_id, at_period_end))

-    def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
+    async def create_refund(self, payment_intent_id: str, *, reason: str) -> RefundResult:
         self.refund_calls.append((payment_intent_id, reason))
         if self.fail_refund_once:
             self.fail_refund_once = False
@@ -88,18 +88,18 @@ class FakeStore:
         self.refund_requests: Dict[str, RefundRequest] = {}
         self.refund_retries: List[Dict[str, Any]] = []

-    def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
+    async def get_subject(self, user_id: UUID, product_code: str) -> BillingSubject:
         subject = self.subjects[product_code]
         if subject.subject_type == "user" and subject.subject_id != user_id:
             raise LookupError("subject not found")
         return subject

-    def get_portal_subject(self, user_id: UUID) -> BillingSubject:
+    async def get_portal_subject(self, user_id: UUID) -> BillingSubject:
         if self.portal_subject.subject_type == "user" and self.portal_subject.subject_id != user_id:
             raise LookupError("subject not found")
         return self.portal_subject

-    def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
+    async def claim_provider_event(self, event: ProviderEvent) -> EventClaim:
         if self.fail_claim_once:
             self.fail_claim_once = False
             raise RuntimeError("database claim unavailable")
@@ -117,7 +117,7 @@ class FakeStore:
         self.events[event.event_id] = {"state": "in_progress", "attempt_count": 1}
         return EventClaim("new", 1)

-    def process_provider_event(
+    async def process_provider_event(
         self,
         event: ProviderEvent,
         audit: AuditRecord,
@@ -147,7 +147,7 @@ class FakeStore:
                 entitlement_active=str(event_object.get("status") or "") in {"active", "trialing"},
             )

-    def mark_provider_event_failed(
+    async def mark_provider_event_failed(
         self,
         event_id: str,
         *,
@@ -165,27 +165,27 @@ class FakeStore:
         )
         self.events[event_id]["state"] = "dead_letter" if failure_class == "permanent" else "failed"

-    def get_status(self, user_id: UUID) -> BillingStatus:
+    async def get_status(self, user_id: UUID) -> BillingStatus:
         if self.status.subject_id != user_id:
             raise LookupError("status not found")
         return self.status

-    def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
+    async def get_subscription(self, user_id: UUID) -> Optional[SubscriptionSnapshot]:
         if user_id != TEST_USER_ID:
             return None
         return self.subscription

-    def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
+    async def record_cancel(self, user_id: UUID, *, at_period_end: bool) -> None:
         self.subscription = replace(self.subscription, cancel_at_period_end=at_period_end)
         self.status = replace(self.status, cancel_at_period_end=at_period_end)

-    def get_refund_candidate(self, user_id: UUID, payment_intent_id: str) -> Optional[RefundCandidate]:
+    async def get_refund_candidate(self, user_id: UUID, payment_intent_id: str) -> Optional[RefundCandidate]:
         candidate = self.refund_candidates.get(payment_intent_id)
         if candidate and candidate.request_id.startswith(str(user_id)):
             return candidate
         return None

-    def create_refund_request(
+    async def create_refund_request(
         self, user_id: UUID, candidate: RefundCandidate, requested_at: datetime
     ) -> RefundRequest:
         existing = self.refund_requests.get(candidate.request_id)
@@ -195,19 +195,19 @@ class FakeStore:
         self.refund_requests[candidate.request_id] = request
         return request

-    def get_refund_request(self, request_id: str) -> RefundRequest:
+    async def get_refund_request(self, request_id: str) -> RefundRequest:
         return self.refund_requests[request_id]

-    def mark_refund_succeeded(self, request_id: str, refund_id: str, completed_at: datetime) -> None:
+    async def mark_refund_succeeded(self, request_id: str, refund_id: str, completed_at: datetime) -> None:
         current = self.refund_requests[request_id]
         self.refund_requests[request_id] = replace(current, status="succeeded", provider_refund_id=refund_id)

-    def mark_refund_retry(self, request_id: str, *, error_code: str, next_attempt_at: datetime) -> None:
+    async def mark_refund_retry(self, request_id: str, *, error_code: str, next_attempt_at: datetime) -> None:
         self.refund_retries.append(
             {"request_id": request_id, "error_code": error_code, "next_attempt_at": next_attempt_at}
         )

-    def append_audit(self, record: AuditRecord) -> None:
+    async def append_audit(self, record: AuditRecord) -> None:
         self.audits.append(record)


diff --git a/tests/billing/test_service.py b/tests/billing/test_service.py
index 29b30a6..1048610 100644
--- a/tests/billing/test_service.py
+++ b/tests/billing/test_service.py
@@ -3,6 +3,7 @@ from __future__ import annotations
 import hashlib
 import hmac
 import json
+import asyncio
 from datetime import timedelta

 import pytest
@@ -66,13 +67,13 @@ def billing_service(fake_gateway, fake_store) -> BillingService:
 def test_checkout_reuses_existing_customer_and_server_owned_subscription_metadata(
     billing_service, fake_gateway
 ) -> None:
-    result = billing_service.create_checkout(
+    result = asyncio.run(billing_service.create_checkout(
         TEST_USER_ID,
         "ignored@example.com",
         "c_plus_monthly",
         "JP",
         now=FIXED_NOW,
-    )
+    ))

     params = fake_gateway.checkout_calls[0]
     assert result.mode == "subscription"
@@ -92,13 +93,13 @@ def test_checkout_reuses_existing_customer_and_server_owned_subscription_metadat
 def test_checkout_uses_authenticated_email_only_when_customer_does_not_exist(
     billing_service, fake_gateway
 ) -> None:
-    result = billing_service.create_checkout(
+    result = asyncio.run(billing_service.create_checkout(
         TEST_USER_ID,
         "member@example.com",
         "risk_report_single",
         "CN",
         now=FIXED_NOW,
-    )
+    ))

     params = fake_gateway.checkout_calls[0]
     assert result.mode == "payment"
@@ -111,13 +112,13 @@ def test_checkout_cannot_select_an_unapproved_price_or_currency(
     billing_service,
 ) -> None:
     with pytest.raises(PriceUnavailable):
-        billing_service.create_checkout(TEST_USER_ID, "member@example.com", "unknown", "CN", now=FIXED_NOW)
+        asyncio.run(billing_service.create_checkout(TEST_USER_ID, "member@example.com", "unknown", "CN", now=FIXED_NOW))
     with pytest.raises(PriceUnavailable):
-        billing_service.create_checkout(TEST_USER_ID, "member@example.com", "c_plus_monthly", "HK", now=FIXED_NOW)
+        asyncio.run(billing_service.create_checkout(TEST_USER_ID, "member@example.com", "c_plus_monthly", "HK", now=FIXED_NOW))


 def test_portal_uses_store_owned_customer_and_return_url(billing_service, fake_gateway) -> None:
-    result = billing_service.create_portal(TEST_USER_ID)
+    result = asyncio.run(billing_service.create_portal(TEST_USER_ID))

     assert result.url.endswith("bps_test_123")
     assert fake_gateway.portal_calls == [("cus_existing", "https://app.test/billing")]
@@ -126,8 +127,8 @@ def test_portal_uses_store_owned_customer_and_return_url(billing_service, fake_g
 def test_webhook_duplicate_event_is_processed_once(billing_service, fake_store) -> None:
     body, header = signed_event("evt_duplicate", "invoice.paid", {"id": "in_123", "customer": "cus_existing"})

-    first = billing_service.handle_webhook(body, header, now=FIXED_NOW)
-    second = billing_service.handle_webhook(body, header, now=FIXED_NOW)
+    first = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))
+    second = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert (first.status, first.duplicate) == ("processed", False)
     assert (second.status, second.duplicate) == ("duplicate", True)
@@ -141,7 +142,7 @@ def test_webhook_in_progress_event_is_retryable_not_acknowledged(
     fake_store.events["evt_in_progress"] = {"state": "in_progress", "attempt_count": 1}

     with pytest.raises(TransientBillingError):
-        billing_service.handle_webhook(body, header, now=FIXED_NOW)
+        asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.processed_events == []
     assert fake_store.failed_events == []
@@ -153,7 +154,7 @@ def test_webhook_rejects_a_non_mapping_event_object_as_permanent(
     body, header = signed_event("evt_malformed_object", "invoice.paid", "not-an-object")

     with pytest.raises(PermanentBillingError):
-        billing_service.handle_webhook(body, header, now=FIXED_NOW)
+        asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.failed_events[0]["failure_class"] == "permanent"
     assert fake_store.processed_events == []
@@ -166,10 +167,10 @@ def test_webhook_transient_failure_is_recorded_and_replay_succeeds(
     body, header = signed_event("evt_retry", "invoice.paid", {"id": "in_retry", "customer": "cus_existing"})

     with pytest.raises(TransientBillingError):
-        billing_service.handle_webhook(body, header, now=FIXED_NOW)
+        asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.failed_events[0]["failure_class"] == "transient"
-    result = billing_service.handle_webhook(body, header, now=FIXED_NOW + timedelta(seconds=6))
+    result = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW + timedelta(seconds=6)))

     assert result.status == "processed"
     assert fake_store.processed_events == ["evt_retry"]
@@ -184,7 +185,7 @@ def test_failed_invoice_updates_status_and_enqueues_one_dunning_action(
         {"id": "in_failed", "customer": "cus_existing", "subscription": "sub_test_123"},
     )

-    billing_service.handle_webhook(body, header, now=FIXED_NOW)
+    asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert fake_store.status.subscription_status == "past_due"
     assert fake_store.status.entitlement_active is False
@@ -198,7 +199,7 @@ def test_unknown_webhook_is_acknowledged_without_provider_side_effects(
 ) -> None:
     body, header = signed_event("evt_unknown", "product.created", {"id": "prod_123"})

-    result = billing_service.handle_webhook(body, header, now=FIXED_NOW)
+    result = asyncio.run(billing_service.handle_webhook(body, header, now=FIXED_NOW))

     assert (result.status, result.ignored) == ("ignored", True)
     assert fake_store.processed_events == ["evt_unknown"]
@@ -208,8 +209,8 @@ def test_unknown_webhook_is_acknowledged_without_provider_side_effects(
 def test_cancel_is_at_period_end_and_repeated_request_is_idempotent(
     billing_service, fake_gateway, fake_store
 ) -> None:
-    first = billing_service.request_cancel(TEST_USER_ID)
-    second = billing_service.request_cancel(TEST_USER_ID)
+    first = asyncio.run(billing_service.request_cancel(TEST_USER_ID))
+    second = asyncio.run(billing_service.request_cancel(TEST_USER_ID))

     assert first.at_period_end is True
     assert second.at_period_end is True
@@ -230,8 +231,8 @@ def test_refund_request_requires_unused_payment_within_48_hours(
         amount_minor=990,
     )

-    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
-    duplicate = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+    request = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))
+    duplicate = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))

     assert request.status == "requested"
     assert duplicate.request_id == request.request_id
@@ -258,7 +259,7 @@ def test_refund_request_rejects_expired_or_used_payment(
     )

     with pytest.raises(RefundNotEligible):
-        billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+        asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))


 def test_refund_request_rejects_a_payment_that_is_not_still_eligible(
@@ -276,7 +277,7 @@ def test_refund_request_rejects_a_payment_that_is_not_still_eligible(
     )

     with pytest.raises(RefundNotEligible):
-        billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+        asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))


 def test_refund_request_cannot_cross_user_ownership_boundary(billing_service, fake_store) -> None:
@@ -291,7 +292,7 @@ def test_refund_request_cannot_cross_user_ownership_boundary(billing_service, fa
     )

     with pytest.raises(RefundNotEligible):
-        billing_service.request_refund(OTHER_USER_ID, payment_id, now=FIXED_NOW)
+        asyncio.run(billing_service.request_refund(OTHER_USER_ID, payment_id, now=FIXED_NOW))


 def test_refund_approval_requires_finance_and_redacts_audit(
@@ -306,16 +307,16 @@ def test_refund_approval_requires_finance_and_redacts_audit(
         currency="JPY",
         amount_minor=990,
     )
-    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+    request = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))

     with pytest.raises(ForbiddenBillingOperation):
-        billing_service.approve_refund(
+        asyncio.run(billing_service.approve_refund(
             InternalActor(TEST_USER_ID, ("member",)), request.request_id, "member@example.com duplicate", now=FIXED_NOW
-        )
+        ))

-    approved = billing_service.approve_refund(
+    approved = asyncio.run(billing_service.approve_refund(
         InternalActor(TEST_USER_ID, ("finance",)), request.request_id, "member@example.com duplicate", now=FIXED_NOW
-    )
+    ))

     assert approved.status == "succeeded"
     assert fake_gateway.refund_calls == [(payment_id, "[redacted-email] duplicate")]
@@ -334,13 +335,13 @@ def test_refund_provider_timeout_is_retryable_without_premature_success(
         currency="JPY",
         amount_minor=990,
     )
-    request = billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW)
+    request = asyncio.run(billing_service.request_refund(TEST_USER_ID, payment_id, now=FIXED_NOW))
     fake_gateway.fail_refund_once = True

     with pytest.raises(TransientBillingError):
-        billing_service.approve_refund(
+        asyncio.run(billing_service.approve_refund(
             InternalActor(TEST_USER_ID, ("finance",)), request.request_id, "duplicate", now=FIXED_NOW
-        )
+        ))

     assert fake_store.refund_requests[request.request_id].status == "requested"
     assert len(fake_store.refund_retries) == 1

```
