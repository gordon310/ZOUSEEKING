# ADR-0002：暂不将 Supabase PostgreSQL 迁移到 Render PostgreSQL

**状态：Accepted（暂缓，非迁移批准）**

**日期：** 2026-09-01

**适用范围：** Render PostgreSQL 的未来可行性、容量/SLO 复盘、迁移门槛与回滚设计；不改变当前 staging 或任何 production 运行路径。

## 决策摘要

当前继续使用 Supabase PostgreSQL、Supabase Auth 和 private Supabase Storage。
staging 不等于 production；当前 staging 验收不能替代 production 证据。
Render PostgreSQL 只保留为未来候选，不执行迁移。当前配置中的 Render Blueprint
没有 PostgreSQL resource，`DATABASE_URL` 继续由环境 secret 提供；不得把未来评估
示例当作已创建的数据库。

当前事实与门槛状态：

```text
decision=defer
render_postgres_migration=not_approved
staging_path=unchanged
production_evidence=not_assessed
live_write_approval=required
production_reset=forbidden
```

这是一项可逆的文档决策，不是 provider、部署、DNS、billing 或数据库变更授权。

## 1. 当前架构与容量证据

```text
Browser
  -> Supabase Auth（注册、登录、刷新、登出）
  -> 静态内容与公开只读 options
  -> FastAPI（私有/认证业务边界）
       -> asyncpg -> Supabase PostgreSQL
       -> service-side client -> private Supabase Storage
```

本地可核对的边界：

| 边界 | 仓库证据 | 迁移含义 |
| --- | --- | --- |
| Render 拓扑 | `render.yaml` 只有 staging API/static service，没有 `databases:`，且 `INIT_SCHEMA=false`。 | 当前 staging 不拥有 Render PostgreSQL。 |
| 身份 | `backend/app/auth.py` 将 bearer token 交给 Supabase Auth `/auth/v1/user` 校验。 | 迁移 DB 不会迁移 Auth issuer、session、refresh、revoke、reset 或 MFA。 |
| 连接 | `backend/app/db.py` 的 asyncpg pool 为 `min_size=1`、`max_size=5`。 | 连接预算必须按 API/worker 进程数、管理连接和余量重新测量。 |
| Schema | `supabase/migrations/` 是唯一 forward history；启动时 legacy schema 仅允许 disposable local/dev/test compatibility。 | Render 目标不能靠启动初始化或替换连接串建库。 |
| RLS | 现有 policies 使用 `auth.uid()`、Supabase roles 和 service-role 语义。 | 裸 Render PostgreSQL 不会自动提供 Supabase claim context、roles 或 helper。 |
| Storage | `backend/app/intake/storage.py` 使用 Supabase service key 访问 private bucket。 | 数据库备份不包含对象；必须另行证明对象 checksum、保留期和恢复关联。 |
| 任务 | 旧区域报告仍有 `BackgroundTasks`、Edge/local worker 和 FastAPI executor 竞争路径。 | 迁移期间的 backlog、重试、幂等和 rollback 不能靠 URL 切换解决。 |

当前 C21 容量 baseline 只覆盖本地 synthetic ASGI、pool、bounded queue 和静态
inventory；它没有生产流量、真实 PostgreSQL saturation、Render cold start、CDN
headers 或生产错误率证据。`web/assets/logoELE.png` 的 945,771B 单文件超出提议的
512KiB 预算，保持 `FIX`，不手工修改生成资源。

## 2. 必须分别通过的评估轴

### 2.1 Supabase Auth continuity

需要验证注册、登录、刷新、登出、密码重置、邮箱确认、账户删除、token 失效、
MFA/provider callback 和用户 UUID 映射。保留 Supabase Auth 时，Render DB 仍需定义
受信任的 user id 注入；替换 Auth 时，必须证明密码/会话迁移和强制重新登录行为。
不能把 `auth.users` 当作普通业务表复制后宣称 Auth 已迁移。

### 2.2 `auth.uid()`、RLS 与 grants

必须在 anonymous、owner、other authenticated user、service worker 四类身份上
分别验证 select/insert/update/delete、owner 字段不可伪造、server-managed quota
不可提升和 grants/policies 组合。候选实现只能二选一：

1. 在非 `BYPASSRLS` 角色上建立经过评审的 claim contract，每个 transaction 以
   transaction-local 设置传递已验证 user id/role，并测试 PgBouncer transaction pooling；
2. 由 FastAPI 作为唯一授权边界，DB role 不向客户端开放，同时证明 RLS 仍是有效的
   defense-in-depth。

前端隐藏、查询参数和 client-supplied email 都不是授权控制。

### 2.3 Private Storage

必须定义 bucket policy、signed URL/service key 边界、对象 checksum、metadata、
retention、删除重试、孤儿对象和 DB restore 点的对象清单。Render PostgreSQL 的
备份/恢复不能自动恢复 Supabase private Storage；替换对象存储还需要单独的加密、
生命周期、跨地区和回滚设计。

### 2.4 备份、恢复与 RPO/RTO

候选 provider 计划必须在脱敏 fixture 或隔离副本上测出：RPO、RTO、备份保留期、
PITR/逻辑导出、restore 校验、失败后的 forward-fix、DB/对象一致性和演练频率。
单一 PITR 或 provider snapshot 不能替代 off-site 备份与恢复证明；Free plan 的
表面费用也不能被当作 production recovery 方案。

### 2.5 跨地区、隐私与数据地图

