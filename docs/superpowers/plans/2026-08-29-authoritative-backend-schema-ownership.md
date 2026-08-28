# 权威后端与 Schema 所有权 ADR 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在实现任何 V1 会员、计费、任务、联系授权或后台功能之前，正式接受并锁定唯一的架构决策。

**Architecture:** Supabase Auth 是唯一身份签发方；FastAPI 是唯一私有产品 API 和授权边界；Supabase PostgreSQL 是共享数据存储；`supabase/migrations/` 是唯一前向迁移历史；FastAPI 验签后的 webhook 写入幂等事件和 outbox；未来异步任务只由一个 PostgreSQL-backed durable worker 执行。当前浏览器私有 Supabase REST 回退、`jphouse-run`、本地 REST worker 和 FastAPI 进程内报告任务均冻结为兼容旧路径。

**Tech Stack:** Markdown ADR、JSON 架构清单、Python 3 标准库、pytest、FastAPI、Supabase Auth/PostgreSQL/Storage、Supabase CLI migrations。

**Spec:** `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md`

## Global Constraints

- 本子项目只完成 ADR 和仓库护栏，不新增业务表、migration、endpoint、worker handler、支付集成、任务流程、联系信息、后台 UI 或产品 fixture。
- 不为了添加弃用注释而修改现有业务源文件。当前工作区已有用户改动；本计划只创建新的策略文件，并仅修改已经确认且当前干净的产品规格状态。
- 不执行或修复 linked database，不修改 Auth/RLS/Storage，不部署服务或函数，不调整 DNS，不配置支付。
- 不编辑任何已经应用的 `supabase/migrations/` 文件。
- 浏览器只允许直连 Supabase Auth 和明确批准的公开只读资源，例如 `query_field_options`。所有私有或需要登录的产品读写都必须经过 FastAPI。
- RLS 仅作为纵深防御，不能替代 FastAPI 的授权、机构所有权、权益、额度、隐私流程和后台权限检查。
- 当前 migration history 不完整。ADR 必须记录 `reconciliation_required`，不得暗示 fresh install、staging drift、restore 或 production readiness 已验证。
- 现有竞争路径只为当前 staging 兼容保留，冻结期间不得加入任何 V1 新逻辑。

---

### Task 1：把架构决策编码为可测试契约

**Files:**
- Create: `docs/architecture/adr-0001-authoritative-backend-and-schema.md`
- Create: `docs/architecture/authoritative-boundaries.json`
- Create: `tests/architecture/test_authoritative_backend_policy.py`
- Existing, stage with this task: `docs/superpowers/plans/2026-08-29-authoritative-backend-schema-ownership.md`

**Interfaces:**
- `authoritative-boundaries.json` 为每个权威边界提供唯一、机器可读的值。
- ADR-0001 记录证据、目标流向、被拒方案、后果、旧路径例外和发布门槛。
- 测试在未来有人静默选择第二个私有 API、migration 目录、webhook handler 或异步执行器时失败。

- [ ] **Step 1：先编写失败的架构契约测试**

创建 `tests/architecture/test_authoritative_backend_policy.py`：

```python
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = ROOT / "docs/architecture/adr-0001-authoritative-backend-and-schema.md"
POLICY_PATH = ROOT / "docs/architecture/authoritative-boundaries.json"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_manifest_selects_one_authoritative_path() -> None:
    policy = load_policy()

    assert policy == {
        "decision_id": "ADR-0001",
        "status": "accepted",
        "identity_issuer": "supabase_auth",
        "private_product_boundary": "fastapi",
        "database": "supabase_postgres",
        "forward_migration_history": "supabase/migrations",
        "payment_webhook_boundary": "fastapi_verified_webhook_then_outbox",
        "background_execution": "postgres_job_outbox_single_worker",
        "migration_baseline_status": "reconciliation_required",
        "allowed_browser_supabase_surfaces": [
            "auth/v1",
            "rest/v1/query_field_options:select",
        ],
        "frozen_legacy_components": [
            "web/app.js:direct_private_supabase_and_edge_fallback",
            "supabase/functions/jphouse-run:regional_report_edge_executor",
            "scripts/run_jphouse_worker.py:regional_report_rest_worker",
            "backend/app/main.py:in_process_regional_report_executor",
        ],
    }


def test_adr_records_non_overlapping_responsibilities() -> None:
    text = ADR_PATH.read_text(encoding="utf-8")

    required = (
        "状态：Accepted",
        "Supabase Auth 是唯一身份签发方",
        "FastAPI 是所有私有产品读写的唯一应用边界",
        "`supabase/migrations/` 是唯一前向迁移历史",
        "支付 webhook 先验签，再写入去重事件与 outbox",
        "一个 PostgreSQL-backed durable worker",
        "migration_baseline_status = reconciliation_required",
    )
    for statement in required:
        assert statement in text
```

