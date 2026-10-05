# PWA 上线闭环进度（2026-10-05）

本表按既有 2026-10-07 C 端 + 后台首发窗口重排。只读核对与进度安排已执行；未部署、未操作凭据、未做数据库/Storage/支付写入。既有 09-27 发布授权仍保留，不修改历史审批文件；新候选版本需绑定新的 commit、资源版本与校验和后再判定。

## 当前结论

生产已提供 Web/PWA 访问，公开端点可用；本次 UX 候选还未整合上线，不能沿用旧版本的 release_ready=true 作为新候选验收。上线闭环仍开放，不按完成百分比推算。

### 本次实际核对

- main HEAD：`54d0d4fb018ca0d3398c4dc5653aad7bea4bec40`；部署版本文件 `20260926-r67`。
- UX 候选：独立 `codex/ux-simplification`，尚未提交/合并；Service Worker 与 HTML 新版本为 `20261005-r68`，部署版本文件仍为 r67，整合时必须同步。
- 线上公开 GET：首页、manifest、sw.js、privacy.html、API `/health/ready` 均 HTTP 200；API 响应 ready/database ok。线上首页和 SW 仍 r67。
- manifest MIME 正确，品牌为小象避坑，standalone、根路径 start_url/scope、192/512 图标字段存在；未在本轮真机安装。
- 线上 `sw.js` 与 manifest 均为 `Cache-Control: public, max-age=31536000, immutable`。SW 更新另有 update/probe 机制，但不能据此声称旧安装用户更新/回滚通过。
- `check_launch_surface_consistency.py --json`：OPEN，O1/O2/O3 尚存（隐私草稿/生效日占位、日本口径与台湾文本冲突、代表姓名异值）。
- `check_release_status_consistency.py --json`：OPEN，RS1 尚存（provider/PITR/Storage 恢复是上线前还是上线后要求，文档口径冲突）。
- `check_migration_ledger_offline.py --json`：PASS；仅离线钉扎一致，不是生产真账复验。
- `check_open_registration_review.py --json`：PASS；注册 409 枚举口径未决，真实限流/邮件行为 NOT_EXECUTED。
- UX 候选上一轮实际验证：Chromium 136 passed、回跳安全检查和生成资源一致性通过；属于本地夹具证据，不是生产交易或真机证据。

## 闭环台账

