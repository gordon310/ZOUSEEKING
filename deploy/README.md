# Lightsail deployment runbook

## Layout and prerequisites

Clone this repository to `/opt/zouseeking`. The production Compose file is
`/opt/zouseeking/deploy/docker-compose.prod.yml`; Compose resolves its relative
volume paths from the `deploy/` directory, so `../web` mounts the repository's
`web/` directory.

Create `/opt/zouseeking/deploy/.env` from `.env.example` and fill it in on the
server. Keep it restricted to the operator:

```bash
chmod 600 /opt/zouseeking/deploy/.env
```

The existing `/opt/zoubeacon` website and its Cloudflare Origin Certificate are
used by the multi-site Nginx container. Do not replace the certificate files.

## JPPGSKILL 内网服务

当前版本默认不启动 JPPGSKILL，也不上线图片 AI 识别。只有完成负责人/法务和运营配置后，才使用 `--profile ai` 显式启动；后端同时需要将 `RECOGNITION_AI_ENABLED=true`。

首次部署前，先使用已配置 SSH deploy key 将 JPPGSKILL clone 到
`/opt/jppskill`，并在服务器填写 `deploy/jpsskill.env`。该服务只加入
Compose 内部网络，不映射宿主端口；`api` 容器通过
`http://jpsskill:8100` 调用它。

```bash
cd /opt
git clone <jppskill-repository-url> jppskill
cd /opt/zouseeking
cp deploy/jpsskill.env.example deploy/jpsskill.env
# Edit deploy/jpsskill.env on the server and add the real OpenAI values.
chmod 600 deploy/jpsskill.env
docker compose -f deploy/docker-compose.prod.yml --profile ai up -d --build jpsskill
```

健康检查（在 `/opt/zouseeking` 目录执行）：

```bash
cd /opt/zouseeking
docker compose -f deploy/docker-compose.prod.yml exec jpsskill node -e "fetch('http://127.0.0.1:8100/api/analyze',{method:'OPTIONS'}).then(r=>process.exit(r.status===204?0:1))"
```

`api` 未配置 `depends_on: jpsskill`。因此 Compose 不保证两个容器的启动顺序；
如果 `api` 在 JPPGSKILL 就绪前启动，首次调用可能失败，应用侧应通过重试或健康状态处理，
而不依赖 Compose 的启动顺序。

## First deployment and cutover

```bash
cd /opt
git clone <repository-url> zouseeking
cd /opt/zouseeking
cp deploy/.env.example deploy/.env
# Edit deploy/.env on the server, without putting secrets in Git or chat.
chmod 600 deploy/.env
python3 deploy/render-frontend-config.py
docker stop zoubeacon-nginx
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

Run `python3 deploy/render-frontend-config.py` on the first deployment and
before every update, before `docker compose up`, so the `web/` directory
mounted by Nginx has the correct configuration. `web/config.js` is a generated
file; do not edit it manually. Regenerate it whenever domains or the release
phase changes.

The new Nginx container serves the project at `zoubeacon.app` and
`platform.zoubeacon.com`, keeps the company website at `zoubeacon.com`, and
proxies `api.zoubeacon.com` to the API container. The worker polls up to 60
rounds with a 10-second interval; the scheduler performs one feed pass and one
account-retention sweep hourly. The retention sweep runs
`python /app/scripts/account_retention_sweeper.py --limit 50` on each scheduler
loop: it records only the fact that a provider-backup retention deadline has
passed and does not modify the provider backup.

## Rollback

If the new deployment must be stopped, run:

```bash
cd /opt/zouseeking
docker compose -f deploy/docker-compose.prod.yml down
docker start zoubeacon-nginx
```

This restores the existing `zoubeacon-nginx` single-container deployment. The
Compose `down` command does not remove the repository or Supabase data.

## Routine update

```bash
cd /opt/zouseeking
git pull --ff-only
python3 deploy/render-frontend-config.py
docker compose -f deploy/docker-compose.prod.yml up -d --build
```

## Logs and health checks

```bash
cd /opt/zouseeking
docker compose -f deploy/docker-compose.prod.yml logs --tail=200 api worker scheduler nginx
curl -fsS https://api.zoubeacon.com/health/ready
```

## Read-only observability timer

`deploy/observability-check.sh` checks only Compose state, API health and
read-only PostgreSQL queue/freshness queries. It exits non-zero for a missing
`api`/`report-worker`/`nginx`, failed health endpoint, any failed outbox row,
running outbox row leased for over 15 minutes, or due pending row. It prints
the latest `usage_events.created_at` and `property_reports.created_at` as
freshness evidence; freshness age thresholds are deliberately not invented.

The production probe deliberately crosses the same boundaries that are
available on the host:

- Health uses `curl` against the public readiness URL
  `https://api.zoubeacon.com/health/ready` by default. Override it with
  `API_HEALTH_URL` only when the public endpoint changes. The Compose `api`
  service uses `expose: 8000`, which is reachable to Compose peers but does not
  publish host `127.0.0.1:8000`; a host-local readiness probe therefore fails.
