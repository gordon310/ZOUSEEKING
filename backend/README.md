# ZOU SEEKING HOUSE Backend

FastAPI + PostgreSQL backend for JPHOUSE query generation.

## Local setup

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"
export ALLOWED_ORIGINS="http://127.0.0.1:8790,http://localhost:8790,https://gordon310.github.io"
uvicorn app.main:app --reload --port 8000
```

## Schema ownership and local development

`supabase/migrations/` is the only forward migration history. The files in
`backend/sql/` are frozen bootstrap/reference material and are not a second
migration path. From the repository root, run the read-only ownership audit
before changing schema-related code:

```bash
python3 scripts/check_schema_ownership.py
npm run check:schema-ownership
```

The canonical history and the approved staging reconciliation have passed;
the gate is now `canonical_staging_reconciled_production_pending`. Do not use
`supabase migration repair`, a staging/production reset, or an unapproved
linked push. `INIT_SCHEMA=true` is retained only for disposable
`local`/`development`/`test` compatibility with the legacy
`backend/sql/schema.sql`; it does not apply `supabase/migrations/` and must not
be used as a staging or production setup command.

Health checks:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## 隐私与账户运营边界（离线契约）

- `GET /api/privacy` 公开返回 `privacy-2026-08`、`terms-2026-08`、同意字段、资料保留目标和客服占位入口；它不返回用户资料。
- `POST /api/account/deletion-request` 只接受已验证 Supabase bearer、当前政策/条款版本和固定确认值 `DELETE_ACCOUNT`。默认删除执行器为 fail-closed：返回 `503` 和 `no account data was changed`，不连接 Auth Admin、数据库或 Storage，也不模拟已删除。
- 注册同意由前端在提交边界写入 Supabase Auth metadata（版本与 UTC ISO 时间）；当前 legacy localStorage 回退仅供演示，不能作为 production 认证或同意证据。
- `/recover`、`/logout` 和密码更新仍由 Supabase Auth 负责；FastAPI 不接收密码、refresh token 或客服正文。登录、注册和找回密码文案必须保持账户枚举安全。

`migration_baseline_status = canonical_staging_reconciled_production_pending`；M1 已用
合成 staging 账号验证 Auth Admin 删除、RLS/Storage 与清理，但没有接通本应用的
删除执行器、发送通知或执行生产部署。运营主体、客服邮箱、近期重新认证、持续清理器和删除
执行器仍需单独授权与演练；详见 `docs/legal/privacy-operations-runbook.md`。
本验收不发送通知，也不使用真实账号或资料。

## Render environment variables

- `DATABASE_URL`: staging Supabase/PostgreSQL connection string; keep it as an uncommitted Render secret
- `SUPABASE_URL`: Supabase project URL used to verify bearer tokens
- `SUPABASE_ANON_KEY`: Supabase anon key used only for Auth token verification
- `ALLOWED_ORIGINS`: `https://gordon310.github.io,http://127.0.0.1:8790,http://localhost:8790`
- `INIT_SCHEMA`: `false` in staging; apply reviewed forward migrations through the canonical migration workflow
- `ENVIRONMENT`: `staging`
- `APP_VERSION`: deployed build identifier
- `INTERNAL_DIAGNOSTICS_TOKEN`: optional secret for provenance metadata diagnostics

After Render deploys the backend, set the frontend API URL:

```js
localStorage.setItem("zou_house_api_base", "https://YOUR-RENDER-SERVICE.onrender.com")
```

Authenticated project queries must use this FastAPI URL. The frontend no longer writes `queries` or `generation_jobs` through the anonymous Supabase REST client; it sends the Supabase access token to `/api/query`, `/api/jobs/*`, `/api/my/queries`, and `/api/reports/*`.

For production, replace this localStorage override with a committed `web/config.js` value.

## Stripe billing boundary (offline only)

当前 Stripe 边界默认关闭：`BILLING_ENABLED` 默认应为 `false`，未注入经过审核的 gateway/store 时 `/api/billing/checkout`、`/api/billing/portal`、`/api/billing/status`、`/api/billing/cancel` 和 `/api/billing/refunds` 返回 `503`，不会产生真实收费。价格目录可以展示已确认的金额，但没有服务端 `price_id` 时不可购买。

`/api/billing/webhook` 只接受 FastAPI 原始 request body，先用 `Stripe-Signature` 验签，再按唯一 `event.id` 幂等处理；暂时性处理失败返回通用 `5xx` 供 provider 重试，错误事件不会把内部异常或原始 payload 返回给客户端。Checkout 的产品、币种、金额、customer 和 redirect URL 均由服务端决定，不能由浏览器覆盖。

本地验证只使用 `tests/billing` 的固定 fixtures、fake gateway 和 fake store：不连接 live Stripe、不使用 live key、不产生真实收费。接入真实 provider 前必须完成 canonical membership/billing migration、RLS/owner 矩阵、Stripe Dashboard Customer Portal 配置、webhook delivery、provider backup/restore、税费/收据和退款演练，并取得明确的 staging/production 授权。
