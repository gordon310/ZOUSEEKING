# 付费用户闭环读取端点 A～D 报告

日期：2026-09-12

## A. 调查结论

| 项目 | 结论与证据 |
|---|---|
| `public.user_profiles` 会员列 | `user_id`、`membership_tier`、`daily_query_limit` 在 `backend/sql/supabase_user_profiles.sql:1-13`。客户端不能改会员字段：触发器 `prevent_client_membership_change` 在 `backend/sql/supabase_user_profiles.sql:37-62` 拒绝非 service role 修改。Stripe webhook 同步会员等级和每日额度，写入 `backend/app/billing/store.py:99-149`。 |
| 用量账本真实结构 | `usage_quotas` 是 `(scope_key, usage_kind, period_key)` 计数器，含 `limit_units/consumed_units/reserved_units`；`usage_events` 是追加事件账本，证据 `backend/app/usage/db_ledger.py:8-23` 和 `supabase/migrations/20260905000300_v1_usage_ledger.sql:35-71,81-133`。数据库计量种类是 `query/report/stats_query/export_row/subscription_slot`，见 `backend/app/usage/db_ledger.py:100-107`。当前新增读取按 `query`、`report`、`export_row` 汇总；原写端点仍为 `POST /api/usage/events`，但默认 provider 仍在 `backend/app/usage/routes.py:66-70` 返回 503。 |
| 计量口径 | 已用读取 `consumed_units`，没有把 reserved 当作已用；账本摘要原语明确返回 consumed/reserved/limit，见 `backend/app/usage/db_ledger.py:895-922`。规格要求查询成功一次计一次、成功报告计一次、导出按成功行数计量，见 `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md:171-188`。本批读取端点暂不返回事件明细，因此前端诚实显示“暂无事件明细”。 |
| 订阅落点和同步 | 订阅落在 `public.subscriptions`，个人订阅按 `user_id` 归属；schema 字段含 `product_code/status/current_period_end/cancel_at_period_end`，见 `supabase/migrations/20260905000200_v1_products_subscriptions.sql:91-128`。`payment_orders` 是支付订单/发票支付记录，不是订阅主表；支付订单定义见 `supabase/migrations/20260905000500_v1_finance_admin_audit.sql:35-63`。Stripe webhook 规则在 `backend/app/billing/store.py:495-508`：创建/更新 upsert 订阅，删除标记 canceled，invoice paid 恢复 active，payment failed 标记 past_due。 |
| 续费/取消如何反映 | `invoice.paid` 更新订阅状态为 active 并刷新权益，`backend/app/billing/store.py:957-974`；`invoice.payment_failed` 标记 past_due，`backend/app/billing/store.py:1011-1035`；删除事件标记 canceled 的设计说明在 `backend/app/billing/store.py:500-508`。新增读取会包含 canceled 记录，避免用户看见假空态。 |
| `pricing_plans` 字段与路径 | 表字段是 `monthly_query_limit`、`monthly_report_quota`、`subscription_slots`、`export_rows_monthly`，见 `supabase/migrations/20260912000100_pricing_admin.sql:37-48`。现有后台 catalog 从 `pricing_plans` 读取并映射成 `PlanDefinition`，见 `backend/app/billing/catalog.py:55-62,135-157`；新 member read store 同样按当前 `membership_tier` 读取这些字段，见 `backend/app/member/routes.py:64-97`。 |
| 现有 API 清单 | usage：`POST /api/usage/events`（`backend/app/usage/routes.py:93-117`）；billing：`GET /api/billing/prices`、`POST /checkout`、`POST /portal`、`GET /status`、`POST /cancel`、`POST /refunds`、`POST /webhook`（`backend/app/billing/routes.py:89-204`）。本批新增 `GET /api/me`、`GET /api/usage/summary`、`GET /api/billing/subscription`。 |

发现的文档/数据冲突：权威产品规格把 B Free 写为每月 30 次查询（`docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md:114-120`），但当前 seed 写入 `free` 为 3（`scripts/seed_pricing_catalog.py:28-32`），且 `membership_tier=free` 也沿用 3 的历史默认值。读取实现没有偷偷修正或伪造，直接读取当前 `pricing_plans`；应由后续产品/数据迁移决定哪个值生效。本批未执行迁移。

## B. 后端实现

