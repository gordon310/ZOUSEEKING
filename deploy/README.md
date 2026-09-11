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
rounds with a 10-second interval; the scheduler performs one feed pass hourly.

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

SSL is terminated through Cloudflare using Full (strict) mode and the existing
Cloudflare Origin Certificate mounted from `/opt/zoubeacon/certs`. Do not run
`certbot` on this machine.
