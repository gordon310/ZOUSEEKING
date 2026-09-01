# ZOU SEEKING HOUSE 后端部署方案

> 状态：暂缓方案（2026-08-27）。当前 staging 不创建 Render PostgreSQL；Render FastAPI 继续连接 Supabase staging 的 PostgreSQL、Auth 和私有 Storage。本文的 Render PostgreSQL 步骤不要用于当前 staging 部署，保留作未来迁移参考。

未来迁移目标（尚未执行）：

```text
GitHub Pages 前端
  -> Render FastAPI 后端
  -> Render PostgreSQL
```

当前 staging 架构：

```text
GitHub Pages / Render Static Site
  -> Render FastAPI
  -> Supabase staging Auth / PostgreSQL / private Storage
```

当前配置见根目录 `render.yaml`：`INIT_SCHEMA=false`，没有 `databases:`，`DATABASE_URL` 由 staging Supabase 提供。迁移到 Render PostgreSQL 前，必须另行完成 Auth、RLS、私有文件、备份恢复和 migration history 评估；不能只替换一个连接字符串。

## 1. 当前 staging 与未来迁移边界

当前 staging 使用仓库里的 `render.yaml` Blueprint，但只创建 Render
FastAPI/static service；`DATABASE_URL` 指向已批准的 Supabase staging，配置中
没有 `databases:`。本节的 Render PostgreSQL 只作未来 ADR 评估，当前不创建。

使用前先从仓库根目录运行只读 ownership 审计：

```bash
python3 scripts/check_schema_ownership.py
```

后端启动命令：

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 2. 当前必要环境变量

当前 staging Blueprint 使用：

- `DATABASE_URL`：Supabase staging connection string（Render secret）
- `INIT_SCHEMA=false`：禁止普通启动自动建表
- `ENVIRONMENT=staging`
- `ALLOWED_ORIGINS=https://gordon310.github.io,http://127.0.0.1:8790,http://localhost:8790`

`INIT_SCHEMA=true` 仅可在 disposable `local`/`development`/`test` 环境用于
legacy `backend/sql/schema.sql` compatibility；它不应用
`supabase/migrations/`，也不能作为 staging/production 建库方式。

当前 `migration_baseline_status = canonical_local_pass_live_reconciliation_required`。
在 provider backup/restore、drift、later-ID forward-fix 和明确 live-change
批准完成前，不执行 linked `db push`、`migration repair` 或 reset。

## 3. 前端连接后端

拿到 Render 后端地址后，例如：

```text
https://zouseeking-api.onrender.com
```

把 `web/config.js` 改为：

```js
window.ZOUSEEKING_API_BASE_URL = "https://zouseeking-api.onrender.com";
```

然后重新同步 GitHub Pages。

## 4. 查询保存逻辑

查询唯一索引：

```text
prefecture + city + ward + asset_type + year + month
```

同样条件再次查询时：

- PostgreSQL 有结果：直接返回历史数据
- PostgreSQL 没结果：创建 `generation_jobs`
- 后端先检查本地已有 `content-library.json`
- 命中本地历史数据：写入 PostgreSQL
- 没命中：先保存待生成占位记录和备用数据源

下一步要做真正自动采集时，把 `backend/app/jphouse_service.py` 里的占位生成逻辑替换成调用现有 JPHOUSE 抓取脚本即可。

## 5. 备用数据源思路

当前后端记录的备用源：

- SUUMO：租赁相场
- Tochidai：中古マンション成交相场
- LIFULL HOME'S：备用租赁/买卖相场
- At Home：备用房源检索
