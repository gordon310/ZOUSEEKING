# P2-6 提审截图材料清单(2026-09-10)

截图全部摄自 staging(zouseeking-web-staging.onrender.com,consumer_active 验收态,测试账号 zouseeking.p2test@gmail.com)。

## 规格
- 桌面:`*.desktop.png` 1440×900(07 为视口抓拍,01-06 1440 宽)
- iOS(6.7" App Store 规格):`ios/*.png` **1290×2796**(视口 430×932 @3x)
- 安卓:待按商店规格补(内容同源,可换视口重出)

## 目标对照

| # | 目标 | 桌面 | iOS | 内容/数据要求达成 |
|---|---|---|---|---|
| 1 | 首页公开价值主张 | 01-home-desktop.png | ios/01-home-ios.png | 登录前首页,CTA 可见 |
| 2 | 查询表单(填写中) | 02-query-form-desktop.png | ios/02-query-form-ios.png | 东京都/涩谷区/塔楼/2026-08 |
| 3 | 免费预览(评估结果) | 03-free-preview-desktop.png | ios/03-free-preview-ios.png | 完整度 6 维 + 费用估算 + 国交省可比参考行 |
| 4 | 工作台任务列表 | 04-workspace-desktop.png | ios/04-workspace-ios.png | 3 条 completed 任务 |
| 5 | 报告详情(解锁全量) | 05-report-unlocked-desktop.png | ios/05-report-unlocked-ios.png | 成交表 3 户型 + 汇率注记 + 数据来源 |
| 6 | 付费墙卡片(锁态) | 06-paywall-locked-desktop.png | ios/06-paywall-locked-ios.png | 🔒 锁卡 + 权益说明 + 解锁按钮,无内容泄漏 |
| 7 | 数据来源/口径特写 | 07-sources-closeup-desktop.png | ios/07-sources-ios.png | 汇率注记(2026-09-08 外管局)+ 国交省口径 |
| 8 | PWA/移动形态 | 08-home-mobile.png(390×844@3x) | = ios/01(复用) | 移动首页;原生安装横幅需真机截(自动化不可得,见记录) |

## 数据真实性
- 成交数据:国交省(国土交通省 土地総合情報システム)取引価格情報整理,期间 2026年[令和8年]1～3月,中古マンション口径,出所明記
- 汇率:国家外汇管理局人民币汇率中间价 2026-09-08(100JPY=4.3098CNY;100USD=677.95CNY 交叉),仅作显示参考
- 免费预览费用估算:法定上限/官定表确定性估算(中介手续费 111万/印花税 2万 等),非报价
- 测试数据仅含测试账号样例查询(涩谷/目黒/港区塔楼 2026-08),无真实用户 PII

## 记录/降级
- 08 原生 PWA 安装横幅(headless 与桌面 Chrome 移动模拟均不渲染浏览器 chrome 层横幅,web 无自绘安装 UI)→ 以移动首页收口;如需横幅素材:Android Chrome 真机访问 staging 首次会话截,或自绘安装指引页(设计活)
- 桌面 07 为报告页整页视口抓拍(来源区与 05 同页不同滚动位)
