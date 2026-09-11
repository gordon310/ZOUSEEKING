# Lightsail 部署设计 · 房产信息系统上云(2026-09-11,v1)

## 0. 目标与范围

把**应用层**(web 静态站 + FastAPI + 采集/生成 worker)**部署到 Amazon Lightsail 新加坡实例**,数据层继续用 Supabase 托管(决策 A,2026-09-11 用户确认)。

- ✅ 范围内:web、FastAPI、worker/scheduler、JPPGSKILL server(后置)、Nginx+TLS、域名接入
- ❌ 范围外(明确不做):Supabase 迁移(留 B 路线,设计见 §9)、生产 Stripe live key 启用、商店提审动作
- 红线:DB 字段冻结/只 forward migration;staging Supabase 是唯一数据目标(生产 Supabase 不动);单写者(避免与 Render 双写同库)

## 1. 目标环境

| 项 | 值 |
|---|---|
| 实例 | `zoubeacon-prod-sg`(Lightsail,新加坡 Zone A) |
| 规格 | 2 GB RAM / 2 vCPU / 60 GB SSD(Ubuntu) |
| 公网 | IPv4 52.221.7.33(**必须先转静态 IP 并 attach**)、IPv6 2406:da18:1325:2200:9a5d:77e0:b848:58ee |
| 域名 | `zoubeacon.app`(**小象避坑 C 端产品站**,PWA/standalone 契合)、`platform.zoubeacon.com`(**小象数据平台**,B 端 + 后台管理)、`api.<TBD>.zoubeacon.com`(FastAPI,待定归属) |
| DNS | 现由 Cloudflare 托管(`zoubeacon.com` 橙云指公司站 カナン株式会社);新记录在 CF 添加 |
| 关键风险 | 2 GB 内存 → 配 2-4 GB swap;`.app` 全域 HSTS 预载:无有效证书=硬失败,证书先行 |

## 2. 组件与端口

```
Internet
  └─ Cloudflare(橙云代理,Full(strict))→ Lightsail Nginx (80/443)
       ├─ zoubeacon.app        → C 端小象避坑(web/ 静态站,C 端页面为根)
       ├─ platform.zoubeacon.com → 小象数据平台(B 端 + 后台 admin 页面为根)
       ├─ api.<TBD>.zoubeacon.com/api/* → 127.0.0.1:8000 (FastAPI/uvicorn)
       └─ (M4) 内部服务           → 127.0.0.1:8100 (JPPGSKILL server,仅内网+API key)
  后台进程(不经 Nginx):
       ├─ collection-scheduler (常驻,scripts/collection_scheduler.py)
       └─ collection-worker    (常驻,scripts/collection_worker.py)
```

**Nginx 站点映射(第一版,two server blocks 同 root + 默认页重写)**:web/ 目录目前 C 端(小象避坑:property-analysis 等)与 B 端(小象数据:index/data-query/mypage/admin)页面混装 → 第一版两域名指向同一 root、按 `server_name` 重写默认页(C 端域根 → C 端首页;B 端域根 → 平台首页);**后续**再做构建产物拆分(独立目录/独立发布),列入 M6 建议项。

| 进程 | 端口 | 形态 | 说明 |
|---|---|---|---|
| Nginx | 80/443 | systemd | TLS 终止 + 反代 + 静态 |
| FastAPI | 127.0.0.1:8000 | docker 或 systemd | `uvicorn app.main:app`(backend/,1-2 worker) |
| collection-scheduler | — | docker/systemd | 定时 enqueue 采集任务 |
| collection-worker | — | docker/systemd | 认领并跑采集/生成(supabase 单写者) |
| JPPGSKILL server | 127.0.0.1:8100 | docker | M4,依赖其仓库形态确认 |
| certbot | — | systemd timer | Let's Encrypt 自动续期 |

**容器化(Docker Compose)为默认**:运维一致性好、重启自愈;Nginx 与 certbot 走宿主 systemd(证书路径简单)。

## 3. 部署步骤与里程碑

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| **M1 服务器基线** | 用户:静态 IP attach + DNS zone + A/AAAA 记录;我:SSH 后更新系统、建 2GB swap、装 Docker+Compose、ufw 只开 22/80/443、创建部署用户+目录、Lightsail 自动快照开启 | `docker compose version` 可用;`free -h` 显示 swap;端口扫描仅 22/80/443 |
| **M2 web + FastAPI 上线** | git clone 到 `/srv/zouseeking`;写 `.env`(见 §4);起 web(静态复制或 Nginx root)+ FastAPI 容器;Nginx 反代 + certbot 签 `zoubeacon.com`/`www`/`api` | `https://www.zoubeacon.com` 200;`https://api.zoubeacon.com/health/ready` → `{"status":"ready"}`;登录+查询+报告链在浏览器实跑通 |
| **M3 worker 常驻** | scheduler + worker 容器常驻;接 staging Supabase;跑一轮真实采集任务 | `generation_jobs` 出现 worker 产出的 completed 行;日志无 PII/secret |
| **M4 JPPGSKILL server(可选,解 D10 依赖)** | 按其仓库部署(端口/鉴权以其 README 为准);FastAPI 侧配 `JPPSKILL_BASE_URL`(D10 开发时接入) | 内网 `curl 127.0.0.1:8100/health` 200;外部不可达 |
| **M5 域名与切换** | `.app` 加证书后 301 → `.com`;Render 降级为备份(不删) | `.app` 与 `.com` 均 HTTPS 正常;`curl -I http://zoubeacon.com` → 301 https |
| **M6 灰度与收口** | 观察 3 天(错误率/内存/证书);更新活卡片与 runbook | 无异常告警;文档入库 |

