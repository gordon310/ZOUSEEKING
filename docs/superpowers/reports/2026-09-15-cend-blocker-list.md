# 小象避坑 C 端 — 卡点清单(2026-09-15 批次,含 live 验证结果)

> 规则:**已测试过的流程不再重复测试**;每个卡点必须带证据、定位根因、标记状态。
> 代码基线:`main == origin == a43135d`(Lightsail 已部署,api 容器已重建,`/health/ready` = ready)。

## 一、本批次修复(已上线 + 已 live 验证)

| # | 卡点 | 根因 | 修复 | 状态 |
|---|---|---|---|---|
| **B1** | 报告**从未产出过 `full_report`**,前端永远「资料不足」,付费入口不可见 | 触发器 `enforce_published_source_rights` 要求 `source_id` 指向 `rights_confirmed` 来源;而 `public.sources` **0 行**、生成路径又未设置 `source_id` → 每次插入抛 `published property_reports requires an authorized source` → 任务 `failed` | forward migration `20260915000100` 登记国土交通省 土地総合情報システム(`rights_confirmed`);生成路径绑定来源 | ✅ 已上线,已 live 验证 |
| **B2** | **第二个用户查同一地区+类型必失败** | `property_reports.slug` 全局唯一,而 slug 由「地区+类型」派生、不含用户 → `duplicate key value violates unique constraint "property_reports_slug_key"` | slug 加 owner 命名空间 + migration `20260915000200`(`unique(owner_user_id, slug)`) | ✅ 已上线,已 live 验证 |
| **B3** | 来源 id 写死在代码里 | `os.getenv("JPHOUSE_MARKET_SOURCE_ID", "<uuid>")` 默认值即硬编码 | 运行时按 `sources.url` 从库解析 + 60s 缓存;解析失败落结构化错误 | ✅ 已上线,已 live 验证(SQL 实测解析到 `bf4b6d56-…`) |
| **B4** | 用户**永久卡死**:报告停在 `generating`、页面无入口、无报错 | 缓存状态机漏分支(终态任务 + 未发布报告被判为「等待中」) | 终态任务 + 未发布报告 → `requeue`;`insufficient_data` 仍走缓存 | ✅ 已上线,已 live 验证(僵尸态 requeue → `full_report`) |

### live 验证证据(C 端真实请求形状)

请求体(**取自前端真实字段**:`prefecture="东京都"`、`city="港区"`、`ward="__not_subdivided__"`、`asset_type="塔楼"`):
```json
{"prefecture":"东京都","city":"港区","ward":"__not_subdivided__","asset_type":"塔楼","year":2026,"month":8}
```

| 项 | 结果 |
|---|---|
| V1 两个不同账号同一地区 | 两次 `POST /api/query` → HTTP 200 → job `completed` → **`report_status=full_report`**;slug 分别为 `<uid-a>_jphouse_jphouse_23ku_港区_塔楼` 与 `<uid-b>_…`,**owner 前缀隔离成功** |
| V2 来源解析 | 解析 SQL 实测 → `bf4b6d56-f7ed-4e66-b599-3900e22001d6`;`sources` 验证前后均为 **1 行**;单测 `10 passed` |
| V3 僵尸态自愈 | 人为造 `report_status='generating'` + job `completed` → 真实 `create_or_get_query_job` 重新排队 → job `completed` → **`full_report`** |
| V4 清理与配额 | 六类残留计数全 **0**;`gordon310103@gmail.com` 配额未被消耗(名下 `query/2026-09=1/30` 是**用户本人**测试产生) |
| V5 未执行 | ① 浏览器 UI 点击级回归(NOT_EXECUTED)② Render staging 入口(已 suspend)③ commit/push/部署(按任务禁止) |

### ⚠️ 一次假阴性教训(重要,避免重复劳动)
第一轮 live 验证报「两个账号都只得 `insufficient_data`」——**结论不成立**:它自拟的请求体是
`{"prefecture":"東京都","city":"東京都","ward":"港区"}`,而 C 端真实字段是
`{"prefecture":"东京都","city":"港区","ward":"__not_subdivided__"}`(`prefecture` 用**简体中文**、`city` 在「都」这一层直接是区)。
`match_snapshot` 的 `prefecture` 是精确相等比较,故必然不匹配。
**规矩:验证 C 端接口的请求形状必须取自 `web/field-options.json` + `web/js/property-intake.js`,不得凭直觉拼字段。**
（同时确认线上环境数据侧正常:容器内 `load_snapshots()` = **64 条**。)

## 二、账号注销(N1)已实施并 live 验证通过

**问题**:`usage_events` append-only + 外键 `ON DELETE SET NULL` → `DELETE FROM auth.users` 被触发器挡下(实测 `usage_events is append-only; update is forbidden`),用户点注销会失败。

**方案(已批准)**:受控删除 = 软删除 + 匿名化;不拆 append-only 保护、不硬删 `auth.users`。

