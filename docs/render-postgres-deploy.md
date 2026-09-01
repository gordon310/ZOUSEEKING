# Render PostgreSQL 未来迁移评估

> 状态：暂缓（2026-09-01）。本文件是 [ADR-0002](architecture/adr-0002-render-postgres-future-migration.md) 的非执行入口，不是当前 staging 或 production 的部署 runbook。

## 当前路径（保持不变）

```text
GitHub Pages / Render Static Site
  -> Render FastAPI staging
  -> Supabase staging Auth / PostgreSQL / private Storage
```

根目录 [`render.yaml`](../render.yaml) 目前只声明
`zouseeking-api-staging` 和 `zouseeking-web-staging`，并设置
`ENVIRONMENT=staging`、`INIT_SCHEMA=false`、`DATABASE_URL sync: false`。
其中没有 `databases:`；因此 **Blueprint 不会创建 PostgreSQL**，也不能把未来评估
示例当作当前资源清单。staging 不等于 production。

## 安全边界

本评估只允许读取源码、SQL、配置、仓库文档和官方公开资料，并编写离线测试/文档。
在取得针对确切环境和操作的明确授权前：

- 不得更换 `DATABASE_URL`、Supabase secrets 或前端 API 配置；
- 不得创建 Render PostgreSQL、Supabase project、Auth user 或 Storage bucket；
- 不得迁移数据、双写、复制、restore、backfill、`db push` 或执行生产 SQL；
- 不执行线上数据库、Auth、RLS、Storage 或部署操作，也不修改 DNS 或 billing。

## 结论

当前不迁移。Render PostgreSQL 只保留为未来候选；在 migration baseline、Supabase
Auth issuer/用户映射、`auth.uid()`/RLS、private Storage、备份恢复、跨地区处理、
连接池/PgBouncer、回滚、成本和停机窗口全部通过隔离环境证据前，结论保持：

```text
render_postgres_migration=not_approved
live_write_approval=required
production_reset=forbidden
```

明确的不迁移条件和方案比较见 [ADR-0002](architecture/adr-0002-render-postgres-future-migration.md)。

## 只读复评顺序

1. 核对 staging/production 的 schema、migration IDs、region、对象清单、规模和数据地图；不得把 staging 结果外推。
2. 在 disposable target 复现 migration candidate、extensions、roles、grants、RLS claim contract 和四类身份矩阵。
3. 在脱敏副本演练 logical restore/PITR、对象 checksum/retention、连接耗尽、PgBouncer transaction semantics、failover/reconnect 和应用 smoke。
4. 形成含 write-freeze、最终同步、验证、rollback window、change owner、监控和用户通知的 cutover 方案；另取明确线上授权后才可执行。

当前容量证据见 [`docs/operations/staging-capacity-validation.md`](operations/staging-capacity-validation.md)，
上线后 SLO 复盘门槛见 [`post-launch-slo-review-2026-09-01.md`](operations/post-launch-slo-review-2026-09-01.md)。

## 官方资料（重评时重新核对）

- [Render PostgreSQL Recovery and Backups](https://render.com/docs/postgresql-backups)
- [Render PostgreSQL connection pooling](https://render.com/docs/postgresql-connection-pooling)
- [Render regions](https://render.com/docs/regions)
- [Render free instance limitations](https://render.com/docs/free)
- [Supabase Auth architecture](https://supabase.com/docs/guides/auth/architecture)
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase Storage access control](https://supabase.com/docs/guides/storage/security/access-control)
