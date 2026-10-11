# 当前候选完整测试与本地联调（2026-10-11）

基于候选306fcaa的项目读取与报告重试修补；生产未发布，真机等待本轮软件测试完成后执行。

## 修复

- consumer_launch遗漏已保存项目GET入口，导致保存后打开项目404；仅补该读取路由，既有登录、政策确认和owner filter保留。
- C项目页报告按钮调用被禁用的旧执行接口；改用已有POST/api/query的六个查询维度，沿用服务器额度和outbox；旧执行接口保持禁用。
- 独立局域网验收代理补传X-Analysis-Session；本地配置synthetic free_c query=3/day，未修改生产额度。

## 验证

- Python全量：1113 passed，0 skipped；含本地真实Supabase REST四身份与全56条canonical migration的独立测试数据库。
- 浏览器全量：156 passed，0 skipped（修补后完整重跑）；desktop与390px、键盘、隐私、付费内容隔离、实际Service Worker离线和更新/回滚均包含在测试中。
- Node10 passed；compileall、pip check、schema ownership、迁移台账C1-C7、release policy、资产一致性、diff检查PASS。
- 真实本地Auth/API：登录和同意确认、session创建、文本资料、字段确认、preview、convert、project读取与受控删除PASS。匿名项目读取401，本人200，其他账户404。
- 真实390px浏览器：注册201→政策确认→已登录→资料预览→保存→打开正确项目→报告按钮POST/api/query 200→账户删除202；页面脚本错误0。
- 独立只读审查：项目GET路由与报告按钮改走主流程均未发现阻塞问题。

## 范围

真实本地报告worker/外部数据采集、实际Stripe付款退款、生产邮件送达、正式HTTPS下手机PWA安装、iPhone/Android真机、生产迁移发布及上线观察未执行。报告内容、权益、worker与支付契约在自动化测试中有合成fixture证据，不能代替上述真实外部链路。

局域网原地址仅供独立测试。用户手工账户保留，仅清理本次脚本创建的synthetic_fixture账户。release_ready仍为false。
