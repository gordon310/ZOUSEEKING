# ZOU SEEKING HOUSE Supabase 免费版接入

这条路线适合当前阶段：

```text
GitHub Pages 前端
  -> Supabase PostgreSQL 保存查询索引和历史结果
  -> 本地/后端 JPHOUSE 生成器补数据
```

## 1. 创建 Supabase 项目

1. 登录 Supabase。
2. New project。
3. 选择 Free 计划。
4. 记下：
   - Project URL
   - anon public key
   - service_role key（只给本地同步脚本用，不要放到前端）

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

## 5. 同步已有网站数据到 Supabase

在本地执行：

```bash
export SUPABASE_URL="https://你的项目.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="你的 service_role key"
python3 scripts/sync_content_library_to_supabase.py
```

注意：`service_role key` 只能放本地环境变量，不要写进 GitHub，不要写进 `web/config.js`。

## 6. 现在的行为

- Supabase 里有相同查询：前端直接返回历史数据
- Supabase 没有相同查询：前端保存 `queries` 和 `generation_jobs`
- JPHOUSE 采集器后续补数据后，写入 `property_reports`
