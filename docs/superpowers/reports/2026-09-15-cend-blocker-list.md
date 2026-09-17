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

## 二·补:C6 90 天备份到期 —— 已补作业并上线

| 项 | 结果 |
|---|---|
| 缺口 | 政策承诺「主数据 30 天 / 备份 90 天」,但全仓没有执行器 → 到点无人执行 |
| 实现 | `scripts/account_retention_sweeper.py`:幂等、有界(`--limit`)、可 `--dry-run`、逐条隔离、日志无 PII;校验受控删除已完成 + 到期后**只写一次** `backup_expired_at` 事实时间,**不碰 provider backup / `auth.users` / append-only `usage_events`** |
| schema | forward migration `20260915000400` 加列 + 部分索引;schema 清单计数 34→35 |
| **调度** | **已接进 `scheduler` 容器每小时循环**(不接进调度 = 等于没跑,这是本轮特意补的一环) |
| CI | 新 SQL 断言已接入 step + 两处 `REQUIRED_CHECKS`;**CI run `34950183015` 七 job 全绿** |
| 线上验证 | 服务器已 pull、scheduler 容器重建;容器内实跑 `--limit 5 --dry-run` → `{"scanned":0,"failures":0,...}` 退出码 0 |
| 口径 | 与政策文案「备份最多 90 天**自然到期**」一致(作业记录事实,不主动删 provider 备份);runbook 已同步 |

### 本轮另外修掉的一个 CI flaky
`property-intake.spec.js:589` 是**竞态**:用例种下过期 access token + 无效 refresh token 后,页面自身可能先完成刷新失败并清掉会话 → `isLoggedIn()` 在 CI 慢时变 false。上一次只加了一行等待(掩盖),**这次改成测试自己控制刷新时机**(token 响应先挂起,状态断言后再放行);连跑 5 次 + 整套 81 passed 全绿,CI 复验通过。

## 四、2026-09-16 批次:付费报告改「只走下载」+ 注册双模式(邮件认证已回到方案内)

> **决策变更**:09-16 上午先按「不做邮件认证」去掉了确认邮件文案;当日用户改主意 —— **SES/邮件链路一次做到位,含认证邮件**。应用侧已改为**双模式**,切换只靠 Supabase 的一个配置开关 `mailer_autoconfirm`,不改代码。

| 项 | 状态 |
|---|---|
| 注册:响应含会话(免验证) | ✅ 直接进已登录态(原行为,有测试保护) |
| 注册:响应无会话(需验证) | ✅ 显示「确认邮件已发送到 <邮箱>」+ **重发确认邮件**(`type=signup`,60 秒节流,失败按原因映射) |
| 登录:邮箱未验证 | ✅ 专属文案 + 重发入口(**不再误报"密码不对"**) |
| 文案 | ✅ 11 个新键 × 四语言(zh-CN / zh-Hant / ja / en) |
| SES 侧配置 | ✅ 发信域 DKIM/MAIL FROM SUCCESS;**发信身份默认配置集 `zoubeacon-tracking` 已挂**(此前为空 → SMTP 发信的退信/投诉到不了 SNS);账户级抑制列表 BOUNCE+COMPLAINT;DMARC 已发布 |
| Supabase 侧配置 | ✅ 双语品牌化模板(确认/改密/登录链接)+ 主题行;开启「密码已修改 / 邮箱已修改」安全通知 |
| ⛔ 唯一缺口 | **SES 生产权限**:案件 `178931383400481` 状态 `Customer action completed`(我方已回复全部细节),等 AWS 24h 内响应;Basic 支持计划**不能用 Support API**(`SubscriptionRequiredException`),只能在控制台跟进 |
| 切换时点 | AWS 放行后由 Hermes 切 `mailer_autoconfirm=false` → 跑通「注册→收信→点链接→登录」 |

