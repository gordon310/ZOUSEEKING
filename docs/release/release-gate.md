# Release Gate Runbook

本 runbook 是正式上线前的离线/可重复门槛。它生成证据和候选 artifact，但不执行线上数据库、Auth、RLS、Storage、部署、DNS、billing 或真实客户数据操作。

## 状态契约

每个检查的状态必须来自真实命令：

- `PASS`：命令已运行且退出码为 0。
- `FAIL`：命令已运行但退出码非 0。
- `BLOCKED`：必需工具、Docker、PostgreSQL 或浏览器环境不可用；阻断发布。
- `NOT_EXECUTED`：明确未运行的外部/线上检查；不能改写成 `PASS`。

`release_ready=true` 需要所有自动化检查为 `PASS`、外部检查有单独的真实证据、人工批准记录和可恢复的发布窗口。本仓库当前仍有：

```text
migration_baseline_status = canonical_staging_reconciled_production_pending
```

M1 staging 已通过，但不得执行 migration repair、staging/production reset、
未经批准的 linked push，也不得把 staging 结果当作 production 结果。

## 本地 gate 命令

在仓库根目录运行。建议使用 Python 3.12（与 Render 配置一致）和隔离环境：

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

浏览器检查必须使用仓库 fixture 和本地静态服务器，不能调用 staging：

```bash
npx playwright install chromium
npm run test:web
```

SQL/RLS 检查只能使用 disposable 数据库。当前 migration baseline 已知不完整，因此 reset 失败必须记录为 `FAIL`/`BLOCKED`：

```bash
npx supabase start
npx supabase db reset --local
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_property_intake_schema.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_provenance_policy_metric_contract.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/security/test_rls_private_projects.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/security/test_rls_v1_identity_matrix.sql
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -v ON_ERROR_STOP=1 -f tests/sql/test_m1_reconciliation_contract.sql
npx supabase stop --no-backup
```

不要用 `backend/sql/` bootstrap 替代 reset；不要把任何 staging URL、service-role key、JWT、邮箱或业务行写入证据。

## 生成证据和 artifact

先用 `record` 保存每个真实命令的状态（stdout/stderr 保持在 CI 日志，不写入 JSON）：

```bash
python3 scripts/ci/release_evidence.py record \
  --name python \
  --output ci-results/python.json -- \
  python3 -m pytest -q
```

所有 job 结果齐全后生成 manifest、候选 tag、rollback checklist 和 evidence bundle：

```bash
python3 scripts/ci/release_evidence.py evidence \
  --results-dir ci-results \
  --output-dir release-evidence \
  --version 0.1.0 \
  --ref-name "${GITHUB_REF_NAME:-main}" \
  --commit "${GITHUB_SHA:-$(git rev-parse HEAD)}"
```

版本 tag 必须是 `vX.Y.Z` 且与 `pyproject.toml` 的 version 一致；分支或 PR 只生成 `vX.Y.Z-ci.<sha12>` 候选名。脚本不创建 tag、GitHub Release、部署或数据库写入。

检查 `release-evidence/manifest.json` 中的 `offline_gate_passed`、`release_ready`、各 check 状态、外部 `NOT_EXECUTED` 状态和 `artifact_sha256`。只要 required check 失败，就不生成 candidate source archive；evidence bundle 仍保留并明确不可发布。

## 外部检查门槛

M1 staging schema/RLS/Auth/Storage 已有单独受控证据；production database、Auth、
Storage、deployment、DNS、billing、真实账号、真实文件和真实报告仍不得由本地或
CI 猜测。它们必须另获授权并记录 migration、备份和回滚证据，否则保持
`NOT_EXECUTED`。

## CI 失败处理

1. 阅读 evidence manifest，先处理第一个 `FAIL` 或 `BLOCKED`。
2. SQL reset 失败时停止 migration 相关工作，并保留首次 SQLSTATE/错误摘要；不得指向 staging 继续试错。
3. 修复后重新跑完整 gate，不只重跑单个 job。
4. 只有 offline checks 全部 `PASS` 才可把 candidate source archive 交给后续人工审批；这仍不等于 production-ready。