- [ ] **Step 2：运行测试并确认失败**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py
```

Expected: FAIL，因为 ADR 和 JSON manifest 尚不存在。

- [ ] **Step 3：创建精确的机器可读架构清单**

创建 `docs/architecture/authoritative-boundaries.json`：

```json
{
  "decision_id": "ADR-0001",
  "status": "accepted",
  "identity_issuer": "supabase_auth",
  "private_product_boundary": "fastapi",
  "database": "supabase_postgres",
  "forward_migration_history": "supabase/migrations",
  "payment_webhook_boundary": "fastapi_verified_webhook_then_outbox",
  "background_execution": "postgres_job_outbox_single_worker",
  "migration_baseline_status": "reconciliation_required",
  "allowed_browser_supabase_surfaces": [
    "auth/v1",
    "rest/v1/query_field_options:select"
  ],
  "frozen_legacy_components": [
    "web/app.js:direct_private_supabase_and_edge_fallback",
    "supabase/functions/jphouse-run:regional_report_edge_executor",
    "scripts/run_jphouse_worker.py:regional_report_rest_worker",
    "backend/app/main.py:in_process_regional_report_executor"
  ]
}
```

- [ ] **Step 4：创建 ADR-0001**

创建 `docs/architecture/adr-0001-authoritative-backend-and-schema.md`，必须包含：

1. **状态与范围：** `状态：Accepted`、日期 `2026-08-29`、已确认产品规格的链接，以及“ADR 本身不授权实现业务功能”。
2. **当前证据：** 明确记录以下冲突：
   - `backend/app/routes/intake.py` 已使用 FastAPI 处理私有 intake。
   - `backend/app/auth.py` 在 API 边界验证 Supabase 身份。
   - `web/app.js` 仍保留 authenticated PostgREST 和 Edge 回退。
   - `supabase/functions/jphouse-run/index.ts`、`scripts/run_jphouse_worker.py` 和 `backend/app/main.py::run_generation_job` 重复执行报告任务。
   - `supabase/migrations/20260825000400_property_intake.sql` 依赖 `public.properties` 与 `public.residential_details`，但该目录没有更早的 migration 创建这些表。
3. **决策：** 包含测试断言的所有原句，并写入目标流向：

```text
Browser
  -> Supabase Auth: signup, login, refresh, logout
  -> local/static content and approved public read-only options
  -> FastAPI: all private or authenticated product operations
       -> Supabase PostgreSQL transaction + RLS defense in depth
       -> transactional outbox/job row
            -> one durable worker

Payment provider
  -> FastAPI verified webhook
       -> unique provider event + business transaction + outbox
```

4. **所有权矩阵：** 身份签发归 Supabase Auth；私有读写、授权、机构、权益、额度、账单、任务、隐私和后台动作归 FastAPI；异步执行归唯一 worker；前向 schema 变更归 `supabase/migrations/`；公开静态内容生成继续归现有离线脚本。
5. **浏览器 allowlist：** 只允许 `auth/v1` 和匿名 `SELECT query_field_options`；禁止浏览器直读写 profile、project、query、report、organization、usage、payment、task、consent 和 audit 数据。
6. **Worker 与 webhook 契约：** 要求原子 claim、幂等、有限重试、失败分类、原始 webhook 验签、唯一 provider event ID 和 commit 后 outbox 交付；明确 FastAPI `BackgroundTasks` 不是 V1 durable worker。
7. **Migration 契约：** 设置 `migration_baseline_status = reconciliation_required`；fresh local reset、SQL 断言、RLS 身份测试、drift 对比与 backup/restore 方案通过审核前，禁止 V1 schema 工作。
8. **旧路径过渡：** 冻结 manifest 中四项；退出条件为私有 web caller 已移除、legacy queue 已清空或迁移、替代 worker 已验证、部署操作已获批准。
9. **拒绝方案：** 拒绝 PostgREST/RLS-only 业务后端、Edge Function 业务后端、FastAPI/Edge 双写实现，以及立即迁移 Render PostgreSQL。
10. **后果：** 记录 FastAPI 加 worker 的运维成本、现有浏览器 token 存储发布风险、migration baseline 缺口，以及该决策不代表系统安全或 production-ready。

- [ ] **Step 5：重新运行测试并确认通过**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py
```

