# 2026-10-07 上线:就绪摘要与待授权清单(2026-09-27 生成)

> 本文件**不改变任何授权状态**:`docs/release/production-go-live-approval.json` 仍为 `BLOCK / NOT AUTHORIZED`,
> `production-release-evidence.json` 仍为 `NOT_EXECUTED`。本文件把**已实测的事实**与**待你确认的项**分开列出,
> 使正式授权时只需签字确认,无需重新取证。

## 1. 发布物标识(实测)

| 项 | 值 |
|---|---|
| 权威分支 | `main`(2026-09-04 决策:main 即唯一权威分支,不另建 release branch) |
| 发布点 commit | `1ea7dd40560a08747daf8fdd03a34530383be886`(`1ea7dd4`) |
| 前端资产版本 | `20260926-r67`(`deploy/frontend-version.txt`,源/产物/HTML 三方一致,`check:web-assets` exit 0) |
| 迁移台账 | 生产 **54 / 仓库 54**,零缺口(最高 `20260923000300`) |
| 生产 RELEASE_PHASE | `consumer_launch`(2026-09-26 切换,冒烟通过) |
| 生产 ENVIRONMENT | `production` |
| 生产 HEAD | `/opt/zouseeking` 已 `git pull` 至与 origin 同步 |

## 2. 已就绪并附生产实测证据

| 维度 | 证据 |
|---|---|
| **C 端注册/登录** | 真实生产端到端:`POST /api/auth/invite-register` → `201` → 页面自动登录 → 本地会话含 token → **控制台零错误** |
| **开放注册** | GoTrue 直连注册关闭(`422 signup_disabled`),本方端点可用(`201`);邀请码可选 |
| **API 门禁** | `consumer_launch` 冒烟 **32 项**:A 组(C 端 + 后台)20 条零门禁拦截;B 组(B 端)12 条全部 `404 GATE` |
| **站点可用性** | `/` `200`、`/tokushoho.html` `200`、`/support.html` `/privacy.html` `/terms.html` `200`、`/health/ready` `200` |
| **法务** | 特商法页含 姜爽 / 〒544-0023 大阪府大阪市生野区林寺2-5-22 / 06-7503-1661;隐私政策占位 0;四语言公告占位 0 |
| **异地备份** | 每日 03:10 JST 自动上传 Cloudflare R2(sha256 三方一致),`observability-check.sh` 转 `OBSERVABILITY_OK`(backup_age_hours ≤ 36) |
| **回滚** | 演练实测:回滚 **22 秒**、前滚 **38 秒**,健康与鉴权边界全通,零 DB 变更;回滚目标与命令已落档 |
| **支付** | live 订单无 `pending`/`failed`;webhook `unprocessed = 0`;price id env 18 = DB 18 零差异 |
| **CI** | 每次 push 绿;含 `first-week-observation` 新守护(artifact `status: PASS`) |
| **测试基线** | 浏览器 **116 passed**;unit+arch **556 passed / 91 skipped**;全量 python **754 passed / 113 skipped** |

## 3. 待你确认/授权(签发项)

| # | 项 | 需要的输入 |
|---|---|---|
| 1 | ~~日本律师复核~~ ✅ **已通过**(用户 2026-09-27 告知) | 仅需补:复核人/事务所、复核日期、书面结论存档位置(不代填) |
| 2 | **C11 预算与 SLO 数值** | 首月预算上限、目标用户量/峰值、可用性 SLO;用于把容量基线从「受邀范围」升级为生产阈值 |
| 3 | **C13 staging smoke(可选)** | 一次性 staging 写入授权 + `SMOKE_ANON_KEY` / `SMOKE_OWNER_TOKEN` / `SMOKE_OTHER_TOKEN` |
| 4 | ~~C14 逐项发布授权~~ ✅ **已授权(2026-09-27,owner: Gordon)** | 观察窗采 30 分钟密集 + 24 小时常规;状态已更新为 `AUTHORIZED`,发布证据已填实 |

**授权已完成(2026-09-27)**:`production-go-live-approval.json` = `AUTHORIZED`(含 approved commit、前端版本与产物
sha256、观察窗、stop conditions、回滚实测);`production-release-evidence.json` = `PRODUCTION_EVIDENCE_RECORDED`,逐项按**生产实测**填写,
未执行项如实标 `PARTIAL` 或列入未验证,**不冒充通过**。

## 4. 本轮**未验证**、不得当作已通过(如实列出)

1. **生产告警投递与 on-call 演练** —— 观测脚本在跑,但告警「送到人」的链路与演练未做;
2. **provider 级物理备份 / PITR 恢复** —— 现有的是逻辑备份异地化,不含 provider 快照/PITR 演练;
3. **私有 Storage 对象恢复** —— 未演练(逻辑 DB 备份不含 Storage blob);
4. **真机多端浏览器审计** —— 自动化覆盖了 116 个用例,但真机多设备/多浏览器的手工审计未做;
5. **技术债(非阻塞,已决定延后)**:
   - `web-source/app.js` 8 处 legacy 直读 Supabase(会员数据路径,当前工作正常)—— **用户 2026-09-27 决定:延后至 10-07 之后**,理由:改动落在 C 端「我的项目/查询/报告」的核心数据路径上,上线前重接的风险高于收益;届时须配端到端回归;
   - 命令型指标只读性仅静态检查(看板守护的能力边界,不可消除)。

## 5. 发布与回滚(已验证的操作序列)

**发布**:`cd /opt/zouseeking && git pull --ff-only origin main` → 若后端有改动则 `docker compose -f deploy/docker-compose.prod.yml build api` → `up -d --no-deps api`;前端为 nginx 挂载宿主 `web/`,`pull` 后即时生效。
**回滚**:改 `deploy/.env` 的 `RELEASE_PHASE` 或 `git checkout <目标 commit>` → 重建 → `up -d`;`.env` 备份为 `.env.bak-*`。
**判据**:健康 `/health/ready` 200 + 站点 200 + 未鉴权后台 401(非 503) + B 端 `404 GATE`。


## 6. 决策记录

| 日期 | 决策 | 决定人 |
|---|---|---|
| 2026-09-23 | 首发范围 = C 端 + 后台管理平台同时上线(B 端随后) | 用户 |
| 2026-09-24 | 开放注册(邀请码可选);关闭 GoTrue 公共注册旁路;法务地区 = 日本;C13 授权;C04 成本批准 | 用户 |
| 2026-09-27 | 法务口径:删 SLA 天数与事故责任人、上特商法记载页、经营者实体信息填实公开 | 用户 |
| 2026-09-27 | `app.js` legacy 直读 Supabase 退役 **延后至 10-07 之后**(非因遗忘) | 用户 |
| 2026-09-27 | 本班次继续绑定 10-07 倒排 | 用户 |
| 2026-09-27 | **日本律师复核通过**(法务侧阻塞解除) | 用户 |
| 2026-09-27 | **C14 逐项发布授权:C14 通过**,发布执行与回滚获授权(provider 级变更仍单独把关) | 用户 |