| 项 | 结果 |
|---|---|
| 台账 `account_deletion_requests` | 新建(forward migration `20260915000300`),RLS 仅属主可读、`ON DELETE RESTRICT` |
| `POST /api/account/deletion-request` | **HTTP 202**;回执**只含白名单 9 个字段**;SLA 24h/24h/30d/90d 全部正确 |
| 会话吊销 | 提交后旧 access token 调用受保护接口 → **401**(账号 `banned_until` 置为远期) |
| PII 清除 | `auth.users.email` → `deleted+<uuid>@invalid`;`user_profiles` 邮箱/显示名等清空、配额置 0 |
| 账本保留 | `auth.users` 行**仍存在**;`usage_events` 行数与内容**未变** |
| 清理 | 8 类残留计数全 0;过程中未删除任何既有线上数据 |
| **B5 幂等** | ⚠️ 无法通过公开接口断言:第一次请求即执行全局登出,旧 token 再提交必然 401(`request_id` 一致性无法用公开路径验证)。**不是缺陷**,已在报告标注 |

### ⚠️ 本轮事故(必读)
N1 首次发版引入**线上 500 回归**:`backend/app/auth.py` 的 `require_user()` 把 token 传给了不存在的变量名 →
`NameError: name 'access_token' is not defined` → **所有带登录态的接口 500**(匿名页面不受影响),持续约 **19 分钟**,已回滚到 `6fbb528` 恢复。
**为什么没测出来**:520 个 Python 测试全绿——测试普遍**覆盖了 `require_user` 依赖**,这条路径从未真正执行;前几轮 live 验证也只打了未鉴权路径。
**修复**:变量名统一 + 新增「**不覆盖依赖、真实跑 `require_user`**」的回归测试(修复前 2 failed 已复现)+ `/api/me` 的 TestClient 冒烟测试;修复后 `525 passed, 86 skipped`。
**已重新部署并复验**:`GET /api/me` 200、`POST /api/query` 200 → job `completed` → **`full_report`**(真实成交数据,港区塔楼,来源=国交省)。

**教训(已写入技能)**:「测试全绿」不等于「路径被执行」——发版前必须对**真实请求**做一次冒烟,尤其是被依赖覆盖 (dependency override) 包裹的鉴权/中间件路径。

## 三、待你决策 / 待处理

| # | 项 | 状态 |
|---|---|---|
| **N1** | 用户注销(上线前合规项) | ✅ **已完成**:受控删除执行器已上线并 live 验证通过(见第二节) |
| **N2** | AWS SES 退沙盒审核 | 待用户告知结果(注册邮件仍 2 封/时,是上线硬依赖) |
| **N3** | 4 行历史僵尸报告(`generating`,分属 `1114513@qq.com` 与测试账号 p2test) | 修复后会在对应账号下次查询时自愈;**本批次未删任何数据**,如需清理先给清单待批 |
| **N4** | 早班/夜班自主班次与人工会话并发写同一仓库 | 本轮发生过(早班 07:40 起两次派 codex,与 live 验证并发) → 已临时暂停早班、终止并发派工,验证完成后已恢复;后续人工会话期间建议先暂停班次 |

## 三、已知未修(不阻塞本次链路)

| # | 项 | 状态 |
|---|---|---|
| **C1** | Release Gate CI 红 | ✅ **已修复**:Playwright 断言漂移 **22 failed → 0 failed**(本地 `81 passed`,CI 同命令);同时修了新增表导致的 `sql-m1` 授权计数基线(authenticated 23→24、service_role→CI 实测 **339**)。最新 run **34918209738 七个 job 全绿** |
| **C2** | `location` 接口要求 `accuracy_m`,直接调 API 会 422(前端流程不受影响) | 待确认前端是否总是传全 |
| **C3** | `pip check` 报缺 `packaging`(环境项,非产品缺陷) | 已记录 |
| **C4** | 迁移未录入 `supabase_migrations.schema_migrations`(2026091x 起的历史实践即如此) | 卫生项,建议后续统一 |
| **C5** | 4 个 SQL 测试文件**从未进 CI**(`test_analysis_query` / `test_exports_query` / `test_member_query` / `test_realtime_quota_migration_additive`)—— 该仓库每个 `tests/sql/*.sql` 都要显式登记 step + 两处 `REQUIRED_CHECKS`,漏登记即零拦截(本轮新增的 `test_account_deletion_requests` 已按规范接入) | 待派工补齐(注意:这些文件从未在 CI 跑过,可能已过期) |
| **C6** | 注册邮件的**备份到期(90 天)作业**是否存在,未验证 | 待确认 |

## 四、部署与回滚

- 部署:push → 服务器 `git checkout -- . && git pull` → `docker compose -f deploy/docker-compose.prod.yml up -d --build api`;nginx 未改。
- 线上库变更:① 追加 1 行 `sources`(可 delete 回滚)② 替换 `property_reports` 的 slug 唯一约束(可回滚为 `unique(slug)`)。
- 回滚:服务器 `git checkout <上一提交>` 后重建 api 容器;DB 侧见对应 migration 的反向语句。
