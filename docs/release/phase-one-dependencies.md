# 第一阶段依赖清单

**范围：** `consumer_intake_preview`，只含 C 端匿名 intake 与免费预览。

**当前判定：** 本地冻结机制已落地；production release 仍为 BLOCK，未授权任何 live 操作。

## 1. 运行时依赖

| 依赖 | 用途 | 仓库契约 | 当前状态 |
| --- | --- | --- | --- |
| Python 3.12 | FastAPI runtime | `render.yaml` 的 `PYTHON_VERSION=3.12.11` | staging 配置存在；production 未确认 |
| FastAPI 0.116.1 / Pydantic 2.11.7 | HTTP 与输入契约 | `backend/requirements.txt` | 版本固定 |
| asyncpg 0.30.0 / PostgreSQL | intake transaction 与查询 | `DATABASE_URL` secret | staging 有历史验收；production 未配置/未授权 |
| Supabase private Storage | PDF/JPG/PNG 私有对象 | `INTAKE_BUCKET=property-intake`，20 MiB | staging 有历史验收；production 未创建/未授权 |
| Supabase Auth | ADR-0001 唯一身份签发方 | 第一阶段不开放 `/convert`，不把账号转正列入验收 | production lifecycle 未验收 |
| GSI reverse geocoder | 用户明确同意后的可选地址候选 | 超时/失败退化为保留坐标和手工地址 | 外部可用性与条款需复核，不得作为核心 readiness |
| Render API + static site | 当前 staging hosting | `render.yaml` | 只声明配置，不代表 production deploy 获批 |

## 2. 必需配置

| 配置 | 要求 | 失败行为 |
| --- | --- | --- |
| `ENVIRONMENT` | `staging` 或 `production` 明确设置 | managed 环境缺少 phase 时业务 API fail closed |
| `RELEASE_PHASE` | 第一阶段精确为 `consumer_intake_preview` | 未知/缺失时仅 health/diagnostics |
| `DATABASE_URL` | secret，最小权限，连接目标须复核 | readiness 503 |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | 只供 FastAPI 验证 Auth | 不得写入前端 production bundle |
| `SUPABASE_SERVICE_ROLE_KEY` | 只存在 server secret | 不得记录、回显或下发浏览器 |
| `INTAKE_BUCKET` | `property-intake`，private | 文件上传 503，不得降级到公开 bucket |
| `ABUSE_HASH_SALT` | 独立 secret | 非 test 环境限流键缺失时 503 |
| `ALLOWED_ORIGINS` | 只列实际 C 端 origin | 不使用通配符扩大 credentialed CORS |
| `ZOUSEEKING_API_BASE_URL` | C 端静态发布时注入经批准的 FastAPI origin | 仓库默认空值；未配置时生产 intake 不可用 |

`INTERNAL_DIAGNOSTICS_TOKEN`、provenance 状态字段属于可选运维依赖；未配置时 diagnostics 返回 404。前端 release config 不固定任何 Supabase 项目 URL，避免把 staging 依赖带入正式发布物。

## 3. 数据与安全依赖

- `supabase/migrations/` 必须成为可从空库重建的唯一 migration history；当前 `reconciliation_required` 是 production blocker。
- 必须分别验证 anonymous、owner、other authenticated user 与 privileged worker 的表和 Storage 访问。
- 必须有 production backup/restore、forward-fix、保留期和删除流程；staging synthetic smoke 不替代这些验证。
- 必须确认隐私文本、同意版本、上传用途、禁止内容、删除入口和事故响应负责人。
- 生产样本不得使用真实个人资料，直到上述门槛通过并获得明确的受控验收授权。

## 4. 构建与离线验证依赖

- Python 3.12 测试环境；`backend/requirements-dev.txt` 固定 `pytest`、`pytest-asyncio`、`httpx` 和 worker 测试导入所需的 Pillow。
- Node.js 与 `npm ci`，以 `package-lock.json` 安装 Playwright。
- Chrome/Chromium channel，用于 `390x844`、键盘、控制台和网络副作用验证。
- SQL/RLS 测试需要隔离 PostgreSQL/Supabase 环境；不得指向 production。

## 5. 明确排除或冻结的依赖

- `supabase/functions/jphouse-run`：默认 410；不是第一阶段运行时依赖。
- `scripts/run_jphouse_worker.py`：默认在读取凭证前退出；不是第一阶段 worker。
- FastAPI `BackgroundTasks` 区域报告执行器：release phase 阻断；不是 durable worker。
- 浏览器 authenticated PostgREST：B/admin 网络边界阻断；不是业务 API。
- 会员、计费、机构、额度、订阅、导出、任务、管理员写操作：只有 `synthetic_fixture` UI，不得配置真实 provider 或 secret。
- `scripts/sync_content_library_to_supabase.py` 等 live 同步脚本：不属于第一阶段请求链路；运行它们仍是独立 live mutation，必须另行明确授权。
