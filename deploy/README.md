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