需要确认 Supabase/Render API/DB/Storage 的实际 region、数据主体位置、跨地区
传输、处理者/DPA、保留和删除告知。region 选择是工程和数据位置决策，不是自动的
合规结论；没有 production data map 前保持 `NOT ASSESSED`。

### 2.6 连接池与 PgBouncer

连接预算按以下公式复测，而不是猜测：

```text
direct_connections = 5 × (asyncpg API processes + asyncpg worker processes)
                     + migration/admin/health headroom
```

若采用 Render PgBouncer transaction pooling，必须测试 transaction-local claim、
重连、timeout、retry、failover，以及所有依赖 session state、temporary table、
`LISTEN/NOTIFY` 或 session advisory lock 的代码。连接池不是授权控制。

### 2.7 成本与停机窗口

重新评估时必须读取当日官方价格并计入 workspace、API/worker、Postgres compute/
storage、HA/replica、备份导出、对象存储、egress、build 和 10–20% headroom：

```text
monthly_total = workspace + API/worker + Postgres + storage
              + HA/replica + backup/object storage + egress
              + build/pipeline + recovery/capacity headroom
```

还要在同规模隔离目标测得最终同步和验证耗时，取得业务批准的停机窗口、write-freeze、
通知、change owner 和 rollback window。没有这些数字时 `cost_gate=unconfirmed`、
`downtime=unmeasured`。

### 2.8 回滚、forward-fix 与 dual-write 风险

迁移不是替换 `DATABASE_URL`：

1. 先在隔离目标完成 schema、Auth/RLS/Storage、备份恢复、连接和应用 smoke；
2. 在批准的 freeze 窗口停止旧 worker/API 写入，完成最终同步并核对行、约束、RLS 和对象；
3. 只在验证通过后切换 secret，保留旧源只读直到 rollback window 结束；
4. 目标一旦接受新写入，回滚必须先做冲突检测、replay 或 later-ID forward-fix，不能盲切旧连接串。

逻辑复制、CDC、双写和 `pg_dump` 只是候选技术，不构成已通过的方案；没有规模、
冲突和 source capability 证据时不承诺 zero-downtime。

## 3. 方案比较

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| A. 继续 Supabase PostgreSQL/Auth/Storage | 当前推荐 | 保留 Auth、`auth.uid()`、RLS、private Storage 和现有 FastAPI 边界，仍需完成 baseline、恢复和 worker 证据。 |
| B. 业务 DB 迁移 Render，Auth/Storage 保留 Supabase | 当前拒绝 | 必须重建 identity mirror/claim context、RLS grants、DB/对象恢复关联，并承担跨区 RTT/egress。 |
| C. 完全离开 Supabase | 当前拒绝 | 需要替换 Auth、RLS、Storage、恢复、删除和合规边界，仓库没有生产规模实现或证据。 |

## 4. 不迁移条件

以下任一条件成立，结论保持 defer：

| 条件 | 当前状态 |
| --- | --- |
| 当前仅为 `canonical_staging_reconciled_production_pending`，没有 production baseline/restore 证据 | **BLOCKED** |
| Auth issuer、用户映射、token/revocation/reset/MFA 未书面确定并测试 | **BLOCKED** |
| `auth.uid()`/claim、grants、owner/RLS 四身份矩阵未通过 | **BLOCKED** |
| DB 与 Storage 的备份、恢复、checksum、retention 和删除关联未演练 | **BLOCKED** |
| region、跨地区处理、DPA、生产 data map 未批准 | **NOT ASSESSED** |
| RPO/RTO、连接预算、PgBouncer、failover/reconnect 未实测 | **NOT ASSESSED** |
| rollback 只能靠切回连接串，或目标已有写入却没有冲突/forward-fix | **BLOCKED** |
| 成本、HA/replica、egress、对象/备份、worker 总账未重新报价或超过批准预算 | **UNCONFIRMED** |
| 停机窗口、change owner、监控和用户通知未批准 | **UNMEASURED** |

## 5. 本次安全边界与重新开启顺序

本次不执行以下动作：

- 不得更换 `DATABASE_URL`、Supabase secrets 或前端 API 配置；
- 不得创建 Render PostgreSQL、Supabase project、Auth user 或 Storage bucket；
- 不得迁移数据、双写、复制、restore、backfill、`db push` 或执行生产 SQL；
- 不执行线上数据库、Auth、RLS、Storage 或部署操作，也不修改 DNS 或 billing。

重新开启只能按以下顺序：只读 inventory → disposable target rehearsal → Auth/RLS/Storage
矩阵 → 备份/恢复与容量演练 → cutover/rollback 批准 → 分阶段 shadow/read-only →
受控写入与 post-cutover evidence。任何一步缺证据都回到 defer。

官方资料入口（每次重新评估时重新核对）：

- [Render PostgreSQL Recovery and Backups](https://render.com/docs/postgresql-backups)
- [Render PostgreSQL connection pooling](https://render.com/docs/postgresql-connection-pooling)
- [Render regions](https://render.com/docs/regions)
- [Render free instance limitations](https://render.com/docs/free)
- [Supabase Auth architecture](https://supabase.com/docs/guides/auth/architecture)
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase Storage access control](https://supabase.com/docs/guides/storage/security/access-control)

相关入口：`docs/render-postgres-deploy.md`（[Render PostgreSQL 未来迁移评估](../render-postgres-deploy.md)）、
[ADR-0001](adr-0001-authoritative-backend-and-schema.md)、
[schema ownership audit](schema-ownership-audit.md)。
