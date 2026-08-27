# 小象避坑基础安全与数据底座实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为小象避坑第一阶段建立可追溯、可扩展且默认私有的数据底座，并修复用户项目、会员权限和数据来源的基础安全问题。

**Architecture:** 保留 Supabase 作为数据库和认证中心，使用标准化项目表承载住宅、预售/新建项目和商业项目投资的公共字段，使用详情表承载类型专属字段。原始文件、来源证据、法规版本、分析指标和用户消费事件分别建模；所有用户项目通过后端身份绑定，不再信任客户端邮箱或会员字段。

**Tech Stack:** Supabase/Postgres、FastAPI、Supabase Auth/RLS、现有静态 `web/` 前端、Python 测试工具。

**Spec:** `docs/data-warehouse-architecture.md`

## Global Constraints

- 用户原始项目资料默认仅本人、明确授权的客服/分析师和必要的 AI 服务可访问。
- 真实数据、用户提交数据、估算数据和测试数据必须通过 `data_class` 明确区分。
- 每个数据字段和分析结果必须保留来源、观察时间、可信度或计算版本。
- 不在本计划中实现无授权的商业网站大规模抓取。
- 法律内容只提供资料核对和交易前提示，不生成法律结论或收益承诺。
- 迁移前不得删除现有表或覆盖用户数据；所有 schema 变更必须可重复执行。

---

### Task 1: 建立统一数据字典和迁移边界

**Files:**
- Create: `backend/sql/001_foundation_data_contract.sql`
- Modify: `docs/data-dictionary.md`
- Test: `tests/sql/test_foundation_schema.sql`

**Interfaces:**
- Produces tables/types: `properties`, `residential_details`, `new_build_details`, `commercial_investment_details`, `sources`, `evidences`, `policy_documents`, `analysis_metrics`, `risk_findings`, `product_events`.
- Produces enum values: `verified_observation`, `scraped_aggregate`, `modeled_estimate`, `synthetic_fixture`, `user_submitted`.

- [ ] **Step 1: Write schema assertions**

在 `tests/sql/test_foundation_schema.sql` 中检查所有基础表存在、`properties.data_class` 具备约束、价格和面积字段有单位或币种字段、指标表包含 `calculation_version`，并确认详情表通过 `property_id` 唯一关联项目主表。

- [ ] **Step 2: Run the schema assertions against a disposable Postgres/Supabase test database**

Run: `psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql`

Expected: FAIL because `backend/sql/001_foundation_data_contract.sql` has not been applied.

- [ ] **Step 3: Add the idempotent migration**

在 `backend/sql/001_foundation_data_contract.sql` 中使用 `create table if not exists`、显式约束和索引建立上述表；所有金额字段使用 `numeric` 并同时保存 `currency`，所有观察型记录保存 `observed_at`，所有来源记录保存 `source_id` 和 `evidence_id` 可追溯关系。

- [ ] **Step 4: Update the data dictionary**

在 `docs/data-dictionary.md` 增加三类项目、数据分类、来源证据、法规版本、风险结果和消费事件字段定义，并注明哪些字段可用于公共聚合统计。

- [ ] **Step 5: Re-run the assertions**

Run: `psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/sql/001_foundation_data_contract.sql && psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/sql/test_foundation_schema.sql`

Expected: PASS with no destructive migration and all constraints present.

### Task 2: 修复私有项目的身份和 RLS 边界

**Files:**
- Create: `backend/sql/002_private_project_rls.sql`
- Modify: `backend/sql/supabase_schema.sql`
- Modify: `backend/sql/supabase_user_profiles.sql`
- Test: `tests/security/test_rls_private_projects.sql`

**Interfaces:**
- Produces policies that use `auth.uid()` and server-owned ownership fields.
- Produces database functions or triggers that prevent clients from changing `owner_user_id`, `membership_tier`, and `daily_query_limit`.

- [ ] **Step 1: Write RLS regression tests**

在 `tests/security/test_rls_private_projects.sql` 创建两个测试用户和两个项目，验证用户 A 不能读取、修改或删除用户 B 的项目、原始证据、报告和消费事件；匿名角色不能访问任何私有项目；普通用户不能修改自己的会员等级和查询额度。

- [ ] **Step 2: Run the regression tests before the migration**

Run: `psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/security/test_rls_private_projects.sql`

Expected: FAIL against the current permissive policies, documenting the existing exposure.

- [ ] **Step 3: Add ownership and policy migration**

在 `backend/sql/002_private_project_rls.sql` 中为私有表增加 `owner_user_id`、启用 RLS、删除匿名全表读写策略，使用 `auth.uid() = owner_user_id` 的 select/insert/update/delete 策略；插入和更新时禁止客户端覆盖所有权字段。

- [ ] **Step 4: Lock member-controlled fields**

修改 `backend/sql/supabase_user_profiles.sql` 的 update policy，使客户端只能更新昵称、头像等允许字段；会员等级、查询额度、封禁状态和审核字段只允许服务端角色更新，并记录变更时间。

- [ ] **Step 5: Re-run the security tests**

Run: `psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/sql/002_private_project_rls.sql && psql "$TEST_DATABASE_URL" -v ON_ERROR_STOP=1 -f tests/security/test_rls_private_projects.sql`

