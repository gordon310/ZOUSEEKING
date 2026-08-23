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
- `generation_jobs`：生成任务进度
- `property_reports`：生成后的房产数据和 Markdown
- `data_sources`：数据源记录

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
3. `Authentication` -> `URL Configuration`
4. `Site URL` 填：

```text
https://gordon310.github.io/ZOUSEEKING/
```

5. `Redirect URLs` 加：

```text
https://gordon310.github.io/ZOUSEEKING/**
```

如果开启邮箱确认，用户注册后需要先点邮件里的确认链接，再登录。

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
