# Formal provenance contract audit（2026-08-31）

本审计针对 `codex/release-candidate`，只读取本地文件和离线 fixture；未访问第三方网站、Supabase、Auth、Storage 或部署目标，也未修改内容库、数据库或生成物。

## 审计范围与方法

- 内容库：`content-library.json`（并核对 `web/content-library.json`）。
- 输入：`data/input/minato_property_synthetic.csv`、`data/input/minato_tower_sample.csv`。
- 校验口径：P0-7 formal provenance contract 的必填来源字段、数据类别、挂牌/成交分离、数值字段与来源 URL 对齐要求。
- 结果只用于发布门禁，不表示 staging 或 production 已验证。

## 结果

| 范围 | 数量 | 可发布 | 阻断/问题 |
| --- | ---: | ---: | ---: |
| `content-library.json` | 70 条 | 0 | 70 |
| `data/input/*.csv` | 2 个 | 0 | 2 |

内容库的 70 条记录均未通过：缺少顶层 `version` / `data_class`，来源 `source_url` 与兼容别名 `url` 未形成正式对齐，租赁/买卖行也缺少 contract 要求的结构化 `market` 等字段。两份 CSV 均缺少正式 provenance 字段：`aggregation_method`、`limitations`、`method`、`missing_value_policy`、`observed_at`、`retrieved_at`、`rights_status`、`sample_size`、`source_period`、`version`。

`content-library.json` 与 `web/content-library.json` 当前 SHA-256 均为 `eb0fefae86a04204d9c0682f69e76a21497fcd1f18f5b8c4aa631197a1b71d1e`；这只证明两个生成副本一致，不证明内容具有发布权利或统计代表性。

## 处置与门槛

- 未自动把历史记录标成 `rights_confirmed=yes`，未把 modeled/synthetic 值伪装成市场事实，也未手工编辑生成内容库。
- 70 条历史记录和两份 CSV 保持 `blocked`；必须先确定 canonical 数据路径，再由负责人提供逐条授权 manifest 或明确保留为 synthetic fixture，重新生成并复审。
- `migration_baseline_status = reconciliation_required` 仍是硬停止条件；formal provenance migration 仅可作为 later-ID forward migration，经 C05 live reconciliation、provider backup/restore 与明确审批后处理。

因此，C06 的离线审计证据已完成，但 provenance 集成和正式发布门禁仍为 **BLOCK / NOT AUTHORIZED**。
