# Staging-safe 容量与性能验证计划

**日期：** 2026-09-01

**范围：** FastAPI 协调层、asyncpg pool 边界、intake 上传与反向地址适配器、旧报告任务路径、Render Free 唤醒、静态资源/CDN 和错误率预算。
**结论：** 本次只完成本地 synthetic 验证和可复现的 staging runbook。结果不能代表 staging 的 PostgreSQL、Render 或 CDN 实际容量，更不能代表 production。

## 安全门槛

- 默认探针不建立网络连接；`--local-fastapi` 使用进程内 ASGI transport，只访问本地 `GET /health/live`，不启动 FastAPI lifespan，因此不会连接数据库。
- 所有请求、文件、任务 ID 和地址都是 synthetic fixture；不读取或写入客户资料，不调用 GSI、Supabase Storage、Supabase Auth 或任何真实第三方站点。
- 当前没有执行 Render、Supabase、DNS、Storage、Auth、RLS、billing 或部署操作。任何 staging 远程检查都要先由负责人书面确认目标 hostname、时间窗、请求上限和回滚联系人；production hostname 必须被工具拒绝。
- 数据库 migration baseline 仍是 `reconciliation_required`。不以本计划替代 fresh reset、backup/restore、RLS 四身份验证或 migration drift 检查。

## 可复现工具与基线

探针位于 [`scripts/staging_capacity_probe.py`](../../scripts/staging_capacity_probe.py)，只使用 Python 标准库；本地 FastAPI 模式额外使用仓库已有的 `httpx`。测试位于 [`tests/performance/test_staging_capacity.py`](../../tests/performance/test_staging_capacity.py)。

使用已安装依赖的 Python 运行：

```bash
CAPACITY_PYTHON=${CAPACITY_PYTHON:-python3}
"$CAPACITY_PYTHON" -m pytest -q tests/performance/test_staging_capacity.py
CAPACITY_PYTHON=${CAPACITY_PYTHON:-python3}
"$CAPACITY_PYTHON" scripts/staging_capacity_probe.py \
  --local-fastapi \
  --output docs/operations/staging-capacity-baseline-YYYY-MM-DD.json
```

第二条命令中的日期应替换为运行日；不要把生产 URL 作为参数。探针默认配置为：100 个请求、并发 8、pool 模型 5、50 个数据库操作、队列容量 20/突发 40、错误预算 1%。当前输出保存在 [`staging-capacity-baseline-2026-09-01.json`](staging-capacity-baseline-2026-09-01.json)，历史输出保留在 `staging-capacity-baseline-2026-08-31.json`；两者均明确标记 `production_contacted=false` 和 `staging_contacted=false`。

### 本次本地 baseline

| 轨道 | synthetic workload | 实测结果 | 提议 guardrail | 状态 |
| --- | --- | --- | --- | --- |
| FastAPI | 本地 ASGI `/health/live`，100 请求、并发 8 | 100/100 成功；p50 `18.829ms`、p95 `33.011ms`、p99 `34.483ms` | p95 ≤ 250ms、p99 ≤ 500ms、错误率 ≤ 1% | 通过；这是 liveness 路由，不是 DB/API 业务容量 |
| DB pool | semaphore 模型，pool=5，50 操作，每项 10ms synthetic service | max in-flight `5`；acquire p95 `109.13ms`；0 错误 | acquire p95 ≤ 150ms；每进程连接上限 5 | 通过模型预算 |
| 任务队列 | 容量 20、40 个突发、1 worker、每项 10ms | 接受 20、拒绝 20、完成 20、峰值深度 20 | 队列必须有上限和明确 overflow policy | 通过“拒绝而不膨胀”模型 |
| 静态资源 | `web/`，排除生成的 `library/` 和 `.git/` | 43 文件、`1,963,542B`；最大 `assets/logoELE.png` `945,771B` | 总量 ≤ 2MiB；单文件 ≤ 512KiB | 单文件超预算，需修复 |

运行时延迟是本机单次测量，不能跨机器比较；重新运行应保留新日期文件，不能覆盖历史证据。队列拒绝是刻意的 backpressure 断言，不是丢失真实任务的许可。

## 验证矩阵与扩容阈值

### 1. FastAPI 并发与错误率预算

本地先用 `run_asgi_probe(app, "/health/live", requests=100, concurrency=8)` 验证请求调度、尾延迟和错误计数。业务路由（认证、DB、Storage、报告生成）不得用这个 liveness 结果外推；它们需要 staging synthetic fixture 和独立的数据库/Storage 配额。

