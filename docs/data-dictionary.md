# 数据字典

正式数据每行代表一条**已获得使用许可**且人工核验过的租售样本；严格多月份流程之外的 sample 只可作为明确标注的离线 fixture，不得据此推断真实市场。

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

## 严格多月份准备字段

`prepare` 流程要求每条记录增加以下字段，并与本地 source registry 和 snapshot manifest 交叉核验：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| `record_id` | `source-2026-08-001` | 稳定主键；重复会阻塞。 |
| `amount_unit` | `jpy_total` / `jpy_monthly` | 出售必须是 `jpy_total`，出租必须是 `jpy_monthly`。 |
| `currency` | `JPY` | 当前分析口径固定为 JPY。 |
| `source_id` | `mlit-transactions-v1` | 对应来源登记项。 |
| `snapshot_id` | `snap-2026-08-01` | 对应本地快照 manifest。 |
| `snapshot_hash` | SHA-256 hex | 必须与本地快照字节重新计算的 hash 相同。 |
| `snapshot_captured_at` | `2026-08-01T00:00:00+00:00` | 必须带时区并和 manifest 一致。 |
| `source_period_from/to` | `2026-08-01` / `2026-08-31` | 来源覆盖期间；记录日期必须落在期间内。 |
| `parser_version` | `parser-v1` | 解析器/转换契约版本，须和来源及快照一致。 |
| `is_synthetic` | `yes` / `no` | 必须和 `data_class` 匹配；synthetic 不得冒充事实。 |

`monthly_metrics.csv` 会按区域、租售、`listing`/`closed`、数据类别、单位和币种分组，输出每月样本量、中位数、期间、聚合方法、来源/快照 hash、趋势资格与限制。`modeled_estimate` 不进入事实指标；趋势不足时只显示明确的 `trend_insufficient_periods` 或 `trend_insufficient_sample`，不能称为趋势。来源 URL 本身不等于授权，当前 placeholder registry 仍为 `pending`。

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

## Osaka 单项目 intake（staging）

新单项目分析通过 FastAPI 写入 Supabase staging；浏览器不直接写入以下私有表。匿名会话只保存 `token_hash`，原始 token 只在创建响应中返回给浏览器并放入 `sessionStorage`。会话在创建后 24 小时到期；过期后立即不可读，文件对象由下一次 API 清理任务删除。已转正项目不参与匿名清理。

| 表 | 用途 | 关键字段与限制 |
| --- | --- | --- |
| `analysis_sessions` | 匿名分析会话及转正状态 | `purpose` 仅为 `self_use` / `rental_investment`；`owner_user_id`、`property_id`、`token_hash`、`expires_at` 由服务端管理 |
| `project_inputs` | 用户提交的文字、URL 和文件元数据 | `input_type` 为 `text` / `url` / `pdf` / `image`；文件最大 20 MiB；`processing_status` 初始为 `manual_review` 或 `pending` |
| `project_field_evidence` | 字段候选值和来源证据 | 保留原始值、标准化值、单位、定位、提取方式和可信度；同一证据不可覆盖 |
| `project_fields` | 用户确认后的当前字段值 | 每个会话/字段唯一；单位由服务端字段白名单推导；确认状态包括 `confirmed`、`corrected`、`unknown`、`conflict` |
| `free_previews` | 免费预览快照 | 保存完整度、费用项目、风险摘要、可比样本状态和 `calculation_version`；每个会话一份 |
| `intake_rate_limits` | 按来源或会话限制操作频率 | 只保存 abuse key 的哈希、动作、窗口、次数和过期时间，不保存原始 IP |

这些表启用 RLS，并撤销 `anon` 与 `authenticated` 的直接访问；只有 FastAPI 使用受信任的数据库连接写入。阶段一不执行 OCR、AI 提取、市场估价、税费金额计算或法律结论。缺少证据只标记为资料不足。

## Schema 所有权与字段演进

数据库字段的定义和约束必须沿唯一 forward history 演进：新字段先更新本数据字典，再新增 `supabase/migrations/` 中的 reviewed forward migration、解析映射和离线断言。`backend/sql/` 中的旧脚本只用于来源比对或 disposable local/test compatibility，不能作为新的建库入口。

当前 `migration_baseline_status = canonical_staging_reconciled_production_pending`。
canonical history 与 staging 的 later-ID reconciliation、provenance constraints、
逻辑备份隔离恢复和权限验收已通过；production 字段状态仍未验证。旧 bootstrap
字段仍不是新的 schema 来源。

完整文件级盘点见 [`docs/architecture/schema-ownership-audit.md`](architecture/schema-ownership-audit.md)。金额、面积和位置继续以带单位/币种的数值列保存，展示文本不得反向作为分析输入。
