# ZOUSEEKING 隱私政策與服務條款合規升級報告

**任务范围：** A～C   
**政策版本：** `privacy-2026-08`   
**条款版本：** `terms-2026-08`  
**生效日：** `〔生效日:待确认〕`

## A. 完成内容

- `docs/legal/privacy-policy.md` 已重写：主体、台湾 PDPA 第 8 条六项告知、第 21 条跨境、香港 DPP1、新加坡 PDPA、日本 APPI、中国大陆 PIPL 补充、照片与 EXIF、储存／接收方、Cookie／localStorage／sessionStorage、行销／DNC、保留和资料主体权利均已覆盖。
- `docs/legal/terms-of-service.md` 已更新主体、法人番号、地址、联络方式、日本准据法及大阪地方裁判所管辖，并说明按份报告、订阅、跨境和付款事实。
- 政策交叉引用 `privacy-operations-runbook.md`、`incident-response.md`、`data-subject-request-process.md`；DSAR 流程已统一台湾 15 日处理、必要时延长 15 日（最长 30 日），其他法域 30 日内部目标。

## B. 网页与多语言

- `web/privacy.html` 复用现有法律页结构，加入四语言切换器、政策正文和导航。
- 正文采用既有 `web/js/i18n.js` 的键承载方案，而非另建分语言文件；语言切换通过现有 `ZouI18n.setLocale()` 保存语言并重载页面。
- `zh-CN`、`zh-Hant`、`en`、`ja` 均覆盖同一组政策键；`zh-Hant` 沿用现有简繁转换生成机制。
- 未修改注册流程；注册页原有隐私政策／服务条款勾选入口仍在 `web/index.html:79-88`。

## C. 自检

### 1. 台湾 PDPA 六项对照

| 法定项目 | 政策对应章节 |
| --- | --- |
| 蒐集者名称、法人番号、地址、联络方式 | 第 1 节；网页 `legal.s1Body` |
| 具体蒐集目的及特定目的代码对应 | 第 2 节；网页 `legal.s2Intro`、`legal.pdpa2` |
| 个人资料类别 | 第 3 节；网页 `legal.pdpa3`、第 4 节 |
| 利用期间、地区、对象、方式；跨境至新加坡／日本 | 第 4 节；第 4.4 节；网页 `legal.pdpa4`、`legal.s3Body` |
| 查询、阅览、复制、更正、停止、删除及行使方式 | 第 6 节；网页 `legal.pdpa5`、`legal.s6Body` |
| 不提供资料的影响 | 网页 `legal.pdpa6`；政策第 2、3、5 节的功能边界 |

### 2. 法域覆盖

| 法域 | 对应章节 |
| --- | --- |
| 台湾 | 第 1～6 节、4.4、第 7 节中国大陆前的跨境与 040 行销说明 |
| 香港 | 第 7 节「香港 PDPO」：目的与接收方类别 |
| 新加坡 | 第 7 节「新加坡 PDPA」：目的、同意、外泄、DPO、DNC |
| 日本 | 第 1 节、第 4 节、第 7 节「日本 APPI」 |
| 中国大陆 | 第 7 节「中国大陆个人信息保护法」：告知、单独同意、跨境 |

### 3. 产品事实核实清单