| 项 | 结果 |
|---|---|
| **交付方式** | 新增 `GET /api/reports/{query_key}/download` → **单个自包含 HTML**(内联 CSS + `@media print`,用户可自行打印/存 PDF)。三重校验:**匿名 401** / 非本人 404 / **未解锁 403 且响应体不含任何报告正文**(实测正文关键词在 403 响应里搜不到)/ 已解锁 200(`nosniff` + ASCII 回退文件名 + RFC 5987 UTF-8 文件名,HTML 内**无任何外部资源 URL**) |
| **前端** | 报告页解锁后**只暴露一个主操作**「下载报告」;四语言文案同步 |
| **注册去邮件化** | 不再依赖邮箱确认(注册即存、成功直接进已登录态);四语言中「已发送确认邮件」类文案清除;注册失败按原因映射(密码不合规/邮箱已注册/网络失败) |
| **内部标识泄漏(4 处,已修)** | ① ward 哨兵 `__not_subdivided__` 进入**报告标题**(`东京都港区__not_subdivided__塔楼…` → `东京都港区塔楼…`);② 下载页「地址」回退链末端用了 `query_key` → **必然把 `<UUID>::…` 写进文件**(改为回退业务标题);③ 下载**文件名**用 owner 命名空间的 slug → **文件名带 UUID**(改为 `物件报告-东京都-港区-塔楼-2026-8.html`);④ 报告页前端同样的 `query_key` 回退。已加回归断言:HTML 与 `Content-Disposition` 均不得含 `::`、`__not_subdivided__`、UUID 形态串 |
| **缓存** | 前端资产版本 r35 → **r36**;`app.js` 被版本脚本有意排除但本批次它改了 29 行,已手工补版本号(否则老用户吃缓存旧模块) |
| 测试/CI | Python `535 passed / 86 skipped`;Web `82 passed`;两次推送 CI 均**七 job 全绿** |
| 线上 | 已部署(api + worker 重建);`/health/ready` ready;实测**匿名下载线上返回 401**;`web/report.html` 已含下载按钮、`app.js?v=20260916-r36` |

## 五、待你决策 / 待处理

**2026-09-15 产品决策(用户,权威)**:
- **不做邮件认证**:注册即存、注册成功直接进入已登录态(不依赖邮箱确认);前端四语言中"已发送确认邮件"类文案清除(已派工)。
- **付费报告的交付方式只有「下载」一条路**:格式 = **自包含 HTML 单文件**(零新依赖,用户可自行打印/存为 PDF);解锁校验必须在服务端,未解锁响应里不得出现正文(已派工)。
- 影响:SES 生产权限申请**不再阻塞上线**(认证邮件不再必需)。⚠️ **遗留风险**:密码重置/找回仍依赖邮件 —— SES 仍在沙盒时只能发给已验证地址(目前 `gordon310103@gmail.com` 已验证,SMTP 链路实测可发);上线前需决定:①接受"忘记密码走客服" ②继续推进 SES 生产权限 ③改用其它发信通道。

| # | 项 | 状态 |
|---|---|---|
| **N1** | 用户注销(上线前合规项) | ✅ **已完成**:受控删除执行器已上线并 live 验证通过(见第二节) |
| **N2** | AWS SES 生产权限 | 🔴 **申请被驳回**(`ProductionAccessEnabled=false`,`ReviewDetails.Status=DENIED`,CaseId `178931383400481`);`PutAccountDetails` 返回 **ConflictException**(官方定义=「已有一次账号详情变更在审核中」,裁决后状态被冻住,控制台/API 都无法重提)→ **必须开支持案让 AWS 清掉陈旧审核状态**;而 IAM 用户 `zoubeacon-ses-ops` 没有 `support:*` → **需用户:①给 IAM 加 `support:CreateCase/DescribeCases/AddCommunicationToCase`(推荐,之后由 Hermes 开案跟进)或 ②自己在控制台追加回复(话术已备)** |
| **N5** | Supabase Auth 配置(本轮已修) | ✅ `site_url` 由 `http://localhost:3000` → **`https://zoubeacon.app`**、补 `uri_allow_list`(zoubeacon.app / platform / 本地 8787、3000)、`smtp_max_frequency` 60→30。⚠️ 修前**改密/确认邮件链接会指向 localhost**,属真实上线缺陷。SMTP 本身早已接 SES(`email-smtp.ap-southeast-1.amazonaws.com:587`,`no-reply@mail.zoubeacon.com`,域名 DKIM + MAIL FROM 均 SUCCESS,SMTP 派生凭据实测认证通过) |
| **N6** | `mailer_autoconfirm=true` | ⚠️ 决策(按推荐执行):**现在保持 true**——SES 仍处沙盒,开启邮箱确认会让所有真实用户的注册确认邮件发不出去(= 直接注册失败);**等 SES 生产权限获批后立即改为 false**,并跑一轮注册确认链路验证(注册→收确认邮件→点链接→登录)。已作为上线检查项登记 |
| **N7** | 发信域 DMARC | ✅ **已添加**(2026-09-15,Cloudflare API 代写并读回核对):zone `zoubeacon.com` 内新增 TXT `_dmarc.mail` = `v=DMARC1; p=none; rua=mailto:canaanlife@goo.jp; fo=1`(DNS only,TTL 3600);`dig @1.1.1.1` 已解析。**只加发信子域,公司主域 `zoubeacon.com` 未被触碰**(主域仍无 `_dmarc` 记录)。观察 1-2 周若 `rua` 报告无异常再收紧到 `p=quarantine` |
| **N8** | SES 沙盒下的收件验证 | 已把 `gordon310103@gmail.com` 建为待验证身份 → **用户点一下 AWS 验证邮件**即可在沙盒下真实收信、测试注册/改密邮件链路 |
| **N3** | 4 行历史僵尸报告(`generating`,分属 `1114513@qq.com` 与测试账号 p2test) | 修复后会在对应账号下次查询时自愈;**本批次未删任何数据**,如需清理先给清单待批 |
| **N4** | 早班/夜班自主班次与人工会话并发写同一仓库 | 本轮发生过(早班 07:40 起两次派 codex,与 live 验证并发) → 已临时暂停早班、终止并发派工,验证完成后已恢复;后续人工会话期间建议先暂停班次 |

