# 数据字典

每行代表一条**已获得使用许可**且人工核验过的租售样本。

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `record_date` | `2025-06-15` | 挂牌日或成交确认日，必须在发布时说明口径 |
| `market` | `sale` / `rental` | 出售或出租 |
| `status` | `listing` / `closed` | 挂牌或已成交；两者不可混算 |
| `prefecture` | `Tokyo` | 都道府县 |
| `ward` | `Minato` | 区/市 |
| `building_name` | `匿名化塔楼A` | 仅在授权允许时保留；公开文章可只呈现区域 |
| `area_sqm` | `55.2` | 专有面积（平方米） |
| `amount_yen` | `320000` | 月租或成交总价，按 `market` 区分 |
| `source_url` | `https://example.com/record/1` | 允许引用的来源页面或内部授权资料链接 |
| `verified_on` | `2026-08-23` | 人工核验日期 |
| `rights_confirmed` | `yes` | 仅 `yes` 可进入发布流程 |

可选字段如 `layout`、`station`、`walk_minutes`、`floor`、`built_year` 可用于后续细分分析。

测试或版式演示数据应增加 `is_synthetic=yes`，并与人工核验的真实数据分文件保存，不得作为真实市场数据发布。

## 第一阶段项目数据契约

第一阶段的项目主表使用 `project_type` 区分：`residential`（住宅）、`new_build`（预售/新建项目）和 `commercial_investment`（商业项目投资）。三类项目共享区域、项目身份、面积、价格、来源和可信度字段；类型专属字段分别存放在 `residential_details`、`new_build_details` 和 `commercial_investment_details`。

所有可用于分析的字段必须同时具备以下元数据：

| 元数据 | 说明 |
| --- | --- |
| `data_class` | `verified_observation`、`scraped_aggregate`、`modeled_estimate`、`synthetic_fixture` 或 `user_submitted` |
| `source_id` | 来源登记表中的来源 ID |
| `observed_at` | 数据观察或提交时间 |
| `confidence` | `high`、`medium`、`low` 或 `unreviewed` |
| `currency` / `unit` | 金额币种和数值单位，不允许只保存展示字符串 |
| `evidence_id` | 可定位到原始文件、URL、页码或字段位置的证据 ID |

`analysis_metrics` 保存计算后的指标，必须包含 `calculation_version` 和 `assumption_set`；`risk_findings` 保存风险依据、所需补充资料、建议动作和置信度。法规内容进入 `policy_documents`，保留来源、发布日、生效日、失效日和人工复核记录。

`product_events` 只保存脱敏后的消费特征和聚合所需字段，不保存姓名、邮箱、电话、合同原文或可直接识别用户的项目链接。消费行为必须标记用途范围，默认使用 `internal_product_analytics`。