Expected: PASS，每个权威边界均只有一个值。

- [ ] **Step 6：只提交新决策文件和本计划**

```bash
git add docs/architecture/adr-0001-authoritative-backend-and-schema.md docs/architecture/authoritative-boundaries.json tests/architecture/test_authoritative_backend_policy.py docs/superpowers/plans/2026-08-29-authoritative-backend-schema-ownership.md
git commit -m "docs: select authoritative backend and schema path"
```

---

### Task 2：声明 schema 所有权与未完成的 baseline 门槛

**Files:**
- Create: `supabase/migrations/README.md`
- Create: `backend/sql/README.md`
- Modify: `tests/architecture/test_authoritative_backend_policy.py`

**Interfaces:**
- `supabase/migrations/README.md` 是前向 schema 变更的贡献契约。
- `backend/sql/README.md` 对历史 SQL 分类，但不删除或改写它们。
- 测试阻止任何人把当前不完整 migration chain 描述成可重建基线。

- [ ] **Step 1：添加失败的 schema 所有权测试**

追加：

```python
MIGRATION_POLICY_PATH = ROOT / "supabase/migrations/README.md"
LEGACY_SQL_POLICY_PATH = ROOT / "backend/sql/README.md"


def test_migration_policy_blocks_v1_until_reconciliation() -> None:
    text = MIGRATION_POLICY_PATH.read_text(encoding="utf-8")

    assert "唯一前向迁移历史" in text
    assert "20260825000400_property_intake.sql" in text
    assert "依赖尚未进入迁移历史的基础表" in text
    assert "migration_baseline_status = reconciliation_required" in text
    assert "基线协调完成前，不得增加 V1 业务迁移" in text
    assert "不得执行 linked repair、db push 或 production reset" in text


def test_backend_sql_is_non_authoritative_reference() -> None:
    text = LEGACY_SQL_POLICY_PATH.read_text(encoding="utf-8")

    assert "backend/sql/ 不是迁移历史" in text
    assert "backend/sql/schema.sql" in text
    assert "backend/sql/supabase_schema.sql" in text
    assert "backend/sql/001_foundation_data_contract.sql" in text
    assert "新 schema 变更只能新增到 supabase/migrations/" in text
```

- [ ] **Step 2：运行 schema 测试并确认失败**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py -k "migration_policy or backend_sql"
```

Expected: FAIL，因为两个所有权 README 均不存在。

- [ ] **Step 3：创建 canonical migration 策略**

创建 `supabase/migrations/README.md`，写明：

- `supabase/migrations/` 是唯一前向 migration history。
- 已应用的 migration 文件不可修改；修复必须新增更晚的 migration。
- 当前最早文件 `20260825000400_property_intake.sql` 依赖尚未由更早 migration 创建的 foundation objects。
- 当前状态必须精确写为 `migration_baseline_status = reconciliation_required`。
- 写入原句：`基线协调完成前，不得增加 V1 业务迁移`。
- 后续 baseline 计划必须从审核后的仓库 SQL 与只读 staging schema inventory 推导缺失 schema，新增确定性的早期 migration，在空的本地 Supabase 执行 reset，运行 foundation/intake/RLS 断言，对比不含客户数据的 schema drift，并制定 backup/restore 与 forward-fix 方案。
- linked migration repair 或 push 必须另行明确批准；写入原句 `不得执行 linked repair、db push 或 production reset`。

- [ ] **Step 4：把历史 SQL 标记为非权威参考**

创建 `backend/sql/README.md`：

| Files | Classification | Rule |
| --- | --- | --- |
| `schema.sql` | legacy non-Supabase bootstrap | 仅用于 disposable local/test compatibility；不得新增 production 字段 |
| `supabase_schema.sql`, `supabase_user_profiles.sql` | historical staging bootstrap/reference | 不得作为新 migration 路径 |
| `001_foundation_data_contract.sql`–`003_analysis_policy_versions.sql` | historical pre-migration work | 仅作为 baseline reconstruction 的来源证据 |
| `supabase_field_options.sql`, `supabase_indexes.sql` | generated/manual support SQL | 进入 managed environment 前必须重新生成或改成经过审核的 forward migration |

必须包含 `backend/sql/ 不是迁移历史` 和 `新 schema 变更只能新增到 supabase/migrations/`，并说明 staging lineage 完成协调前保留所有原文件不动。

- [ ] **Step 5：运行完整架构测试**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py
```

