# ZOU SEEKING HOUSE 后端部署方案

目标架构：

```text
GitHub Pages 前端
  -> Render FastAPI 后端
  -> Render PostgreSQL
```

## 1. Render 上创建服务

推荐用仓库里的 `render.yaml` Blueprint：

1. 登录 Render。
2. New -> Blueprint。
3. 选择 GitHub 仓库 `gordon310/ZOUSEEKING` 对应的源仓库。
4. Render 会创建：
   - `zouseeking-api` Web Service
   - `zouseeking-postgres` PostgreSQL

后端启动命令：

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 2. 必要环境变量

Render Blueprint 已写好：

- `DATABASE_URL`：自动引用 Render PostgreSQL connection string
- `INIT_SCHEMA=true`：后端启动时自动建表
- `ALLOWED_ORIGINS=https://gordon310.github.io,http://127.0.0.1:8790,http://localhost:8790`

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