| ID | 优先级 / 当前状态 | 交付与 Done when | 负责人 / 依赖 | 目标窗口 |
|---|---|---|---|---|
| L01 | P0 / OPEN | 同步已审定日本法务文本至站内三基础语言及繁中派生，明确生效日和代表信息；O1/O2/O3 全部关闭，一致性门禁 PASS | Codex 整理待确认差异；经营者确认最终文案，不另作法律结论 | 10-05 |
| L02 | P0 / OPEN | 核实 staging 与生产项目隔离；现 smoke 白名单 project_ref 与生产证据中的 project_ref 相同。在未明确隔离前不执行 smoke 写入。确认 provider/PITR/Storage 恢复的 RS1 范围决定，状态门禁 PASS | 环境负责人提供非敏感目标标识；经营者确认恢复范围 | 10-05 |
| L03 | P0 / OPEN | 整合 UX 候选；同步 deploy/frontend-version、SW、HTML、构建资产为唯一版本；冻结 commit/checksum；该候选完整 CI required jobs 与审计全绿 | Codex；当前分支尚未整合，136 本地测试不能代替候选 CI | 10-05 至 10-06 上午 |
| L04 | P0 / OPEN | 评估并修正稳定 sw.js URL 的一年 immutable 策略；分别验证 r67→新版本、离线再联网、后台唤醒和回滚；不丢失填写内容、无循环刷新；检查 manifest/icon 更新 | Codex 准备代码/部署配置与测试；发布环境验收由执行负责人完成 | 10-06 上午 |
| L05 | P0 / NOT_EXECUTED | iPhone Safari 添加主屏幕后 + Android Chrome 安装后各走一次：启动、登录回跳、文件选择、生成、报告、支付跳转后返回、退出登录；断网不显示旧账户私有数据；记录设备/OS/浏览器/候选版本与截图 | 真机持有人 + Codex 汇总；设备与测试账户 | 10-06 白天 |
| L06 | P0 / PARTIAL（历史） | 同候选完成注册→登录→资料→生成→支付→解锁→再次打开；匿名/本人/其他用户私有报告与 Storage 拒绝/允许矩阵；真实限流和找回邮件；退款/客服路径留证，受控记录清理确认 | 执行负责人 + Codex；隔离环境、受控测试账号；真实支付/退款按批准范围执行 | 10-06 白天 |
| L07 | P0 / OPEN | 根据首发流量确定预算、峰值、SLO、降级/停止阈值与值守联系人；做一次告警到人→响应→判定恢复/回滚流程；复核异地备份新鲜度。至少验证从异地逻辑备份恢复到隔离环境；provider PITR/Storage 的硬门槛由 L02 决定 | 经营者给数值及联系人；执行负责人提供当前证据 | 10-06 白天 |
| L08 | P0 / NOT_EXECUTED | 最终 Go/No-Go：L01–L07 所有首发硬门槛关闭；候选/线上版本与产物一致；API C 端可用、B 端门禁保留、健康通过；登记回滚目标、命令、停止条件、执行人 | Codex 汇总证据；经营者最终放行；既有授权不重复索取 | 10-06 晚 |
| L09 | P0 / NOT_EXECUTED | 发布后 30 分钟密集观察及 24 小时常规观察：站点/ready、错误、任务队列、支付 webhook/解锁、备份新鲜度、PWA 老用户更新；异常按停止条件回滚；证据归档 | 发布/值守负责人执行；Codex 汇总，不在本次自动配置定时任务 | 10-07 至 10-08 |

时间安排是条件排期，不是完成承诺。L01/L02 当天未关闭或 L05/L06 真机/交易主路径失败，10-07 不强行上线；沿用旧计划的 10-09 备选窗口，或明确缩小首发范围，由经营者决定。

## 首发范围和延后项

C 端 + 后台首发，B 端数据查询/统计/导出维持门禁。本轮 B 端体验优化不等于开放 B 端。已保存资料编辑及继续上传缺当前接口支持，首发不得宣传为已提供。

legacy Supabase 路径退役已有延期决定，保持上线后处理。provider PITR 与私有 Storage 恢复是否可延后仍是 RS1 待定项，不能自行认定为非阻塞。容量数值、法务留痕虽在旧清单被称非阻塞，本排期要求最迟冻结前明确其责任人、期限与接受条件，不虚构数值。

## 证据来源与维护

以 production-go-live-approval.json / production-release-evidence.json 的 09-27 存档、现行上线一致性合同、开放注册 review、倒排计划及本次实际输出共同核对。历史“已通过”只代表当时版本；告警投递 09-28 已有人确认收到，仍缺响应演练，不能倒退写为从未投递。

每项完成时记录：候选 commit、环境、执行时间、命令/设备、结果、证据路径、残留清理和未覆盖面。状态使用 PASS / FAIL / PARTIAL / OPEN / NOT_EXECUTED，不把未执行写为 PASS。

PWA 真机与更新验收参考官方文档：[Apple 安装指引](https://support.apple.com/en-lamr/guide/iphone/iphea86e5236/ios)、[web.dev 更新生命周期](https://web.dev/learn/pwa/update)。

## 2026-10-05 继续执行结果（候选分支）

L01 部分完成：代表姓名 O3 已修正，O1/O2 仍 OPEN，具体同步差异已交付。L03 本地版本已统一 r68，待 main 整合与远程完整 CI。L04 本地配置和浏览器行为验收完成，待线上/真机证据。全套 Chromium 139 passed、聚焦 pytest 31 passed、两项 Node 检查及资源/版本/策略/秘密扫描通过；临时 nginx 三主机9项 HTTP 检查通过并清理。所有代码均在 codex/ux-simplification，主目录代码与线上均未变更。详见候选 docs/release/pwa-preflight-evidence-2026-10-05.md。
