# 多月份数据质量与来源登记离线契约

状态：C19 offline candidate（2026-09-01）。这是本地可重放的质量门禁，不是生产数据授权、数据库迁移或上线批准。

## 输入与命令

严格准备流程需要四类本地输入：

- 严格 CSV：每行有稳定 `record_id`、日期、租售/挂牌成交口径、数值型 JPY 金额和单位，以及 `data_class`、`is_synthetic`。
- `data/source_registry.json`：登记版本化来源 URL 范围、来源类型（`official`、`partner`、`user_submitted` 或 `synthetic_fixture`）、权限状态、授权证据、条款复核日期、允许用途、负责人和 parser 版本。
- snapshot manifest：记录来源、捕获时间、相对内容路径、SHA-256、字节数和 parser 版本；运行时会重新读取本地字节校验。
- 版本化 `configs/data_quality_policy.json`：当前 `trend-policy-v1` 要求 3 个可比月份、每月 5 条、总计 15 条，并按区域、租售、挂牌/成交、数据类别、单位和币种分组。

```bash
PYTHONPATH=src python3 -m jp_property_publisher prepare \
  --input path/to/records.csv \
  --registry data/source_registry.json \
  --snapshots path/to/snapshots.json \
  --policy configs/data_quality_policy.json \
  --output-dir data/output/quality-run
```

运行始终保留 `prepared.csv`、`monthly_metrics.csv`、`quality_report.json` 和 `summary.json`。退出码 `0` 只表示离线质量检查无 error；退出码 `2` 表示检查阻断但审计输出仍已写出。

## 阻断与发布口径

- 缺失或不一致的来源、快照、hash、捕获时间、source period、parser version、单位、币种和重复业务记录会阻断事实指标。
- `rights_confirmed=yes` 不能替代 registry 中的授权证据；非 synthetic 来源必须有 confirmed 权限、允许用途和负责人。当前 placeholder 保持 `pending`。
- `verified_observation` 与 `scraped_aggregate` 可在权限证据齐全时进入事实聚合，但挂牌和成交始终分组；金额以数值 JPY 保存，指标用中位数并带样本数、期间、来源/快照和限制。
- `modeled_estimate` 不进入事实指标或趋势；`synthetic_fixture` 只能在 `fixture_only` scope 使用。一次运行混入 fixture 与事实类别会得到 `blocked_mixed_fixture`。
- 极端但可解析的数值只产生 warning，不静默修复；无效数值、时区缺失、负值和趋势样本不足会明确记录原因。

## 运行边界

`src/jp_property_publisher/pipeline.py` 没有网络、数据库、Storage 或 provider 依赖；仓库 fixture 是 synthetic、可重放且不代表真实市场。C19 未修改历史输入记录、未联网抓取、未自动填充授权或 provenance，也未新增/应用 migration。进入真实发布前仍需完成 migration baseline reconciliation、来源 rights 审核、历史重建、备份/恢复、SQL/RLS 和人工发布批准。
