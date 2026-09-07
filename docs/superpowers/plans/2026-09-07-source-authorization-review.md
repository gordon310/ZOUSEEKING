# 数据源授权审查 · SUUMO 试点(2026-09-07)

## 试点源
SUUMO 賃貸相場(例 https://suumo.jp/chintai/soba/tokyo/sc_shibuya/?ts=1)——configs
三家族(jphouse_23ku/osaka_wards/yokohama_wards)data_sources 中的"租金相场"项,
当前由 collect_local_readin 从本地快照读入(未 live 抓取)。本审查为 live 抓取前置。

## 审查结论:❌ 不通过(商业用途需书面许可)

| 检查项 | 结果 |
|---|---|
| robots.txt | 目标列表路径(/chintai/soba/)未 Disallow——robots 层面允许访问;但仅 bingbot 有 Crawl-delay:30,通用 UA 无明确节流 → 即便授权也须自设低频 |
| 利用規約 | **Article 3(7):使用本站作商业用途需 Recruit 许可**;Article 3(2) 版权/知识产权侵权禁止 |
| 业务实质 | 小象避坑为**收费商业产品**,展示/转载 SUUMO 相场数据(哪怕聚合指标)落入商业用途条款,且属 Recruit 版权数据 |
| AGENTS 红线 | `rights_confirmed=yes` 是采前必需——本审查即记录:SUUMO 未获许可 → **不可 live 采集/展示** |

## 连带发现

- configs 另一源 `tochidai.info`(中古マンション成交相场)是**民间站**(非政府官方;官方为
  国土交通省 土地総合情報システム tochi.mlit.go.jp)——同属需站方许可,且数据源于国交省,
  直接采官方更合规。
- 产品若保留"租金/成交相场"展示,数据侧现实:
  - 成交(中古マンション):国土交通省 土地総合情報システム = **政府开放数据**
    (国交省サイト利用規約/政府標準利用規約,允许加工再利用,标注出处)——推荐 live 试点对象。
  - 租金相场:无同等官方开放源;候选:不动产经济研究所等商业报告(需商务)、或社区自采
    (authorized_csv/user_submitted 类,样本小),或 P2 后联系 Recruit 商务许可(用户动作)。

## 补充:国交省土地総合情報システム(推荐替代试点)——09-07 实测

| 检查项 | 结果 |
|---|---|
| terms/再利用 | 政府开放数据框架:国交省站点按政府標準利用規約(CC BY 4.0 兼容),成交信息可加工/再利用,需**出所明記**(数据来源标注) |
| robots | 未取得(tochi.mlit.go.jp / land.mlit.go.jp **国内直连与 7897 代理均不可达**,解析/连接失败) |
| 网络现实 | 采集执行节点必须能访问 land.mlit.go.jp → **海外/日本执行**(Render staging 免费层为海外区,可行;国内网络不可) |
| 采集设计前置 | 低频率(政府站)、stored fixtures 先行、robots/rate-limit 登记(补取后)、出所明記进报告模板 |

**结论**:国交省是 terms 合规的 live 试点对象,但触发条件 = 采集运行环境在海外(部署到 Render worker 时自然满足);国内网络无法预览/开发抓取——开发期用已存 fixtures,不 live 抓。

## 建议(待用户决策)

1. **live 试点改国交省土地総合情報システム**(成交数据,官方开放,标注出处即可)——审查后可授权,衔接 runner 家族(osaka/yokohama 同构)
2. SUUMO 租金:暂保持本地快照读入(现状,不 live 抓取);如需真租金数据 → 商务联系 Recruit(用户)或替代源
3. tochidai.info:从 configs data_sources 摘除或改官方 URL(防误导:现行引用是镜像站)

## 备注
本报告不构成采集启动;试点源(国交省)terms 审查与采集设计另行出清单待批(AGENTS:robots/rate-limit/保留期登记 + stored fixtures 先行)。
