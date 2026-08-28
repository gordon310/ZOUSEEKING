# ZOU SEEKING HOUSE Supabase 免费版接入

这条路线适合当前阶段：

```text
GitHub Pages 前端
  -> Supabase PostgreSQL 保存查询索引和历史结果
  -> 本地/后端 JPHOUSE 生成器补数据
```

单项目分析的 staging 路径与旧区域查询分开：

```text
Render FastAPI
  -> Supabase Auth / PostgreSQL / 私有 Storage
```

`property-intake` bucket 必须保持 private，浏览器不直接访问或写入项目资料。FastAPI 使用 `SUPABASE_SERVICE_ROLE_KEY` 生成上传和删除请求；该 key 的实际值只能配置在 Render secret 或本地环境变量中，不能写入 `render.yaml`、`web/config.js` 或日志（`render.yaml` 只声明 `sync: false`）。文件上传限制为 PDF/JPG/PNG、单文件 20 MiB，匿名会话创建后 24 小时到期。阶段一只保存资料元数据并等待人工确认，不执行 OCR 或 AI 提取。

当前 staging 使用 Render Free web service 的机会式清理：匿名会话在数据库中过期后立即不能再通过 API 读取，实际 Storage 对象会在 API 启动或下一次会话创建时，按每次最多 100 个会话清理。Free service 休眠期间不会主动执行清理；如果公开上线要求严格的墙钟删除 SLA，需要另行配置持续运行的定时清理机制。

## 1. 创建 Supabase 项目

1. 登录 Supabase。
2. New project。
3. 选择 Free 计划。
4. 记下：
   - Project URL
   - anon public key
   - service_role key（只给本地同步脚本或 Render API secret，不要放到前端）

## 2. 建表与 migration 边界

当前仓库仍有一段历史 bootstrap schema 尚未回填到 Supabase migration history：

- `backend/sql/supabase_schema.sql`、`backend/sql/supabase_user_profiles.sql` 和 `backend/sql/001–003` 只作为已有 staging 的恢复/bootstrap 脚本保留；不要在托管环境中单独重复执行。
- 新的 forward migration 统一放在 `supabase/migrations/`。`20260827000500_legacy_private_data_rls.sql` 会移除旧的匿名私有表权限，并将区域报告表改为“登录用户只读本人、写入由受信任后端负责”。
- 房屋照片定位和调查记录命名使用 `20260828000100_property_photo_location.sql`；它只扩展 FastAPI intake 所需字段、约束和 owner-scoped 索引，不应编辑已有 migration。2026-08-28 已将它与 `20260827000500_legacy_private_data_rls.sql` 应用到 `zoubeacon-staging`，production 未执行。
- 现有 `backups/zoubeacon-staging-20260825/restore_supabase.sql` 是旧恢复包，不等同于完整 migration history；使用前必须确认它已包含最新 RLS migration，绝不能直接用于生产数据库。
- 当前 staging 的历史 bootstrap schema 尚未完全回填到仓库 migration history；本次已验证 schema/RLS 断言，但完整备份恢复演练和四类身份行为测试仍需单独完成。

房屋照片定位的默认反向地址服务由 FastAPI 调用日本国土地理院 `LonLatToAddress`。服务端可配置：

- `REVERSE_GEOCODER_URL`：地址服务 endpoint；默认使用 GSI，切换前先审核供应商条款和隐私要求
- `REVERSE_GEOCODER_TIMEOUT_SECONDS`：请求超时，应用限制在 1–15 秒，默认 5 秒

用户拒绝定位、设备不支持定位或地址服务不可用时，坐标不会阻断 intake；页面保留手工填写地址入口。GSI 返回值只作为候选地址，最终的 `address_normalized` 必须来自用户确认/修正。

旧区域报告基础表包括：

这会创建：

- `queries`：用户查询索引
- `query_field_options`：首页查询字段选项，控制都道府县 / 市 / 区 / 房型 / 年 / 月
- `generation_jobs`：生成任务进度
- `property_reports`：生成后的房产数据和 Markdown
- `data_sources`：数据源记录

如果表已经建好，只想补首页查询字段，复制并执行：

```text
backend/sql/supabase_field_options.sql
```

现在已内置完整日本行政区划字段库：

- 47 个日本都道府县
- 1746 个市区町村
- 20 个有行政区的政令指定都市
- 171 个行政区
- 房型：塔楼 / 公寓 / 一户建
- 年份：2024-2027
- 月份：1-12月

字段库来源：`nojimage/local-gov-code-jp` 整理的总务省全国地方公共団体コード JSON。生成脚本：

```text
scripts/build_japan_field_options.mjs
```

如果表已经建好，只想补查询索引，复制并执行：

```text
backend/sql/supabase_indexes.sql
```

索引覆盖：

- 查询条件：都道府县 / 市 / 区 / 房型 / 年 / 月
- 历史命中：`query_key`
- 详情页：`slug`
- 最近数据：`created_at`
- 模糊查询：标题和 Markdown 正文
- JSON 数据：`summary`、`raw_record`

## 3. 前端连接 Supabase

把 `web/config.js` 改成：

```js
window.ZOUSEEKING_API_BASE_URL = "";
window.ZOUSEEKING_SUPABASE_URL = "https://你的项目.supabase.co";
window.ZOUSEEKING_SUPABASE_ANON_KEY = "你的 anon public key";
```