- `GET /api/me`：只接受 `require_user` 的当前认证用户；返回 profile、当前 UTC+8 自然月额度和订阅摘要。缺表时返回 `available: false`，未知上限保留 `null`，无订阅返回 `subscription: null`。
- `GET /api/usage/summary`：返回当前自然月的 `period.key/start/end` 和 `queries/reports/exports_rows` 的 `used/limit`；未实现历史 `?period=`，因为当前读取契约只有当前月账本快照。
- `GET /api/billing/subscription`：复用现有 billing store 读取个人订阅，返回 `plan/status/current_period_end/cancel_at_period_end`；无订阅为 HTTP 200 + `null`。取消、逾期和续费状态由 webhook 镜像反映，不直接读 Stripe。

脱敏示例：

```json
{
  "available": true,
  "user_id": "00000000-0000-0000-0000-000000000030",
  "email": "member@example.com",
  "membership_tier": "c_plus",
  "entitlements": {
    "queries": {"used": 2, "limit": 100},
    "reports": {"used": 1, "limit": 12},
    "exports_rows": {"used": 0, "limit": 0}
  },
  "subscription": {
    "plan": "c_plus_monthly",
    "status": "active",
    "current_period_end": "2026-09-30T00:00:00+00:00",
    "cancel_at_period_end": false
  }
}
```

## C. 前端接线

- `web/js/business-api.js` 新增三个读取方法及订阅 checkout 方法。
- `web/usage.html` / `web/js/business-pages.js` 改为展示真实汇总、自然月起止和未配置上限；API 不可用时显示空态，不创建事件或额度夹具。
- `web/subscriptions.html` 改为真实 billing subscription 状态；无订阅显示“未订阅”和 `billing.html` 升级入口。统计条件订阅写入仍未实现，页面明确说明。
- `web/billing.html` 保留真实价格目录，当前套餐/订阅状态由 `/api/me` 和 `/api/billing/subscription` 提供；删除静态账单演示行，保留升级入口。
- `web/profile.html` / `web/app.js` 增加真实会员等级和本周期额度摘要；未登录或接口不可用显示明确空态。
- `web/js/i18n.js` 已同步中文、英文、日文动态文案。

## D. 测试与自检

新增用例：

- `tests/api/test_member_read_routes.py`：`/api/me`、`/api/usage/summary` 未登录 401；登录后结构；空订阅；不同用户不能读取 owner-scoped fake store。
- `tests/billing/test_routes.py`：`/api/billing/subscription` 登录结构、无订阅 200 + null、未登录 401。
- `tests/unit/test_member_read.py`：UTC+8 月边界，`2026-08-31 15:59:59Z` 属于 8 月，`16:00:00Z` 切到 9 月。

验证结果：

- `PYTHONPATH=. backend/.venv/bin/pytest tests/unit tests/api -q`：**323 passed, 83 skipped**。
- `PYTHONPATH=. backend/.venv/bin/pytest tests/billing/test_routes.py tests/billing/test_service.py tests/unit/test_billing_store.py -q`：**28 passed, 19 skipped**。
- `PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache backend/.venv/bin/python -m compileall -q backend/app tests/api tests/unit`：通过。
- `node --check web/app.js`、`web/js/business-api.js`、`web/js/business-pages.js`、`web/js/i18n.js`：全部通过。

未验证项：

- 没有连接真实 Postgres/Supabase，也没有执行 migration 或 seed；因此没有验证当前环境是否已落地 `user_profiles`、`pricing_plans`、`usage_quotas`、`subscriptions`。
- 没有连接 Stripe，也没有修改 Stripe 对象；真实续费/取消能否及时镜像仍依赖已部署 webhook、权限和数据表。
- 没有执行 Playwright 浏览器回归；本批完成的是静态 JS 语法和后端 API 测试。

`git status --short`（最终核对）：

```text
 M backend/app/billing/ports.py
 M backend/app/billing/routes.py
 M backend/app/billing/service.py
 M backend/app/billing/store.py
 M backend/app/main.py
 M backend/app/usage/routes.py
 M tests/billing/conftest.py
 M tests/billing/test_routes.py
 M web/app.js
 M web/billing.html
 M web/js/business-api.js
 M web/js/business-pages.js
 M web/js/i18n.js
 M web/profile.html
 M web/subscriptions.html
 M web/usage.html
?? backend/app/member/
?? docs/superpowers/reports/2026-09-12-paid-user-loop-task-report.md
?? tests/api/test_member_read_routes.py
?? tests/unit/test_member_read.py
```

本批没有 commit/push，也没有执行迁移。