Expected: PASS; cross-user reads and writes return zero rows or permission errors.

### Task 3: 建立来源、原始快照和证据记录接口

**Files:**
- Create: `backend/app/services/provenance.py`
- Modify: `backend/app/main.py`
- Create: `tests/unit/test_provenance.py`
- Modify: `docs/data-warehouse-architecture.md`

**Interfaces:**
- `register_source(name: str, source_type: str, url: str, permission_status: str) -> Source`
- `save_snapshot(source_id: UUID, fetched_at: datetime, content: bytes, parser_version: str) -> Snapshot`
- `attach_evidence(property_id: UUID, snapshot_id: UUID, field_name: str, page_or_locator: str | None) -> Evidence`

- [ ] **Step 1: Write unit tests for hash stability and provenance fields**

测试同一内容产生相同 `content_hash`，不同内容产生不同哈希；测试来源、抓取时间、解析器版本和字段定位不能为空；测试未经授权的来源不能进入自动采集队列。

- [ ] **Step 2: Run the unit tests before implementation**

Run: `pytest tests/unit/test_provenance.py -q`

Expected: FAIL because `backend/app/services/provenance.py` does not exist.

- [ ] **Step 3: Implement the provenance service**

使用现有数据库连接方式写入 `sources`、原始快照和 `evidences`；原始内容保存对象存储引用和哈希，不把大文件直接塞入业务项目表；所有写入接受服务端生成的用户身份和项目 ID。

- [ ] **Step 4: Add a protected health/diagnostic endpoint**

在 `backend/app/main.py` 增加仅服务端可用的 provenance diagnostics，不返回原始文件内容，只返回来源状态、快照时间、哈希和解析器版本。

- [ ] **Step 5: Run tests and API checks**

Run: `pytest tests/unit/test_provenance.py -q && python3 -m compileall backend/app`

Expected: PASS; no raw document content appears in diagnostic responses.

### Task 4: 固定指标、风险和法规版本模型

**Files:**
- Create: `backend/sql/003_analysis_policy_versions.sql`
- Create: `backend/app/services/analysis_contracts.py`
- Create: `tests/unit/test_analysis_contracts.py`

**Interfaces:**
- `MetricResult(metric_name: str, value: Decimal | None, unit: str, calculation_version: str, assumption_set: dict)`
- `RiskFinding(category: str, severity: str, basis: str, required_evidence: list[str], action: str, confidence: str)`
- `PolicyDocument(policy_id: str, authority: str, effective_from: date, effective_to: date | None, source_url: str, status: str)`

- [ ] **Step 1: Write contract tests**

测试指标缺少单位、计算版本或假设集时拒绝保存；测试风险项必须有依据和行动建议；测试法规有效期重叠时拒绝同一政策的冲突版本。

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_analysis_contracts.py -q`

Expected: FAIL before contracts and validation are implemented.

- [ ] **Step 3: Add versioned tables and validation models**

建立法规文档版本、指标结果和风险结果表；禁止更新已用于报告的历史版本，新的政策或计算口径使用新版本号；校验结果明确返回字段错误而不是静默填充。

- [ ] **Step 4: Re-run contract tests**

Run: `pytest tests/unit/test_analysis_contracts.py -q`

Expected: PASS with invalid records rejected and valid records serialized consistently.

### Task 5: 建立 staging 部署和验证门槛

**Files:**
- Create: `render.yaml`
- Create: `backend/app/routes/health.py`
- Create: `tests/smoke/test_staging_contract.py`
- Modify: `README.md`

**Interfaces:**
- `GET /health/live -> {"status": "ok"}`
- `GET /health/ready -> {"status": "ready", "database": "ok", "version": "..."}`

- [ ] **Step 1: Write smoke checks**

测试健康接口返回正确状态，检查未配置生产密钥时应用拒绝启动敏感服务；检查静态页面可以加载但不会暴露 Supabase service-role key。

- [ ] **Step 2: Add Render staging configuration**

在 `render.yaml` 中只声明 staging Web Service 和静态站点；使用环境变量注入 Supabase anon key、API URL、环境名和报告开关，不声明 Render Postgres 或 Cron Job。

- [ ] **Step 3: Add health routes and safe startup validation**

实现 live/ready 两个接口；ready 检查数据库连接和迁移版本，错误响应不包含密钥、连接串或用户资料。

- [ ] **Step 4: Run local smoke checks**

Run: `pytest tests/smoke/test_staging_contract.py -q && node --check web/app.js && PYTHONPATH=src python3 -m jp_property_publisher --help`

Expected: PASS locally; staging-only variables are clearly documented.

- [ ] **Step 5: Deploy staging manually and verify**

在 Render 选择 Free Web Service/Static Site，使用测试 Supabase 项目和合成数据；验证首次冷启动、登录、私有项目隔离、健康检查和日志脱敏。不得导入真实客户文件。

## 验收门槛

只有 Task 1–4 的测试通过，且 staging 完成权限和日志验证后，才进入下一份计划：AI 文件解析、三类项目分析模型、法规更新任务和付费报告生成。正式生产部署前必须另外完成支付、删除请求、备份恢复、监控和法律文案审核。