然后同步 GitHub Pages。

## 4. 启用用户注册/登录

网站使用 Supabase Auth 做邮箱密码注册/登录。注册时填写用户名、邮箱、密码；登录时使用邮箱和密码。用户名保存在 Supabase Auth 的用户 metadata 里，用来做页面显示名。

在 Supabase 项目里检查：

1. `Authentication` -> `Providers`
2. 确认 `Email` 已启用
3. 关闭 `Confirm email` / `Email confirmations`
4. `Authentication` -> `URL Configuration`
5. `Site URL` 填：

```text
https://gordon310.github.io/ZOUSEEKING/
```

6. `Redirect URLs` 加：

```text
https://gordon310.github.io/ZOUSEEKING/**
```

当前阶段先关闭邮箱确认，注册后直接登录。后面如果要重新开启邮箱确认，重点检查：

- `Site URL` 是否是 `https://gordon310.github.io/ZOUSEEKING/`
- `Redirect URLs` 是否包含 `https://gordon310.github.io/ZOUSEEKING/**`
- 默认邮件服务是否触发发送频率限制；免费默认 SMTP 适合测试，正式使用建议配置自定义 SMTP
- 邮箱安全扫描是否提前打开确认链接，导致 token 失效

## 5. 同步已有网站数据到 Supabase

在本地执行：

```bash
export SUPABASE_URL="https://你的项目.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="你的 service_role key"
python3 scripts/sync_content_library_to_supabase.py
```

注意：`service_role key` 只能放本地环境变量或 Render secret，不要写进 GitHub，不要写进 `web/config.js`。

## 6. 现在的行为

- 新的“分析一个日本房产”页面只通过 FastAPI intake API 写入项目、文件和预览，不进入旧的 `queries` / `generation_jobs` 表。
- 区域行情查询优先使用已配置的 FastAPI：查询发送到 `/api/query`，Mypage 的旧任务执行发送到 `/api/jobs/{job_id}/run`，任务读取发送到 `/api/jobs/*` 和 `/api/my/queries`。
- 没有配置 FastAPI 时，区域行情页面只显示本地公开内容；旧任务仍可由下面的 Edge Function 兼容路径处理。
- 匿名角色不能直接读取或写入区域查询、生成任务、报告、数据源和会员资料；完成 `20260827000500_legacy_private_data_rls.sql` 后，登录用户只能读取自己的区域任务与报告，写入仍由受信任后端负责。
- `property_reports` 的旧报告必须由带有 `owner_user_id` 的受信任服务写入，不能把客户端邮箱当作归属边界。

## 7. 本地运行 JPHOUSE worker

旧区域查询产生的 `generation_jobs` 可以由本地 worker 消费队列；它不消费新的 intake 会话。

本地运行：

```bash
cd /Users/gordonmac/GordonDev/JPPropDIs
python3 scripts/run_jphouse_worker.py --limit 5
```

脚本会隐藏提示输入 Supabase `service_role key`。不要把这个 key 写进网页或发到聊天里。

worker 会：

1. 读取 `pending` 的 `generation_jobs`
2. 用 `id=eq...&status=eq.pending` 的条件更新原子抢占任务；抢不到的任务直接跳过
3. 按查询条件生成 JPHOUSE 报告
4. 写入 `property_reports`
5. 更新 `queries.status = completed`
6. 更新 `generation_jobs.status = completed`

注意：worker 会在本地生成图片到 `web/library/...`。如果新报告需要在线显示图片，还要把 `web/` 同步到 GitHub Pages。

## 8. 方案B：Supabase Edge Function 云端执行

现在项目里已经加入 `supabase/functions/jphouse-run`，仅作为旧区域报告的兼容执行路径。

它负责：

1. 检查用户登录状态
2. 使用 `queries.owner_user_id` 读取用户自己的查询任务；缺少归属或归属不匹配时拒绝执行
3. 如果已有同条件报告，直接返回缓存
4. 如果没有报告，就按 JPHOUSE 模型生成数据
5. 写入 `property_reports`
6. 更新 `queries` 和 `generation_jobs`

部署前先在本地安装 Supabase CLI，并登录：

```bash
supabase login
supabase link --project-ref vbwynsyryuiigpqwvuer
```

设置云函数需要的私密 key。

注意：新版 Supabase CLI 不允许手动设置 `SUPABASE_` 开头的 secret，所以这里使用项目自己的名字 `JPHOUSE_SERVICE_ROLE_KEY`。

```bash
supabase secrets set JPHOUSE_SERVICE_ROLE_KEY="你的 service_role key"
```

然后部署：

```bash
supabase functions deploy jphouse-run
```

只有在未配置 FastAPI 的旧页面上，登录用户才会通过该 Edge Function 处理 Mypage 的“手动执行 JPHOUSE”。API 已配置时，按钮走 FastAPI `/api/jobs/{job_id}/run`，不会再调用该函数。

当前 Edge Function 先生成数据报告，不生成图片。原因是 Supabase Edge Function 更适合轻量数据处理；图片生成仍然建议后续用 Supabase Storage + 独立图片 worker，或者继续用本地 worker 批量生成后同步网站。
