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

Health checks:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## Render environment variables

- `DATABASE_URL`: staging Supabase/PostgreSQL connection string; keep it as an uncommitted Render secret
- `SUPABASE_URL`: Supabase project URL used to verify bearer tokens
- `SUPABASE_ANON_KEY`: Supabase anon key used only for Auth token verification
- `ALLOWED_ORIGINS`: `https://gordon310.github.io,http://127.0.0.1:8790,http://localhost:8790`
- `INIT_SCHEMA`: `false` in staging; apply reviewed SQL migrations separately
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