## 4. 环境变量清单(FastAPI/worker,服务器 `.env`,权限 600)

从 Render staging Environment 页**复制粘贴**(经 SSH 或你自己编辑,不经聊天):

```
ENVIRONMENT=staging            # 首版仍指向 staging Supabase;转生产时改 production
RELEASE_PHASE=consumer_active
INIT_SCHEMA=false
APP_VERSION=lightsail-2026-09
DATABASE_URL=<staging Supabase transaction pooler 串>
SUPABASE_URL=https://fnogxuytbabxmqousifh.supabase.co
SUPABASE_ANON_KEY=<publishable key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>
ABUSE_HASH_SALT=<同 Render>
INTERNAL_DIAGNOSTICS_TOKEN=<同 Render>
INTAKE_BUCKET=property-intake
# 支付(生产接入时填;首版可留空 → /api/billing/* 优雅 503)
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_IDS=
BILLING_SUCCESS_URL=https://www.zoubeacon.com/mypage.html
BILLING_CANCEL_URL=https://www.zoubeacon.com/mypage.html
BILLING_PORTAL_RETURN_URL=https://www.zoubeacon.com/mypage.html
```

web 静态站:`web/config.js` 的 API_BASE_URL 指向 `https://api.zoubeacon.com`;supabase 注入策略沿用(部署注入或 addInitScript 方案的固化,见 P2-6 记录)。

## 5. 凭据与安全

- SSH:专用 key(建议 `lightsail-zouseeking`),仅本人持有;禁用密码登录(`PasswordAuthentication no`)
- 服务器 `.env` 600 + 只部署用户可读;不放 repo(已 gitignore)
- 证书:certbot 自动续期 timer;`.app` 证书须与 `.com` 同步(预载 TLD 无例外)
- Lightsail 防火墙:22(限本人 IP 最佳)、80、443;其余关闭
- 备份:Lightsail 自动快照(每日)+ Supabase 自带备份;`data/collected` 快照随 repo/对象存储备份
- 日志:docker logs + logrotate;不落 PII/secret

## 6. 部署方式(第一版)

- `git clone` 到 `/srv/zouseeking`,`docker compose up -d --build`
- 更新:`git pull && docker compose up -d --build`(runbook 记录)
- 不做 CI 自动部署(第二版再上 GitHub Actions → SSH)

## 7. 回滚

- Render staging **保持在线不动** → 任何阶段故障,把 DNS 指回 Render 即恢复服务(切换窗口 < 5 分钟,TLS 由 Render 侧已有域名?→ .com 未在 Render 配置时,回滚以 Lightsail 修复为主)
- 服务器侧:docker compose down 即停应用,不动数据(Supabase 托管,天然隔离)

## 8. 验收测试清单(浏览器 + 命令行,全部实测)

1. `https://api.zoubeacon.com/health/ready` → ready/database ok
2. 浏览器:登录(测试账号)→ 查询涩谷塔楼 → 免费预览(可比参考行)→ 工作台 → 报告(锁态/解锁态)
3. `generation_jobs` 由 Lightsail worker 产出的 completed 行(与 Render 区分:加 `worker_id` 日志标记)
4. 内存:闲时 < 1.2 GB;跑一轮 worker 后无 OOM(`dmesg | grep -i oom` 为空)
5. 证书:`.com`/`www`/`api` 三项 `openssl s_client` 有效;`certbot renew --dry-run` 通过
6. 重启恢复:`sudo reboot` 后所有服务自动起来(compose restart: unless-stopped)

## 9. 后续路线(Supabase 自托管,触发时执行)

触发条件(任一):免费层限制成瓶颈 / 合规要求数据自持 / 成本优化。
路径:官方 `supabase/docker` compose 起 Postgres+PostgREST+GoTrue+Storage → **迁移历史 replay**(`supabase/migrations/`)+ 数据逻辑导出导入 → 平行验证(双读对比)→ 切 `SUPABASE_URL`/`DATABASE_URL`。应用代码零改(API 兼容)。
**本设计预留**:服务器目录结构、备份策略、env 组织均按"未来可加 DB 容器"排布。

## 10. 需要用户执行的动作(阻塞项)

1. **Lightsail:创建静态 IP 并 attach 到实例**(否则重启换 IP)
2. **DNS:建 zone / 加 A 记录**(`@`、`www` → 静态 IP;`api` → 静态 IP;AAAA 可加 IPv6)
3. **SSH 访问**:提供 key(或你自己按本文档执行命令)
4. Render Environment 页的 secret 值(你自己填进服务器 `.env`,或授权我读取后写入——建议前者)

## 11. 实施现状(2026-09-11 服务器盘点)

- 实例已装 Docker 29.8.0;已有 `/opt/zoubeacon`(官网单容器 + CF Origin 证书,运行中)
- 已补:2GB swap(fstab 持久化,swappiness=10)、ufw(22/80/443)
- 待实施:本 deploy/ 制品上线(FastAPI + worker + scheduler + 站点分域名)
- 备注:官网与项目同机;nginx 站点配置由单容器版升级为多站点版
