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