Expected: PASS；没有修改 SQL 文件或数据库。

- [ ] **Step 6：只提交新所有权文档和测试更新**

```bash
git add supabase/migrations/README.md backend/sql/README.md tests/architecture/test_authoritative_backend_policy.py
git commit -m "docs: define canonical migration ownership"
```

---

### Task 3：盘点全部竞争路径并记录产品确认

**Files:**
- Create: `docs/architecture/runtime-conflict-inventory.md`
- Modify: `tests/architecture/test_authoritative_backend_policy.py`
- Modify: `docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md`

**Interfaces:**
- inventory 在不修改用户业务实现的前提下，使代码和文档冲突可审核。
- 每个冲突记录当前用途、ADR 状态、禁止加入的 V1 功能和退出条件。
- 产品规格只更新确认状态并链接 ADR-0001，不改变任何商业或隐私规则。

- [ ] **Step 1：确认产品规格没有未提交重叠改动**

Run:

```bash
git status --short docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md
git diff -- docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md
```

Expected: 无输出。如果该文件之后出现无关改动，停止 Task 3 并报告重叠，不编辑、不暂存。

- [ ] **Step 2：添加失败的冲突清单测试**

追加：

```python
INVENTORY_PATH = ROOT / "docs/architecture/runtime-conflict-inventory.md"
SPEC_PATH = (
    ROOT
    / "docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md"
)


def test_conflict_inventory_covers_every_frozen_component() -> None:
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    policy = load_policy()

    for component in policy["frozen_legacy_components"]:
        path = component.split(":", 1)[0]
        assert path in inventory
    assert "docs/supabase-setup.md" in inventory
    assert "backend/sql/" in inventory
    assert "supabase/migrations/" in inventory
    assert "不得承载 V1 新功能" in inventory


def test_approved_spec_links_to_adr_without_losing_core_rules() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    assert "**状态：** 产品规则已确认；架构采用 ADR-0001" in text
    assert "adr-0001-authoritative-backend-and-schema.md" in text
    assert "C Plus／月" in text
    assert "B Data Pro／月" in text
    assert "平台不参与报价、议价、付款、佣金、托管、发票或任务费用退款" in text
```

- [ ] **Step 3：运行清单测试并确认失败**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py -k "conflict_inventory or approved_spec"
```

Expected: FAIL，因为 inventory 不存在，spec 仍是确认前状态。

- [ ] **Step 4：创建 runtime conflict inventory**

创建 `docs/architecture/runtime-conflict-inventory.md`，至少包含：

| Current component | Current role | ADR status | V1 rule | Exit condition |
| --- | --- | --- | --- | --- |
| `web/app.js` direct authenticated PostgREST and Edge fallback | legacy profile/query/report compatibility | frozen | 不新增私有读写 | FastAPI 等价接口验证并移除 caller |
| `supabase/functions/jphouse-run/` | legacy regional report generator | frozen | 不加入会员、额度、账单、任务、授权或后台逻辑 | 清空/迁移 queue 并经批准下线函数 |
| `scripts/run_jphouse_worker.py` | local service-role REST report worker | frozen | 不加入 V1 worker handler | canonical worker 验证且 legacy queue 退役 |
| `backend/app/main.py::run_generation_job` | in-process report executor | frozen | 不执行 V1 durable job | canonical queue/worker 接管报告生成 |
| `backend/sql/` and `supabase/migrations/` | competing schema histories | blocked | 未来只允许 `supabase/migrations/` | baseline reconciliation 通过 |
| `docs/supabase-setup.md` | 混合历史 setup 和当前 staging 指引 | conflict documented | ADR-0001 优先 | 重叠工作区改动整合后更新 |
| `docs/render-postgres-deploy.md` | deferred Render PostgreSQL option | V1 rejected | 禁止仅替换 connection string | 新 ADR 和 migration plan 获批 |

写入原句 `以上路径不得承载 V1 新功能`，并记录仍允许直连的 Supabase Auth 与公开只读 `query_field_options`。

- [ ] **Step 5：只更新干净规格文件的头部**

- 将状态改成 `**状态：** 产品规则已确认；架构采用 ADR-0001`。
- 紧随其后添加 `[ADR-0001：权威后端与 schema 所有权](../../architecture/adr-0001-authoritative-backend-and-schema.md)`。
- 不修改价格、额度、周期、退款、任务状态、保留期、隐私、角色、指标或法律文本。

- [ ] **Step 6：运行完整架构测试**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py
```