提议 staging smoke（取得授权后才可执行）：

1. 预热一次 `/health/live` 和 `/health/ready`，确认服务版本、数据库 readiness 和日志 correlation ID；不发送业务写请求。
2. 以 synthetic 身份/fixture 做 100 次只读 health 请求、并发 8，记录 p50/p95/p99、HTTP 状态和 timeout；禁止把真实 token、邮箱或文件放入 fixture。
3. 只有在独立的 staging 数据库快照和批准的 synthetic API 流程就绪后，才增加 authenticated/intake 读写样本；每个样本使用可清理的唯一 synthetic ID。

错误预算统一为 1%：100 请求最多允许 1 个失败；`floor(total × 0.01)` 是允许失败数。任何 timeout、5xx、连接耗尽和错误响应都计入预算；429 只有在测试目标明确是限流时另行标注，不能从业务成功率中隐藏。

扩容/暂停阈值：连续 3 个相同窗口的 p95 > 250ms、p99 > 500ms、错误率 > 1%，或出现连接耗尽时暂停增加流量并检查 pool、Render CPU/内存和下游依赖。没有 profile/trace 的“感觉变慢”只记为 `NOT ASSESSED`。

### 2. DB pool

`backend/app/db.py` 当前调用 `asyncpg.create_pool(..., min_size=1, max_size=5)`；测试会断言这两个边界。synthetic semaphore 只验证 acquire 等待和上限，不验证真实 PostgreSQL 查询计划、连接数、锁或 RLS。

staging 需要同时记录：实例数、uvicorn worker 数、每进程 pool 上限、数据库 `max_connections`、reserved connections 和业务查询 p95。连接预算至少按 `实例数 × worker 数 × 5` 计算，并为迁移/管理连接留余量；不能只看单进程的 5。

扩容阈值：acquire wait p95 > 150ms 持续 3 个窗口、pool 使用率 > 80% 持续 5 分钟、出现 `TooManyConnections`，或 DB 查询 p99 超出业务 SLO。先降低并发/隔离慢查询，再批准增加实例或 pool；不得未经 DB owner 批准直接提高 `max_size`。

### 3. 上传大小与 timeout

当前 contract 和测试固定为：单文件最大 `20 MiB`，route 读取 `MAX_UPLOAD_BYTES + 1` 后在超限时返回 413，Storage `urlopen` timeout 为 8 秒；支持 PDF/JPG/PNG 和 magic bytes 校验。测试使用 `%PDF-` synthetic bytes，覆盖恰好 20MiB 接受、20MiB+1 拒绝和 timeout 参数，不上传真实文件。

这条路径会把每个文件暂存为 bytes；在并发 8、每个 20MiB 的最坏模型下，仅请求 body 就可能同时占用约 160MiB，尚未计入 multipart、Python、Storage 和数据库开销。没有 staging profile 前，不把这个上界当作实际 RSS。

取得 staging 授权后只做小规模、可清理的 synthetic 文件样本（例如 1KiB、20MiB、20MiB+1），并把并发限制在批准值；不要用真实合同、照片或 listing 内容。若 Storage timeout/5xx 达到 1% 错误预算，或 RSS/GC 持续上升，暂停测试并转为流式上传或独立 worker 设计评审。

### 4. Geocoder 限流与超时

`GsiReverseGeocoder` 的 provider timeout 被夹在 1–15 秒，默认 5 秒；响应上限 64KiB。intake route 对同一 session 的 `location_capture` 每小时限制 5 次，测试确认第 6 次返回 429 和 `Retry-After: 3600`。限流 key 只保存 HMAC，不保存原始 IP。

这不是 provider 配额证明：当前没有全局 geocoder concurrency limiter，也没有调用真实 GSI。staging 只可使用本地 fake provider；任何真实 provider 配额、条款、robots、隐私和速率上限都要由 owner 另行批准。若多个 session 同时打满线程池，按 provider 允许的并发和错误预算做 bulkhead；不能因为 429 就盲目提高应用限制。

### 5. 任务队列与 worker

`SyntheticJobQueue` 用容量 20、`reject` overflow policy 验证突发不会无限积压；现有 `scripts/run_jphouse_worker.py::claim_pending_job` 另有 conditional update 回归，确保两个 worker 不会同时 claim 同一 pending 行。

