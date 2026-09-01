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

## 2. 建表

打开 Supabase 项目：

SQL Editor -> New query

复制并执行：

```text
backend/sql/supabase_schema.sql
```

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

## 4.1 隐私、同意和账户删除（离线发布门槛）

当前契约版本为 `privacy-2026-08` / `terms-2026-08`。注册表单必须主动勾选隐私政策和服务条款；提交边界生成 UTC `consent_at`，并将版本写入 Auth metadata。浏览器时钟和 metadata 仍属于不可信输入，正式上线前需要受信任服务端/Auth 事件补充时间戳核验，不能把当前静态前端结果当作 production 证据。

账户页的删除入口只会在有 FastAPI 地址、Supabase 会话和 bearer token 时调用 `POST /api/account/deletion-request`，请求包含当前版本及固定值 `DELETE_ACCOUNT`。当前 FastAPI 删除执行器未配置时明确返回 `503`（`no account data was changed`），页面显示未删除，不连接 Auth Admin、数据库、RLS、Storage 或备份，也不会发送客服通知。客服与数据主体请求使用静态 [support.html](../web/support.html) 和 `.example` 占位地址，不能视为已接通邮箱。

密码找回使用 Supabase `/recover` 并保持账户枚举安全；登出尽力调用 `/logout` 后清理本地 UI；当前实现只证明当前会话退出，不能证明所有 refresh token 已撤销。旧区域路径仍可能由 `web/app.js` 直连 Supabase REST/Edge Function，FastAPI 唯一业务路径、RLS 四角色验证和受信任删除 worker 尚未收敛。

上线前必须完成运营主体/隐私负责人确认、客服工单权限、近期重新认证、全会话撤销、Auth Admin 删除、RLS/Storage 删除、备份轮换、持续清理器、事故通知决定和恢复演练。当前 `migration_baseline_status = reconciliation_required`，本任务不执行这些线上动作、不发送通知、不使用真实账号或资料。

## 5. 同步已有网站数据到 Supabase

在本地执行：

```bash
export SUPABASE_URL="https://你的项目.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="你的 service_role key"
python3 scripts/sync_content_library_to_supabase.py
```

注意：`service_role key` 只能放本地环境变量或 Render secret，不要写进 GitHub，不要写进 `web/config.js`。

## 6. 现在的行为

- Supabase 里有相同查询：前端直接返回历史数据
- Supabase 没有相同查询：前端保存 `queries` 和 `generation_jobs`
- JPHOUSE 采集器后续补数据后，写入 `property_reports`

## 7. Stripe 计费 rollout 门槛（当前仅离线）

当前 FastAPI 已记录 Stripe 支付/订阅边界，但 `BILLING_ENABLED` 默认关闭，未完成受信 gateway/store 注入前不会创建 Checkout、Customer Portal 或退款请求，也不会连接 live Stripe。所有本地测试使用固定 test fixtures/mock，不使用 live key，不产生真实收费。

Webhook 必须由 FastAPI 读取原始 request body，先验证 `Stripe-Signature`，再以唯一 `event.id` 幂等写入事件状态、账单状态和审计/outbox。Checkout 产品、price id、金额、币种、customer 和 redirect URL 只能来自服务端白名单；浏览器回跳不能直接开通权益。

上线前必须同时完成并记录：

- `migration_baseline_status = reconciliation_required` 清除后的 canonical membership/billing forward migration、RLS 与四类身份断言；在此之前不得增加或执行 billing migration。
- 不得执行 linked repair、db push 或 production reset，除非另有明确授权、备份和 forward-fix 计划。
- Stripe Dashboard Customer Portal 的 payment method、invoice history、取消/计划更新配置，test-mode webhook delivery 和失败重试演练。
- provider backup/restore、税费/收据、退款/取消和支付失败降级演练；任何 provider 或生产数据库操作都必须停在明确授权门槛。

## 8. 本地运行 JPHOUSE worker

网站产生的新查询会进入 `generation_jobs`，需要 worker 消费队列。

本地运行：

```bash
cd /Users/gordonmac/GordonDev/JPPropDIs
python3 scripts/run_jphouse_worker.py --limit 5
```

脚本会隐藏提示输入 Supabase `service_role key`。不要把这个 key 写进网页或发到聊天里。

worker 会：

1. 读取 `pending` 的 `generation_jobs`
2. 按查询条件生成 JPHOUSE 报告
3. 写入 `property_reports`
4. 更新 `queries.status = completed`
5. 更新 `generation_jobs.status = completed`

注意：worker 会在本地生成图片到 `web/library/...`。如果新报告需要在线显示图片，还要把 `web/` 同步到 GitHub Pages。

## 9. 方案B：Supabase Edge Function 云端执行

现在项目里已经加入 `supabase/functions/jphouse-run`。

它负责：

1. 检查用户登录状态
2. 读取用户自己的查询任务
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

部署完成后，网站登录用户可以在 Mypage 里点击“手动执行 JPHOUSE”。

当前 Edge Function 先生成数据报告，不生成图片。原因是 Supabase Edge Function 更适合轻量数据处理；图片生成仍然建议后续用 Supabase Storage + 独立图片 worker，或者继续用本地 worker 批量生成后同步网站。