Expected: PASS；全部竞争路径已登记，已确认产品规则保持不变。

- [ ] **Step 7：提交清单与安全的状态更新**

```bash
git add docs/architecture/runtime-conflict-inventory.md docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md tests/architecture/test_authoritative_backend_policy.py
git commit -m "docs: inventory frozen legacy architecture paths"
```

---

### Task 4：验证 ADR 子项目并建立下一道门槛

**Files:**
- Modify: `docs/architecture/adr-0001-authoritative-backend-and-schema.md`

**Interfaces:**
- ADR-0001 如实记录已执行的离线验证。
- 下一子项目必须是 migration baseline reconciliation，而不是身份/机构或计费实现。
- 完成本计划不会改变任何线上环境状态。

- [ ] **Step 1：运行架构契约与现有离线回归检查**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py tests/unit/test_schema_initialization.py tests/api/test_legacy_job_routes.py
node --test tests/edge/jphouse-run-authority.test.mjs
node --check web/app.js
PYTHONPYCACHEPREFIX=/tmp/jppropdis-adr-pycache python3 -m compileall -q backend scripts src
git diff --check HEAD~3..HEAD
```

Expected: PASS。不得声称 SQL/RLS 行为、浏览器交互、fresh migration reset、linked Supabase 状态、backup/restore 或部署已测试。

- [ ] **Step 2：证明变更集与 dirty worktree 隔离**

Run:

```bash
git status --short
git diff --stat HEAD~3..HEAD
git diff HEAD~3..HEAD -- docs/architecture supabase/migrations/README.md backend/sql/README.md tests/architecture docs/superpowers/specs/2026-08-28-membership-billing-task-marketplace-design.md
```

Expected: 三个小提交仅包含本计划、ADR、policy manifest、policy test、migration ownership README、conflict inventory 和两行 spec header 变更；所有既有无关改动仍在这些提交之外。

- [ ] **Step 3：记录验证结果和下一硬门槛**

在 ADR-0001 的 `Verification` 中记录 Steps 1–2 的准确命令和结果，并添加：

```text
Next required plan: reconstruct and reconcile the Supabase migration baseline from an empty local database. Until it passes a fresh reset, schema assertions, anonymous/owner/other-user/service-worker RLS tests, drift comparison, and an approved backup/restore plus forward-fix procedure, no V1 membership, billing, task, contact-consent, or admin migration may be added.
```

保持 `migration_baseline_status = reconciliation_required`，不得声称 staging 或 production 与仓库一致。

- [ ] **Step 4：重新验证并提交验证记录**

Run:

```bash
python3 -m pytest -q tests/architecture/test_authoritative_backend_policy.py
git diff --check -- docs/architecture/adr-0001-authoritative-backend-and-schema.md
```

Expected: PASS。

Commit:

```bash
git add docs/architecture/adr-0001-authoritative-backend-and-schema.md
git commit -m "docs: verify authoritative architecture decision"
```

## Completion Criteria

- ADR-0001 只选择一个身份签发方、私有产品边界、数据存储、前向 migration 目录、webhook 边界和 durable worker 路径。
- 所有竞争运行路径与文档路径均已登记和冻结，且没有修改用户当前业务实现。
- migration baseline 缺口明确阻断 V1 schema 工作。
- 已确认产品规格已链接 ADR，且商业、隐私、任务和法律规则未改变。
- 架构策略测试与相关现有离线回归检查通过。
- 没有执行线上数据库、Auth、RLS、Storage、部署、DNS 或计费操作。
- 下一份实施计划是 migration baseline reconciliation。
