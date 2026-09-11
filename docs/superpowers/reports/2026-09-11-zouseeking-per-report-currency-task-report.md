# 按份报告购买、订阅权益与六币种区域支持自检报告

日期：2026-09-11

## A. 币种与区域

- `backend/app/billing/catalog.py` 已补齐 9 条 TWD/HKD/SGD 本地价格：单份 TWD 3000、HKD 800、SGD 150；C Plus TWD 30000、HKD 8000、SGD 1500；B Data Pro TWD 120000、HKD 32000、SGD 6000，均为最小货币单位。
- `TW/HK/SG` 已映射到 `TWD/HKD/SGD`；`MO` 暂映射 `HKD`，代码注释说明澳门常用港币，MOP 留待后续价格版本。
- 保留服务端按账单地区选币、禁止前端汇率换算的原则。
- `.env.example` 与 `deploy/.env.example` 已给出不含真实 ID 的 18 条 `STRIPE_PRICE_IDS` 示例。

## B. 按报告购买

- 新增 forward migration：`supabase/migrations/20260911000100_report_purchase_subject.sql`，只添加 `payment_orders.subject_id` 和查询索引，未执行迁移。
- 单份 checkout 要求 `query_key`，Stripe metadata、`client_reference_id`、订单 `subject_id` 都使用当前报告标识；订阅 checkout 仍使用原有账户/机构 subject。
- `_has_report_unlock(conn, user_id, report_key)` 现在只匹配该报告的已付单份订单。旧订单的 `subject_id` 为空，因而不会解锁新报告，也未删除任何旧数据。
- C Plus 有效且当月额度未耗尽时可解锁；额度耗尽后继续显示单份购买入口。
- 前端单份 checkout 携带 `query_key`，锁态文案改为“购买后解锁本份深度报告”，完整报告显示“已解锁”徽标；中英日 i18n 均已补齐。

## C. 调查结论与闭环

| 调查项 | 现状证据 | 缺口 | 本次已实现 | 仍未实现/限制 |
| --- | --- | --- | --- | --- |
| 用量计量 | `backend/app/usage/ledger.py:18-148` 有 UTC+8 日/月周期和 `report` 类型；`backend/app/usage/db_ledger.py:8-41` 有原子 quota/event/idempotency 设计。 | `backend/app/usage/routes.py:66-69` 的服务注入仍返回 503，通用用量 API 尚未接线。 | 报告生成对 C Plus 写入 `usage_events`，以 `c-plus-report:<query_key>` 幂等并原子增加 `usage_quotas.consumed_units`。 | 通用 `/api/usage/events` 仍需单独接入 trusted service wiring。 |
| `membership_tier` / `daily_query_limit` | `backend/sql/supabase_user_profiles.sql:1-13` 定义字段；`backend/sql/002_private_project_rls.sql:195-219` 保护为服务端字段。 | 之前没有 billing webhook 更新这些字段。 | `backend/app/billing/store.py:99-150` 在订阅 webhook 成功/状态变化时更新会员等级和兼容额度，并 provision 当前 UTC+8 月 quota。 | `daily_query_limit` 是历史兼容字段，B 端完整的组织共享额度以 `usage_quotas` 为准。 |
| 订阅 webhook | `backend/app/billing/store.py:825-929` 已镜像 checkout/subscription 事件；`:1011-1039` 已处理支付失败。 | 之前只更新 `subscriptions`，没有会员等级/配额副作用。 | active/trialing 开通 C Plus/B Data Pro；past_due/canceled/退款回收为 free/不可新增权益；当前周期到期由 `current_period_end` 判定失效。 | 真实 Stripe webhook delivery、退款分支和生产数据库尚未联调。 |
| C Plus 12 份报告 | 原始规格规定“每自然月 12 份且不结转”，但旧代码无接线。 | 没有报告级 quota consumption 或解锁判断。 | 订阅成功 provision `report=12`；报告生成成功后消费一次；当前月份额度耗尽则回落单份购买；UTC+8 月份键自然切换。 | 首月折算、自动续费主动选择、失败重试通知等规格项不在本次最小闭环内。 |

## 自检命令与结果

1. `grep -n "TWD\|HKD\|SGD\|TW\|HK\|SG" backend/app/billing/catalog.py | head`

   已命中区域映射和价格行，范围见 `backend/app/billing/catalog.py:18-57`。

2. `grep -n "_has_report_unlock" -r backend/app | head`

   已确认定义在 `backend/app/main.py:116`，调用在 `backend/app/main.py:576`。

3. Python 测试：

   `backend/.venv/bin/python -m pytest -q`

   结果：`416 passed, 83 skipped`。

   新增/调整覆盖：

   - `tests/billing/test_catalog.py`：TWD/HKD/SGD/MO 区域、金额和模式。
   - `tests/billing/test_service.py`：单份 checkout 的报告 subject metadata。
   - `tests/api/test_report_access.py`：A 付费仅 A 解锁、未付费锁定、C Plus 有额度解锁、额度耗尽回落单份。
   - `tests/web/report-paywall.spec.js`：checkout 请求携带当前 `query_key` 与新文案。
   - `tests/unit/test_billing_store.py`、`tests/architecture/test_schema_ownership_audit.py`：新 forward migration 纳入离线迁移清单。

4. 其他已通过：

   - `python3 -m compileall -q backend scripts src`
   - `node --check web/app.js`
   - `node --check web/js/i18n.js`
   - `git diff --check`

5. 未验证项：

   - `npx playwright test tests/web/report-paywall.spec.js --reporter=line` 未能启动，因为当前沙箱禁止 Python HTTP server 绑定 `127.0.0.1:8787`（`PermissionError: Operation not permitted`）。
   - 真实 Stripe 沙盒 webhook delivery、真实数据库执行新迁移、订阅取消/退款/支付失败事件联调尚未执行；Stripe 对象未改动。

## 工作区状态

已执行 `git status --short`。工作区原有的部署、隐私、识别功能等修改均保留；本任务新增/修改的主要文件包括 billing catalog/service/routes/store、main、frontend i18n/paywall、forward migration、schema ownership manifest、data dictionary、相关测试和本报告。未执行 `git commit` 或 `git push`，未打印密钥。