## 三、已知未修(不阻塞本次链路)

| # | 项 | 状态 |
|---|---|---|
| **C1** | Release Gate CI 红 | ✅ **已修复**:Playwright 断言漂移 **22 failed → 0 failed**(本地 `81 passed`,CI 同命令);同时修了新增表导致的 `sql-m1` 授权计数基线(authenticated 23→24、service_role→CI 实测 **339**)。最新 run **34918209738 七个 job 全绿** |
| **C2** | `location` 接口要求 `accuracy_m` | ✅ **已查清,非产品路径问题**:`accuracy_m` 在请求模型里是必填(`backend/app/intake/models.py:110`),但**前端的照片定位走 `/api/recognition` → 回填三级地区下拉**,`api-client.saveLocation` 全仓无调用点 → 只有直连 API 的调用方才需要传。**默认不改**;若要对外暴露该接口,再改成可选(带默认精度)即可 |
| **C6** | 90 天备份到期承诺 | 🔴 **确认存在缺口**:全仓无任何 `backup_expiry` 的**执行器/定时清理作业**,`BACKUP_EXPIRY_SLA=90d` 目前只在注销台账里**生成一个到期时间**(`account_deletion_requests.backup_expiry_due`),到点**没有任何东西会执行**。需要决策:①补一个定时作业(建议,与隐私政策文案一致)②或调整隐私政策措辞。**待用户拍板** |
| **C7** | 线上 `deploy-worker-1` 的 `RestartCount=441` | ✅ **不是崩溃循环,是设计如此**:compose 命令为 `--loop 60 --interval 10`(跑 60 轮 × 10 秒后**主动退出**),由 `restart: unless-stopped` 拉起 → 约每 10 分钟一个生命周期。ExitCode=0、无 OOM、DB 取任务走原子认领,功能正常。**后续会话勿误判为故障** |
| **C3** | `pip check` 报缺 `packaging`(环境项,非产品缺陷) | 已记录 |
| **C4** | 迁移未录入 `supabase_migrations.schema_migrations`(2026091x 起的历史实践即如此) | 卫生项,建议后续统一 |
| **C5** | 4 个 SQL 测试文件从未进 CI | ✅ **已修复**:`sql-analysis` / `sql-exports` / `sql-member` / `sql-realtime-quota` 四个 step + 两处 `REQUIRED_CHECKS` 已接入;其中 `test_realtime_quota_migration_additive.sql` 的 `pg_read_file`(需超级用户+绝对路径)改为临时表 `\copy`,已实跑通过。**CI run `34920080958` 七 job 全绿** |
| **C5b** | 接入过程中被 CI 抓到的两个 CI-only 缺陷 | ✅ 已修:①四个新 step 的 psql URL 复制了**掩码显示**,密码变成字面 `***` → psql exit 2(已还原真实 URL);②`property-intake:589` 在会话种子写入前就断言 `isLoggedIn()`,只在 CI 现造的 example 前端配置下暴露(已改为先等种子落盘;两种配置下均 0 failed) |
| **C6** | 注册邮件的**备份到期(90 天)作业**是否存在,未验证 | 待确认 |

## 四、部署与回滚

- 部署:push → 服务器 `git checkout -- . && git pull` → `docker compose -f deploy/docker-compose.prod.yml up -d --build api`;nginx 未改。
- 线上库变更:① 追加 1 行 `sources`(可 delete 回滚)② 替换 `property_reports` 的 slug 唯一约束(可回滚为 `unique(slug)`)。
- 回滚:服务器 `git checkout <上一提交>` 后重建 api 容器;DB 侧见对应 migration 的反向语句。

## 六、2026-09-17 更新:SES 生产权限**已获批**(只读实测,晨班)

