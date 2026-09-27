# 开放注册上线复核(D-6)· 离线半部分

> 执行:**2026-09-28 早班**(倒排表 **D-9** 当日项 `C13 真实 staging smoke` 因缺 `SMOKE_*` 三凭据 + 一次性 staging 写入授权**无法执行**,按倒排规则顺延到下一个可自主完成的条目 **D-6**)。
> 边界:本班 **零网络、零凭据、零 DB 写**;本文件只记录**可离线机械复核**的部分。真实环境的限流/枚举/邮件确认**未实测**,不冒充通过。

## 0. 结论摘要

| # | D-6 复核项 | 判定 | 依据(仓库内,已实跑) |
|---|---|---|---|
| 1 | **限流** | ✅ 代码与合同一致;🟡 实测未执行 | 注册路由走共享计数器 `consumer_registration`(`backend/app/routes/invites.py:22-27`),计数器不可用时 **fail-closed 503**;键 `INVITE_REGISTER_RATE_LIMIT_PER_HOUR`(默认 5/小时)已登记于 `docs/operations/production-configuration-contract.md:61` 与 `deploy/.env.example:68` |
| 2 | **账号枚举安全** | ⚠️ 待用户决策(见 §3) | 注册端点对已存在邮箱返回 `409 code=account_already_exists`(`backend/app/invites.py:28`),即**注册侧可探测账号是否存在**;登录/找回走 Supabase Auth(统一错误),但注册侧与 AGENTS「uniform responses where account enumeration is possible」存在张力 |
| 3 | **邮件确认行为** | ✅ 行为已定义;🟡 实测未执行 | 全仓**唯一** Admin 建号路径为 `backend/app/invites.py:24`,payload 固定 `"email_confirm": True`(:35)→ 我方通道建号即预确认、不发确认信;仓库内不存在第二处 `POST /auth/v1/admin/users`(`integrations/supabase_admin.py` 只做 revoke/delete) |
| 4 | **试运行标识与开放注册口径(四语言)** | ✅ 机械校验通过 | zh-CN / zh-Hant / ja / en 四段各自含开放注册口径(无需邀请码 / 無需邀請碼 / 招待コード不要 / no invite code required)**且**试运行标识(试运行 / 試營運 / トライアル / trial),全文无未填占位(`TBD`/`待定`/`未定`/`TODO`) |

## 1. 机器校验

```bash
python3 scripts/check_open_registration_review.py          # 人类可读
python3 scripts/check_open_registration_review.py --json    # 机器可读
```

本轮实跑结果(2026-09-28):

```text
open_registration_review_status=pass checks=6
- C1_registration_request_optional_invite_code: invite_code = Field(default='', max_length=128)
- C2_open_registration_skips_invite_tables: empty-code branch at line 38 precedes the invite reservation at line 45
- C3_admin_create_pre_confirms_email: email_confirm=True at line 35; the only admin create path is backend/app/invites.py
- C4_registration_rate_limit_fails_closed: shared counter scope 'consumer_registration' with fail-closed 503; INVITE_REGISTER_RATE_LIMIT_PER_HOUR registered
- C5_consumer_signup_never_requires_invite_code: web/profile.html has no invite-code field; web/index.html keeps it optional; the reader stays null-safe
- C6_four_language_open_registration_alignment: zh-CN / zh-Hant / ja / en each state open registration and mark the trial period; no placeholders
```

判据设计原则:每条判据读的是**真实源**(AST 解析注册模型与分支顺序、唯一建号点、限流合同登记、四语言文档段落),不是对期望的重述;`tests/unit/test_open_registration_review.py` 用**变异测试**逐条证明判据确有拦截力(改必填、破坏短路分支、翻 `email_confirm`、删限流键登记、给邀请码字段加 `required`、抹掉某语言口径、注入占位)。

**能力边界(不可消除)**:本检查器只证明**仓库内声明的口径自洽**,不能证明运行中的 staging/生产行为一致 —— 那正是 §2 未执行的部分。

## 2. 未执行(需环境授权,不冒充通过)

| 项 | 需要的授权/凭据 | 现成执行体 |
|---|---|---|
| 真实注册限流实测(第 6 次起 429、`Retry-After` 生效) | 一次性 staging 写入授权 + 目标 base URL | `scripts/staging_m1_acceptance.py`(注册/限流链路) |
| 真实账号枚举响应实测(同邮箱二次注册的响应码与 body) | 同上 + 一个受控已注册邮箱 | 同上 |
| 真实邮件确认行为(`email_confirmed_at` 已填、GoTrue 直连注册已关) | provider 侧配置读取权(staging) | `scripts/staging_m1_acceptance.py:264-284`(admin 建号 `email_confirm`)、`:381`(signup-link 不得被自动确认) |

上述三项与倒排表 **D-9(C13 真实 staging smoke)** 共用同一套 `SMOKE_*`/staging 授权 —— **一次授权可同时闭合 D-9 与本节**。

## 3. 待用户决策(本班不擅自改行为)

**账号枚举口径**:`POST /api/auth/invite-register` 对已注册邮箱返回 `409 account_already_exists`,前端据此提示「该邮箱已注册」(`web-source/app.js:2079`)。这属于**有意的可用性选择**,但与 AGENTS「Use uniform responses for login, signup, and password reset where account enumeration is possible」冲突。

| 选项 | 做法 | 代价 |
|---|---|---|
| **A(推荐)维持现状 + 记录例外** | 保留 409 语义,在 AGENTS/合同里显式写明「注册侧允许枚举」的例外与理由 | 零改动;例外须留痕,后续审计不再重复报同一项 |
| B 改为统一响应 | 已存在邮箱也返回 202/201 同形响应(实际不发信或发信告知),由邮件侧承担告知 | 改 API 契约 + 前端 i18n + 测试;**用户无法即时得知邮箱已注册**,客服量上升 |

## 4. 本班未触碰

- 未连接任何 staging/生产环境,未读取任何凭据,未做 DB 写或对象变更,未部署。
- 未改动注册链路、限流阈值、公告文案的实质口径(仅新增复核载体与报告)。
