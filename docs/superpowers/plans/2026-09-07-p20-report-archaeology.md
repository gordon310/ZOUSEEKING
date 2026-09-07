# P2-0 报告链路考古与目标架构(2026-09-07)

考古结论 + P2-1/P2-3 设计基线。红线延续:字段冻结 forward-only、无 synthetic 冒充真实、汇率/模型需 dated source。

## 1. 现状:四条报告链并存

| 链 | 位置 | 内容 | 数据类 | 合规 |
|---|---|---|---|---|
| A. Edge jphouse-run | supabase/functions | **硬编码东京基准 × 人工系数(factor)× 汇率 0.0423** 排版;`isLegacyExecutionEnabled` 开关 | modeled(无版本/无来源) | ❌ 硬编码汇率/基准、字符串金额、无 dated source |
| B. FastAPI run_generation_job | backend/app/main.py:169 | 匹配 `web/content-library.json`(成品字符串)→ property_reports;未命中=**诚实占位**("等待采集器补全"+fallback_sources) | scraped_aggregate(快照) | ✅ 无假数据,但输出字符串化,不读数值源 |
| C. free preview | backend/app/intake/completeness.py:157 | 完整度打分(真)+ acquisition_costs=`rules_not_loaded`/None + comparable=`not_checked` | — | ⚠️ 空壳(规则未接) |
| D. configs/content-library | configs/*/web/content-library.json | 真实相场成品(字符串排版 + 汇率 4.23 写死 note) | scraped_aggregate | ⚠️ 内容真、数值在生成时字符串化 |

数值源头:`data/collected/{family}_sources.json` = **数值化快照**(rents: {1LDK: 22.3 万…};sale: {layout_price_man_yen, unit_man_yen_per_sqm}+ 来源更新日期 + config 路径)——P1 采集链已产出,**未接任何报告路径**。

前端(app.js runJphouseFromMyPage):canUseAuthenticatedBackend ? FastAPI `/api/jobs/{id}/run`(轮询)→ : Edge `jphouse-run`(legacy 通道仍在)。

## 2. ⚠️ 产品级冲突:D6 决策(阻断深度报告内容设计)

- `rents` 数值源自 **SUUMO 相场**(2026-07-10 快照,已存 fixtures)。
- 授权审查(2026-09-07-source-authorization-review.md)结论:SUUMO 利用規約 **Article 3(7) 商业用途需 Recruit 书面许可**。
- 小象避坑是**收费产品** → 深度报告(付费解锁)输出 SUUMO 租金 = 违约。
- `sale` 数值源自国交省成交(政府开放,标注出处即可)——**无冲突**。

| 选项 | 内容 | 后果 |
|---|---|---|
| D6a | 报告只含国交省 sale 侧(成交均价/㎡)+ 诚实标注租金侧"待授权源";砍租买比或标注不可比 | 合规最快;深度报告信息量减半(无租金对比) |
| D6b | 用户商务联系 Recruit/SUUMO 许可(书面,含数据再利用范围) | 全量报告;商务前置(数周~月,阻塞 P2-3) |
| D6c | 租金源替换:自采(authorized 房东/管理会社 CSV)、公开统计替代源 | 合规自采;样本覆盖降级,设计另行评估 |
| D6d | 免费预览含租金(产品免费面)+ 付费报告只含 sale | 仍属商业产品展示 SUUMO 内容——同违约,不推荐 |

**推荐 D6a**(先合规闭环,sale 侧真实报告即有价值;D6b 可并行商务不阻塞开发)。待用户确认。

## 3. 目标架构(P2-1/2-3 基线)

```text
query(任意区/asset/月)
  → FastAPI run_generation_job(唯一权威路径;Edge 退役)
      → 匹配 data/collected/*_sources.json(family=prefecture 判定 + ward + 数值)
          命中 → 数值行 → 报告排版(数值字段 + display 串分开;JPY canonical)
          未命中 → 诚实空态(现有 "等待采集器补全" + 来源标注)——零 synthetic
  → property_reports(数值 JSONB + 元数据:period/source/sample/class)
  → 前端渲染
```

关键改造(相对 B 现状):
1. **匹配源切换**:content-library(字符串成品)→ collected_sources(数值)——引擎读数值,前端排版与 DB 存储分离。
2. **free preview 接真实**:acquisition_costs rules 加载(费率表→估算真值,带 version);comparable 检查接 collected(命中 ward 才可比)。
3. **Edge 退役**:前端删 Edge 分支 + supabaseReportToRecord;函数 disable/删;isLegacyExecutionEnabled 置 false。
4. **汇率服务**(D5,可 P2-4):汇率表(forward migration,带 source/effective_date)替代一切硬编码 0.0423/4.23。
5. 输出结构:rental/sale 行 = {layout, area_min/area_max, amount_jpy(数值 yen), unit_jpy(数值), currency, period, source_class: scraped_aggregate, sample 说明, limitations}——display 字符串由前端拼(不再存字符串金额)。
6. 区外/等级 query(非 ward):明确"暂无该粒度数据"而非跨 ward 平均(AGENTS 禁止);可选 ward 对比视图(后续)。

## 4. P2-1/P2-3 单元细化(更新 09-06 规划)

| 单元 | 内容 | 验收 |
|---|---|---|
| P2-1 收敛 | 前端单通道(FastAPI)+ Edge 退役 + 测试 | 分析流无 Edge 引用;legacy 分支删;spec 绿 |
| P2-3a free preview | rules 加载 + 真实估算 + comparable 检查 | preview 返回真估算(非 None);测试断言 |
| P2-3b 报告引擎 | collected_sources 数值读入 + 匹配 + 数值化排版 + property_reports 数值 JSONB | 24+ward 命中报告数值正确;区外诚实空态;无 synthetic |
| P2-3c 汇率 | 汇率表 migration + 服务接入(替代硬编码) | 报告汇率带 source/date;测试无 0.0423 残留 |

依赖:D6 决策(阻断 P2-3b 租金侧,不阻 sale 侧与 P2-1)。

## 5. 风险

- collected_sources 覆盖 = 23ku+大阪23+横滨18 ≈ 64 ward 级;区外 query(县/市粒度)返回空态——产品语义要与 C 端对齐("支持 64 区,其余暂缺")。
- content-library 若仍供静态 web/社媒稿用,保留不动(B 链读它改读 collected 后,静态链互不影响)。
- P2-1 Edge 退役前确认无其它调用方(web/app.js 1335 单点;admin 无)。