| 项目 | 结论 | 代码／文档证据 |
| --- | --- | --- |
| 照片处理 | 当次请求传给 FastAPI；EXIF 在服务进程解析；未发现图片落盘或入库路径；AI 默认关闭；位置预填使用 `sessionStorage` | `backend/app/recognition/service.py:95-120,168-180`；`.env.example:3`；`web/js/recognition.js:24-29,36-65` |
| AWS／Supabase 位置 | 部署资料确认 Lightsail、Supabase、Cloudflare；仓库未编码生产 region，政策已列新加坡／日本并标注 AWS/Supabase 实际 region 待上线确认 | `deploy/README.md:1-22,105-106`；`docs/render-postgres-deploy.md:8-10,31-47` |
| 第三方处理者 | Stripe 支付；Supabase Auth／PostgreSQL／Storage；AWS Lightsail；Cloudflare；日本国土地理院反向地理编码。未发现其他已接入图片 AI 默认路径 | `backend/app/billing/gateway.py:57-75,102-129`；`backend/app/intake/geocoding.py:14-16,61-88`；`deploy/README.md:17-22,105-106` |
| 邮箱、密码、查询／报告、用量、付款 | 邮箱和用户 ID 来自 Supabase Auth；密码交由 Supabase Auth，本仓库不确认其内部 hash 算法；查询／报告／用量有对应路径；付款订单保存币别／金额／provider ID，审计过滤卡片与支付凭据 | `backend/app/auth.py:24-68`；`web/app.js:483-495,1722-1762`；`docs/data-dictionary.md:87-110`；`backend/app/billing/store.py:41-44,185-197` |
| 卡号 | 本服务不保存完整卡号，Stripe 处理支付凭据 | `backend/app/billing/store.py:185-197`；`backend/app/billing/gateway.py:57-75` |
| Cookie／本地储存 | 未发现广告 Cookie；语言和查询历史使用 localStorage，会话 token 也由现有前端放在 localStorage；位置预填用 sessionStorage | `web/js/i18n.js:2,1691-1709,1752-1760`；`web/app.js:1-10,190-205,474-495`；`web/js/recognition.js:24-29` |
| 行销／DNC | 代码中未发现行销邮件流程；政策明确目前不用于行销，并保留日后 DNC／退订待确认 | `web/app.js:1700-1779`（仅找回／注册路径）；政策第 5、7 节 |
| 保留期间 | 会员存续＋删除后主数据 30 日目标、备份最多 90 日、同意／DSAR／事故等法定或内部目标；以 Runbook／DSAR 流程为准 | `docs/legal/privacy-policy.md:41-43,74-78`；`docs/legal/privacy-operations-runbook.md:14-26,48-50`；`docs/legal/data-subject-request-process.md:17-27` |
| 不提供的后果 | 网页六项表明确邮箱、密码、查询条件、照片位置、付款资料分别影响哪些功能 | `web/privacy.html:45-51`；`web/js/i18n.js` 的 `legal.pdpa6` |

### 4. 语言覆盖确认

通过 Node 沙箱读取 `ZouI18n.keys()`：

```text
zh-CN: 573
zh-Hant: 573
en: 573
ja: 573
legal.* keys: 30
```

四个 locale 的键集合一致；正文元素均带 `data-i18n`，切换器使用 `data-locale-switcher`。自检命令为：

```text
node --check web/js/i18n.js
node --check web/app.js
node --check web/js/recognition.js
```

### 5. 页面上应放置的同意／告知入口清单（本任务未改注册流程）

- 注册页 `web/index.html:79-88`：隐私政策与服务条款两个链接、必选勾选、版本与同意时间说明。
- 隐私政策页顶部：主体信息、版本、生效日占位和语言切换器。
- 照片位置功能 `web/property-analysis.html:202-213`：上传控件旁的 EXIF 用途、不落盘／不入库、当次使用、位置反向编码接收方及可不使用说明；若启用 AI，必须增加独立选择与跨境告知。
- 付款／订阅结帐前：价格、币别、Stripe 处理、卡号不由本服务保存、退款／续订规则和隐私政策链接。
- 客服入口 `web/support.html:24-37`：资料主体请求类型、身份验证、canaanlife@goo.jp／受控工单系统和时限说明。
- 账号设置：删除、撤回可选用途同意、会话撤销及保留例外说明。

### 6. 命令、状态和未验证项

- `node --check web/js/i18n.js`：通过。
- `node --check web/app.js`：通过。
- `node --check web/js/recognition.js`：通过。
- `git diff --check`：通过。
- `git status --short`：见最终报告；未执行 commit/push。
- 未进行浏览器真实视窗／移动视窗交互验收、线上 AWS／Supabase／Stripe／Cloudflare region 或供应商合同核对、线上 RLS／删除／外泄通报演练、法律意见确认。
- 条款中按份报告、订阅、价格、退款、续订、消费者撤回权、跨境机制、客服系统及正式 DPO 身分仍需负责人／法务确认；这些差异已在 `docs/legal/terms-of-service.md:11,31,35,41` 留出说明。
