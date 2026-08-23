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

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Render environment variables

- `DATABASE_URL`: Render PostgreSQL internal connection string
- `ALLOWED_ORIGINS`: `https://gordon310.github.io,http://127.0.0.1:8790,http://localhost:8790`
- `INIT_SCHEMA`: `true`

After Render deploys the backend, set the frontend API URL:

```js
localStorage.setItem("zou_house_api_base", "https://YOUR-RENDER-SERVICE.onrender.com")
```

For production, replace this localStorage override with a committed `web/config.js` value.