当前 `backend/app/main.py::query_report` 仍把长任务交给进程内 `BackgroundTasks`；这不是 durable queue，重启/休眠期间不能作为任务持久化保证。`scripts/run_jphouse_worker.py`、Edge Function 与 FastAPI executor 仍是竞争路径，ADR-0001 将它们标为冻结。故本次只报告风险，不改写业务队列：

- **Medium / Needs verification：** 在没有真实 profile、队列深度指标和 crash/restart 演练前，不能给 `BackgroundTasks` 赋予容量或可靠性 SLO。
- **扩容阈值：** canonical durable worker 设计获批后，backlog > 80% 容量、最老任务年龄超过目标 SLA、连续重试或 DLQ 增长即暂停接收并扩 worker；必须有幂等、有限重试、失败分类和可监控的 DLQ。
- **授权门槛：** 不在本次任务中迁移 queue、执行 Supabase 写入、清空旧 queue 或下线 Edge/legacy worker。

### 6. Render 休眠恢复

`render.yaml` 是 Free web service，`healthCheckPath=/health/ready`，没有本地 worker 或第二个 Render 数据库。Free service 的休眠/唤醒行为未在本机测量，本次 baseline 明确为 `NOT ASSESSED`。

取得明确 staging 部署和远程探测批准后，使用同一个 staging hostname 做低频人工记录：等待超过平台休眠窗口，依次测 `/health/live`、`/health/ready`，每次只发一个 GET，记录 DNS、TCP、TLS、TTFB、总时长、状态和 Render deploy/version。重复 5 个冷启动周期即可作为 smoke 样本；不要并发唤醒、不要调用写接口。提议门槛是冷启动 p95 ≤ 30s、5xx/timeout ≤ 1%，超出则评估付费实例、预热策略或异步 worker；门槛通过也不能当作 production SLO。

匿名 session 的 API 可立即拒绝过期记录，但 Storage 对象清理依赖下一次 API 唤醒；严格墙钟删除 SLA 仍需持续运行的清理机制，不能由本 smoke 推断已满足。

### 7. 静态资源与 CDN

本次本地 inventory 排除了生成的 `web/library/`，因为它由脚本拥有且可能随报告增长；发布前应分别统计入口页面依赖的 HTML/CSS/JS、图片和生成库。当前总量在 2MiB 总预算内，但 `assets/logoELE.png` 为 `945,771B`，超过 512KiB 单文件预算，是唯一已测得的静态 FIX 项。不要手工编辑生成库来“通过”预算。

Render static site 的实际 `Cache-Control`、`ETag`、`Age`、`Content-Encoding`、CDN provider 和 edge hit ratio 没有证据，列为 `NOT ASSESSED`。staging 获批后只对静态 GET/HEAD 取响应头和资源大小，分别冷缓存/热缓存记录；不把一次本地 `file://` 或开发 server 结果当 CDN 结论。

提议门槛：入口首屏静态字节 ≤ 1.5MiB、单文件 ≤ 512KiB、压缩传输可解释、无未版本化长期缓存；若 p75 LCP/INP/CLS 的真实 RUM 可用，再以现场数据决定 Web Vitals。当前没有现场数据，不声称通过 CWV。

## 审计 verdict

- **FastAPI liveness / synthetic pool / bounded queue：** 本地模型 `SHIP`，只表示探针和边界可运行。
- **静态交付：** `FIX`，最大 logo 文件超提议预算。
- **任务执行可靠性：** `FIX / Needs verification`，进程内 `BackgroundTasks` 和多条 legacy executor 路径没有可证明的 durable queue 容量。
- **Render wake、真实 PostgreSQL、provider quota、CDN/CWV、production 错误率：** `NOT ASSESSED`，没有安全授权或可复现证据。
- **整体：** `FIX`，不能据此宣称 staging 或 production ready；完成上述修复/授权/实测后再重跑日期化 baseline。

## Blocker 与后续输入

1. 需要负责人批准的 staging hostname、远程 GET 上限和时间窗；没有它就不执行 Render/CDN/数据库远程检查。
2. 需要可从空库重建的唯一 migration history、backup/restore 演练和 RLS 四身份 fixture；当前 `migration_baseline_status=reconciliation_required`。
3. 需要 canonical durable worker、队列深度/年龄/重试/DLQ 指标和重启演练；否则不能给报告生成吞吐或丢失率作承诺。
4. 需要静态图片压缩/拆分决定和 CDN/cache owner；在此之前保留 logo 超预算证据，不改生成资产。
5. 需要 staging-only synthetic Auth/Storage 测试数据清理方案；本次没有创建任何远程数据。
