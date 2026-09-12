# Release Gate Runbook

本 runbook 是上线前的离线/可重复门槛。它生成证据和候选 artifact，但不执行线上数据库、Auth、RLS、Storage、部署、DNS、billing 或真实客户数据操作。当前生产部署目标是 AWS Lightsail Compose；Supabase 是数据服务；Render 已挂起，仅作为待最终处置的回滚候选。

## 状态契约

每个检查的状态必须来自真实命令：

- `PASS`：命令已运行且退出码为 0。
- `FAIL`：命令已运行但退出码非 0。
- `BLOCKED`：必需工具、Docker、PostgreSQL、浏览器或网络环境不可用；阻断发布。
- `NOT_EXECUTED`：明确未运行的外部/线上检查；不能改写成 `PASS`。

`release_ready=true` 需要所有自动化检查为 `PASS`、生产外部检查有单独真实证据、人工批准记录和可恢复发布窗口。仓库配置不是生产可达性证据。

## 当前目标核对

- 官网：`https://zoubeacon.com`、`https://www.zoubeacon.com`
- C 端：`https://zoubeacon.app`、`https://www.zoubeacon.app`
- B 端：`https://platform.zoubeacon.com`
- API：`https://api.zoubeacon.com`
- 部署配置：`deploy/docker-compose.prod.yml` 的 `api`/`worker`/`scheduler`/`nginx`；Nginx 域名与代理见 `deploy/nginx/default.conf:1-86`。

本批执行的 curl 在当前环境均返回 `Could not resolve host`，所以 DNS、TLS、HTTP、健康端点和生产页面均保持 `NOT_EXECUTED/BLOCKED`，不能据此宣布已上线。

## 本地 gate 命令

在仓库根目录运行：

```bash
python3 -m pytest -q
node --check web/app.js
node --check playwright.config.js
node --test tests/edge/jphouse-run-authority.test.mjs
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src
python3 -m pip check
python3 scripts/ci/secret_scan.py --repo .
python3 scripts/ci/check_release_policy.py
python3 scripts/check_post_launch_review.py
git diff --check
```

依赖/供应链检查在工具和 advisory feed 可用时运行：

```bash
npm ci
npm audit --audit-level=high
python3 -m pip install pip-audit==2.9.0
pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt
```

浏览器检查必须使用仓库 fixture 和本地静态服务器，不能调用生产：

```bash
npx playwright install chromium
npm run test:web -- --workers=1
```

SQL/RLS 检查只能使用 disposable 数据库；不得把本地 reset 或 staging 结果写成 production evidence：

```bash
npx supabase start
npx supabase db reset --local
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_property_intake_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_provenance_policy_metric_contract.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/security/test_rls_private_projects.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/security/test_rls_v1_identity_matrix.sql
npx supabase stop --no-backup
```

## 证据与 artifact

先用 `record` 保存每个真实命令的状态（stdout/stderr 留在 CI 日志，不写入 JSON）：

```bash
python3 scripts/ci/release_evidence.py record --name python --output ci-results/python.json -- python3 -m pytest -q
```

所有 job 结果齐全后生成 manifest、候选 tag 和 evidence bundle：

```bash
python3 scripts/ci/release_evidence.py evidence --results-dir ci-results --output-dir release-evidence --version 0.1.0 --ref-name "${GITHUB_REF_NAME:-main}" --commit "${GITHUB_SHA:-$(git rev-parse HEAD)}"
```

检查 `release-evidence/manifest.json` 的各 check 状态、外部 `NOT_EXECUTED` 状态和 `artifact_sha256`。只要 required check 失败或外部证据缺失，就不可发布。脚本不创建 tag、Release、部署或数据库写入。

## 生产外部门槛

生产 AWS Lightsail 容器、Supabase database/Auth/Storage、四站点 DNS/TLS、Stripe 生产密钥/webhook、真实小额收款、法务政策批准、备份恢复、RLS/ownership、日志、告警和 rollback smoke 必须分别记录真实结果。Stripe 沙盒闭环只证明沙盒/代码路径，不能代替生产支付证据；Render 只能作为挂起回滚目标，不能写成当前服务。

## 失败处理

1. 阅读 evidence manifest，先处理第一个 `FAIL` 或 `BLOCKED`。
2. SQL reset 或生产迁移前置检查失败时停止后续 migration、部署和流量切换，保留 SQLSTATE/错误摘要。
3. 修复后重新跑完整 gate，不只重跑单个 job。
4. 只有离线检查全部 `PASS` 且外部/人工门槛闭合，才能交给负责人作 Go/No-Go 决策；这仍需保留可恢复发布窗口。