- **证据**(本机只读调用 `~/.aws-ses-ops` 凭据,IAM 用户 `zoubeacon-ses-ops`,region `ap-southeast-1`,零写操作、零发信):
  - `sesv2:GetAccount` → `ProductionAccessEnabled=true`、`SendingEnabled=true`、`EnforcementStatus=HEALTHY`、`MailType=TRANSACTIONAL`、`ReviewDetails.Status=**GRANTED**`(CaseId `178931383400481`,即第五节 N2 的同一案件)。
  - 配额(`ses:GetSendQuota`):24h `50,000` 封 / `14 msg/s`;近 24h 已发 1 封 → **沙盒限制(200 封/日、仅已验证地址)已解除**。
  - 身份:`mail.zoubeacon.com`(域名)+ `canaanlife@goo.jp`、`gordon310103@gmail.com`(历史沙盒验证地址,可保留);配置集 `zoubeacon-tracking` 存在。
- **缺口状态**:第五节 N2「🔴 申请被驳回/`ConflictException`」**已解除**;SES 不再是上线阻塞项。密码重置/安全通知现在可发给任意真实用户邮箱。
- **唯一剩余动作(需授权,本班未执行)**:把 Supabase Auth 的 `mailer_autoconfirm` 由 `true` 切为 `false`,然后跑通「注册 → 收确认信 → 点链接 → 登录」。两种等价方式(均已按最新官方文档核对,2026-09-17):
  1. **Management API(推荐,Gordon 侧提供 access token 后由 Hermes 代执行)**:
     ```bash
     curl -X GET "https://api.supabase.com/v1/projects/fnogxuytbabxmqousifh/config/auth" \
       -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN"
     curl -X PATCH "https://api.supabase.com/v1/projects/fnogxuytbabxmqousifh/config/auth" \
       -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" -H "Content-Type: application/json" \
       -d '{"mailer_autoconfirm": false}'
     ```
     token 获取页:https://supabase.com/dashboard/account/tokens(本机当前**无**该 token,`supabase` CLI 亦未 link 本项目 → 无法自行执行)。
  2. **控制台**:Supabase Dashboard → 项目 `zoubeacon-staging` → **Authentication → Providers → Email** 内的 **Confirm Email** 开关(官方 general-configuration 文档:该选项位于 email provider 的 provider-specific configuration)。关闭后等价于 `mailer_autoconfirm=false`。
- **切换注意**:应用侧已是双模式(`mailer_autoconfirm` 单开关,不改代码);切换前确认 SES 侧发信身份与模板已就绪(§四已核对);切换后立即跑一轮真实地址注册验证,失败则回切 `true`。
- 红线:本节仅只读取证 + 文档;零 DB/线上写、零部署、零凭据改动、零删除、未改 migration 与冻结字段。

## 七、2026-09-18 更新:N6 已闭环 + 门禁真实库证据缺口(晨班只读)

| # | 项 | 状态 |
|---|---|---|
| **N6** | `mailer_autoconfirm` 切 `false` | ✅ **已闭环(2026-09-17 人工会话执行)**:开关已切 `false`、「注册 → 真收信 → 点链接 → 登录」端到端验证通过;§六「唯一剩余动作」作废。本班只读复核:Hermes `cron list` 已无 SES 监视作业,与闭环记录一致 |
| **C1** | Release Gate 红链(09-17 连续 7 推) | ✅ **已复位**:`0a70e3e` / run `35245512352`(09-17T16:16Z)**七 job 全绿**;两条根因分别由 `d233e6f`(集成测试改 skip + 浏览器断言去 `synthetic_fixture` 字面)与 `57617d3`/`0a70e3e`(Playwright)修掉 |
| **C1b** | ⚠️ **新缺口(本班实测)**:修复走的是「库不在即 skip」次选路径 | `.github/workflows/release-gate.yml` 的 Python job **无任何数据库服务**(无 `55432`、无 `services:`),`npx supabase start` 只在 `sql-rls` job(54322,跨 job 不可用)→ **7 个真实库集成测试在 CI 静默跳过**,MLIT XIT001 导入 / region-stats / 报告来源解析的**真实库证据在门禁中不成立**。本机复现:`pytest tests/integration -q`(未设库变量)→ 7 skipped。**最小修法(建议派 Codex)**:Python job 加 `services: postgres:16`(映射 `55432:5432`)+ pytest step 导出 `DATABASE_URL`;`tests/support/pg_bootstrap.py` 自建库并跑迁移,无需 supabase CLI |
| **N3** | 4 行历史僵尸报告 | 仍待批(本班无 DB 凭据,未动);修复后会在对应账号下次查询时自愈 |
| **C4** | 迁移台账卫生 | 仍待口径(补齐 or 不补) |

- 红线:本节仅只读核验 + 文档;零 DB/线上写、零部署、零删除、未触凭据与冻结字段、未改 migration。
