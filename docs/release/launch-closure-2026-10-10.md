# 2026-10-10 上线闭环

当前候选为 codex/launch-closure，前端 20261010-r70。当前判定 **No-Go**：尚未取得冻结候选的完整 CI、真实设备/交易验收及发布观察证据。09-27 发布授权继续适用于发布、重启、phase 配置与回滚；不替代本次验证，不允许 provider、套餐、计费或 DNS 改动。

## 用户决定

零新增费用。PITR 为 **NOT_APPLICABLE**，不是 PASS。实际 R2 逻辑备份隔离恢复及私有 Storage 隔离恢复为发布前门槛。仅补跑一次既有备份，保持定时器 disabled，不清理远端备份。privacy-2026-10 随本次实际上线生效，重要更新要求重新确认，保留历史同意。

## 当前恢复证据

- 生产基线 f60f9106c8493b8d5a2fb86026d0ab8bf0bb909c / 20260926-r67；生产实际 datastore project_ref fnogxuytbabxmqousifh，控制台名称含 staging 不意味着可作写入演练目标。
- 已授权补跑 zouseeking-20261010T144526Z.dump，并上传现有 R2，再从 R2 重新下载校验。创建时间 2026-10-10T14:45:40Z；15,805,432 bytes；SHA-256 667489b3c4b691d6f60463c2726011596cc13df74608f86eae5d89942869c8e0。
- 本机 Docker --network none、只读挂载备份，隔离数据库恢复 7 表计数与 manifest、54 migration versions 完全一致。恢复程序用时 4.58 秒；这是程序耗时，不是全系统 RTO。备份时间是恢复点，不是已批准的 RPO 服务承诺。
- 逻辑导出不含完整 Auth 凭据/会话及 ACL；隔离 Auth 使用 UUID 桩。另在旧 09-29 异地备份恢复库重建测试授权进行 queries RLS 检查，匿名 0、owner 3、其他用户 0、worker 6；不能据此声称完整身份系统恢复。
- 生产 property-intake 私有桶当前 0 对象。因此没有实际生产文件可恢复。使用明确标记 synthetic_fixture 的 68-byte PNG，经现有 R2 上传→重新下载→独立本机私有桶恢复，字节 SHA-256 一致。worker HTTP 200；匿名、owner 和另一账户直接读取均 HTTP 400，符合 worker-only Storage 边界，普通用户只经后端授权读取。签名 URL 在有效期内 HTTP 200，1 秒 TTL 后重新请求 HTTP 400。
- 本机临时 Storage 对象、目标桶与两个 Auth fixture 用户已删除。生产数据库及生产 Storage 未写入；备份定时器保持 disabled。本次没有启用自动 Storage 备份：以后出现真实文件时须归档对象字节及元数据，数据库备份不能替代文件备份。
- 脱敏证据：`evidence/launch-closure-2026-10-10/database-restore.json`、`storage-restore.json`、`storage-r2.json`。实际生产 dump 和日志位于仓库外受限临时目录，禁止提交。

## 候选变更与验收

整合 r68 UX 与 C 端独立账户/找回页面，保留安全回跳参数，统一 r70。同步审定日本隐私文案，新增服务端当前版本确认：使用既有 append-only audit_events，不新增迁移；身份来自认证，时间来自数据库，旧客户端 Auth metadata 不当作可信确认。consumer_launch 未确认的 intake/query/report/checkout 返回 428，确认与账户删除入口仍可用。

真库并发测试验证 8 次确认只追加一次、旧版本保持原样、另一用户不被确认、UPDATE 被 append-only trigger 拒绝。法律页面和一致性门禁已更新。独立审查发现并修复账户切换同意复用、隐私字段 422 回显、退出事件竞态；旧 GET/POST 结果按账户及 generation 作废。旧格式浏览器会话保留 userId 以绑定弹窗，服务端授权仍只依验证的 Auth。全量测试和冻结候选 CI 结果待录入。

## 尚未关闭

完整候选测试/CI、artifact checksum、真机 PWA 与账户/支付路径、告警到人响应、生产发布及 30 分钟/24 小时观察。没有这些证据不得将本文件改为 Go 或宣称上线闭环完成。定时器按用户决定不自动恢复，后续备份新鲜度需依人工补跑维护。