- Database metrics run with `docker exec deploy-api-1 python -c ...` and the
  API image's `asyncpg`, with `default_transaction_read_only = on` asserted
  before each `SELECT`. The host intentionally need not install `psql`. If the
  production Compose project gives the API container another name, set
  `API_CONTAINER` in the environment file to that container name.

`observability-check.service` has a required
`EnvironmentFile=/etc/zouseeking/observability.env`. systemd refuses to start
the service with `Failed to load environment files` when it is missing, so
create it before enabling or manually starting the timer. It must contain a
`DATABASE_URL` accepted by the API container; include optional overrides only
when needed:

```dotenv
DATABASE_URL=postgresql://read_only_role:...@database-host:5432/postgres
# API_HEALTH_URL=https://api.zoubeacon.com/health/ready
# API_CONTAINER=deploy-api-1
```

Use a database role restricted to reads where available. The script also
enforces a read-only session, but that is defense in depth rather than a
replacement for database permissions.

Install only after an operator has reviewed the production paths and database
credential scope; this change does not install anything on a host:

```bash
sudo install -d -o ubuntu -g ubuntu -m 755 /var/log/zouseeking /etc/zouseeking
sudo install -o ubuntu -g ubuntu -m 600 /dev/null /etc/zouseeking/observability.env
sudoedit /etc/zouseeking/observability.env  # DATABASE_URL=... (read-only role preferred)
sudo install -o root -g root -m 755 deploy/observability-check.sh /opt/zouseeking/deploy/observability-check.sh
sudo cp deploy/systemd/observability-check.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now observability-check.timer
sudo systemctl start observability-check.service
sudo tail -n 100 /var/log/zouseeking/observability.log
```

The timer runs every 15 minutes and appends stdout/stderr to
`/var/log/zouseeking/observability.log`. A non-zero run is an alert for
operators to inspect; the script never repairs, requeues, or deletes rows.

SSL is terminated through Cloudflare using Full (strict) mode and the existing
Cloudflare Origin Certificate mounted from `/opt/zoubeacon/certs`. Do not run
`certbot` on this machine.

## Monthly MLIT transaction refresh

The refresh service imports the current and previous calendar year for Tokyo,
Osaka, and Niigata. It is idempotent and does not restart the Compose
containers. The unit template runs as `ubuntu`, which is the service user on the
current host. If your deployment user differs, change both `User=` and `Group=`
in `deploy/systemd/mlit-refresh.service` and synchronize the key-file owner
below before installing the unit. The script checks that the API key is readable
and has mode `600`, and exits without running the importer when that check fails.

Install the host interpreter and dependency first. The default interpreter is
`/opt/zouseeking/backend/.venv/bin/python`; set `PYTHON_BIN=` in a systemd
drop-in or the deployment copy of the script only when using another path.
`DATABASE_URL` is read from the optional systemd environment file shown below:

```bash
cd /opt/zouseeking
python3 -m venv /opt/zouseeking/backend/.venv
/opt/zouseeking/backend/.venv/bin/pip install asyncpg
chmod 600 /opt/zouseeking/deploy/.env
```

Create the API key file as the service user with mode `600`; edit it without
printing the value:

```bash
sudo install -d -m 755 /etc/zouseeking
sudo install -o ubuntu -g ubuntu -m 600 /dev/null /etc/zouseeking/mlit-api-key
sudoedit /etc/zouseeking/mlit-api-key
sudo chown ubuntu:ubuntu /etc/zouseeking/mlit-api-key
sudo chmod 600 /etc/zouseeking/mlit-api-key
```

Install the script and systemd units, reload systemd, and enable the timer:

```bash
cd /opt/zouseeking
sudo install -o root -g root -m 755 deploy/mlit-refresh.sh /opt/zouseeking/deploy/mlit-refresh.sh
sudo cp deploy/systemd/mlit-refresh.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mlit-refresh.timer
```

Confirm one manual run and inspect its timestamped output:

```bash
sudo systemctl start mlit-refresh.service
sudo tail -n 200 /var/log/zouseeking/mlit-refresh.log
```

Stop and disable the timer when the refresh is no longer wanted:

```bash
sudo systemctl disable --now mlit-refresh.timer
```

The script does not contain a production connection string or secret.
