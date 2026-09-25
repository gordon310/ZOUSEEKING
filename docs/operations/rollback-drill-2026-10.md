# Rollback drill — 2026-09-25 (production)

Scope: rehearse a production code rollback on the Lightsail Compose stack, verify the
key paths on the rolled-back revision, then roll forward to the current `main`.
This documents what was actually run and observed. It is **not** a claim of
database-level recoverability: this drill rolls back application code only, and no
schema or data change was made at any point.

## Baseline (measured before the drill)

| Item | Value |
| --- | --- |
| Host | `52.221.7.33` (`jpbox`), Compose project `deploy` |
| `git HEAD` | `85bc86f docs(progress): record the green Release Gate run for the C13 carrier` |
| Working tree | clean (`git status --porcelain` empty) |
| Containers | `deploy-api-1`, `deploy-report-worker-1`, `deploy-worker-1`, `deploy-scheduler-1` up; `deploy-nginx-1` up |
| Readiness | `https://api.zoubeacon.com/health/ready` = 200 |
| Site | `https://zoubeacon.app` = 200 |
| Frontend asset version | `20260923-r63` |
| Migration ledger | 54 applied (unchanged by this drill) |

Rollback target: `fd13974 fix(worker): run the collection worker continuously instead of
restarting every ten minutes` — the revision production ran before the 2026-09-25 launch
batch. Roll-forward target: `main` = `711c73f`.

Schema compatibility for the rollback target was checked before running: the migrations
applied after `fd13974` only **add** tables (`invite_codes`, `invite_redemptions`,
`shared_rate_limits`) and backfill data (provenance columns). `fd13974` reads none of them,
so the older code runs against the current schema.

## Timeline (host clock, UTC)

| T | Time | Event |
| --- | --- | --- |
| T0 | 15:18:44 | baseline captured |
| T1 | 15:18:44 | `git checkout fd13974` (HEAD is now `fd13974`) |
| T2 | 15:19:06 | rebuild and container replacement finished — **22 s** |
| T3 | 15:19:52 | roll-forward begins |
| T4 | 15:19:52 | `git fetch` + `git checkout main` + `git pull --ff-only` → `711c73f` |
| T5 | 15:20:30 | rebuild and container replacement finished — **38 s** |
| T6 | 15:20:41 | post-roll-forward verification complete |

Total drill wall time ≈ 2 minutes including verification. Container replacement is the
only interruption; the build stages ran while the previous containers were still serving,
so the unusable window is the container swap itself (seconds), not the build.

## Commands and observed output

### 1. Rollback

```bash
cd /opt/zouseeking
git checkout fd13974
docker compose -f deploy/docker-compose.prod.yml up -d --build api report-worker worker scheduler
```

Observed:

```text
HEAD is now at fd13974 fix(worker): run the collection worker continuously instead of restarting every ten minutes
 Container deploy-worker-1 Starting / Started
 Container deploy-report-worker-1 Starting / Started
 Container deploy-scheduler-1 Starting / Started
 Container deploy-api-1 Starting / Started
```

Post-rollback checks:

| Check | Result |
| --- | --- |
| `/health/ready` | **200** |
| `https://zoubeacon.app` | **200** |
| `GET /api/admin/overview` unauthenticated | **401** |
| Containers | all four `Up`, nginx untouched (`Up 8 days`) |
| Frontend asset version | **`20260917-r61`** |

The asset version moved back with the checkout because nginx serves `../web` from the
working tree; a code checkout therefore changes the frontend too, immediately.

### 2. Roll forward

```bash
git fetch origin && git checkout main && git pull --ff-only origin main
docker compose -f deploy/docker-compose.prod.yml up -d --build api report-worker worker scheduler
```

Observed:

```text
HEAD = 711c73f docs: record the D-12 open-registration closure, the R2 retention policy and the frontend version-drift fix
```

| Check | Result |
| --- | --- |
| `/health/ready` | **200** |
| `https://zoubeacon.app` | **200** |
| `GET /api/admin/overview` unauthenticated | **401** |
| Containers | all four `Up`, nginx still `Up 8 days` |
| Frontend asset version | **`20260925-r64`** |

### 3. Functional check of the rolled-forward revision

The roll-forward also carries the open-registration change, so its behaviour was checked
against the same endpoint that used to require the code:

```bash
curl -s -o /tmp/reg.json -w "http=%{http_code}\n" \
  -X POST https://api.zoubeacon.com/api/auth/invite-register \
  -H "Content-Type: application/json" \
  -d '{"email":"not-an-email","password":"abcdef","username":"probe"}'
```

Observed:

```text
http=400
body={"detail":{"code":"invite_registration_invalid"}}
```

`400 invite_registration_invalid` means the request reached the business validation with
no invite code present. On the pre-D-12 revision the same body is rejected earlier as
`422` (missing required `invite_code`). This is the production evidence that the invite
code is no longer required. The probe used an invalid address and created no account; it
consumed one unit of the shared `consumer_registration` rate-limit counter, which is the
normal behaviour of that endpoint.

## What this drill does and does not prove

Proven:

- A production code rollback to the previous revision restores service: readiness, the
  public site and the authorization boundary all held.
- Rolling forward to `main` restores the newer revision and its behaviour.
- The rollback target runs correctly against the current 54-migration schema.
- The whole cycle is short and repeatable (22 s and 38 s of build-and-replace).

Not proven / not rehearsed (tracked as residual risk):

- **Database-level recovery** — no data or schema rollback was exercised. `restore_drill.py`
  covers logical restore separately; a provider-level PITR/restore remains to be approved
  and rehearsed (Go/No-Go item C04).
- Rollback while a report job is mid-flight, and rollback while a payment webhook is
  being processed, were not exercised. The outbox lease design is expected to recover
  in-flight reports, but that expectation is untested under a real rollback.
- Rollback from a future revision that contains a *destructive* migration would need a
  different procedure (expand/backfill/switch/contract), and is not covered here.
- No traffic-shaping or user-facing maintenance page was used; during the swap window
  requests would fail rather than be queued.

## Sources of delay during the drill

The first attempt at the rollback phase failed before executing anything: the SSH path via
the local SOCKS proxy was down (both the production host and `github.com` refused SSH at
key exchange while HTTP also returned 000). Restarting the local proxy application restored
the channel, and the host was re-checked to be unchanged (`85bc86f`, clean tree) before
retrying. No command from the failed attempts reached the host.
