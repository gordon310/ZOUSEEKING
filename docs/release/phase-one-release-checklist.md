# 第一阶段发布范围 checklist

本 checklist 的完成对象是 `consumer_intake_preview`。打勾必须附证据链接、命令输出或审批记录；“staging 看起来可用”不能代替 production 证据。

## A. 决策与发布物

- [x] ADR-0001 确认 FastAPI 是唯一私有业务 API，`supabase/migrations/` 是唯一 forward migration history。
- [x] ADR-0002 将第一阶段冻结为 C 端匿名 intake 与免费预览。
- [x] 机器契约与 FastAPI allowlist 由离线测试保持一致。
- [x] B/admin staging 演示页仅允许 allowlisted public static GET，阻断私有读取、跨域请求和所有网络写入。
- [ ] production 静态发布物只包含 C 端入口，或对 B/admin 评审页实施独立访问控制。
- [ ] production 页面明确说明免费预览范围、资料用途、非估价/非法律意见、保存与删除规则。

## B. 权威路径与冻结

- [x] managed 环境缺少/未知 `RELEASE_PHASE` 时业务 API fail closed。
- [x] `/convert`、project、旧 query/job/report 路由不在第一阶段 allowlist。
- [x] Edge Function 默认关闭，只有精确 break-glass 值可进入执行逻辑。
- [x] local worker 默认在读取 service-role 凭证前退出。
- [x] 前端配置不固定 Supabase 项目 URL。
- [ ] 对实际部署产物做一次网络审计，证明业务 fetch/XHR 只调用已批准 FastAPI origin，B/admin fetch 只命中公开静态 allowlist。
- [ ] 清点并确认所有 legacy queue 均未被第一阶段发布触发；不得擅自清空或迁移队列。

## C. Production 数据与安全门槛（全部未授权）

- [ ] migration baseline 可从空的隔离环境 fresh reset，且与预期 schema 一致。
- [ ] anonymous / owner / other user / privileged worker 的 SQL 与 Storage 权限测试通过。
- [ ] production backup/restore 与 forward-fix 演练通过并留存证据。
- [ ] private bucket 的 public、size、MIME、object policy 与保留期经过复核。
- [ ] Auth 邮箱确认、重复账号、密码策略、找回、注销、撤销、删除和枚举防护经过验收。
- [ ] signup/intake/upload/preview 的 account + abuse-source 限流和告警经过验收。
- [ ] 日志确认不含 token、email、姓名、原始资料或内部异常。
- [ ] production secret 由负责人设置并复核；仓库与构建日志中没有 secret。

## D. 产品、隐私与数据质量

- [ ] 产品/法务确认隐私文本、同意版本、资料用途、保留期、删除请求和禁止上传内容。
- [ ] 明确第一阶段是公开可用还是受邀测试，并记录首月用户量、峰值 QPS、文件量、SLO 与预算。
- [ ] 用非敏感受控资料验证文字、URL、PDF、JPG、PNG、位置拒绝和 geocoder 失败降级。
- [ ] 免费预览继续显示 `data_class`、资料不足、`comparable_status=not_checked`，不生成虚假税费总额或完整报告结论。
- [ ] 可访问性覆盖键盘、focus、状态播报、200%/400% zoom、390x844 和 reduced motion。

## E. 离线与部署前验证

- [x] 新增 release scope API、worker、Edge、manifest 与浏览器网络阻断测试。
- [x] Python unit/api/smoke/architecture 全量回归通过。
- [x] Edge Node 测试与所有相关 JS `node --check` 通过。
- [x] Playwright 全量 web 回归通过。
- [ ] 对第一阶段实际发布物单独完成无 console error/warning 的浏览器审计。
- [x] Python `compileall`、依赖兼容检查、`git diff --check` 通过。
- [ ] SQL/RLS 测试在隔离数据库通过；若环境缺失，发布继续 BLOCK，不记作 pass。
- [x] 审阅最终 diff，确认没有 migration、live project ref、secret、真实用户资料或生成资产误改。

## F. Live authorization gate

- [ ] 明确批准 production 数据库/RLS/Storage/Auth 变更的确切目标、备份和回滚。
- [ ] 明确批准 production/staging deployment 的 commit、服务、域名、环境变量差异和观察窗口。
- [ ] 指定发布负责人、回滚负责人、告警渠道和停止条件。
- [ ] 发布后只做已批准的 synthetic/受控 smoke；任何真实资料测试需单独授权。

在 C、D、E、F 未全部完成前，状态保持 **BLOCK / NOT AUTHORIZED**。不得通过启用 Edge/local worker break-glass、直接 PostgREST 或手工数据库写入绕过 checklist。
