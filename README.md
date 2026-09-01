# 日本房产数据发布

用于把**人工核验、具备使用权限**的日本房产租售记录，整理为可审核的数据表、统计摘要和小红书图文草稿。

本项目不包含 SUUMO、at home 或其他平台的爬虫，也不应复制房源图片、介绍文字、经纪人联系方式等受保护内容。

## 工作流程

1. 在 `data/input/` 中维护人工录入的成交/挂牌记录。
2. 每条记录填写来源链接、核验日期、`rights_confirmed=yes` 和 `data_class`。
3. 运行脚本生成标准化 CSV、区域统计、图表数据和待审核的小红书草稿。
4. 人工核对数字、来源和措辞后，再发布。

## 快速开始

需要 Python 3.9+，不依赖第三方库：

```bash
PYTHONPATH=src python3 -m jp_property_publisher normalize \
  --input data/input/minato_tower_sample.csv \
  --output data/output/minato_tower_normalized.csv

PYTHONPATH=src python3 -m jp_property_publisher report \
  --input data/output/minato_tower_normalized.csv \
  --title "东京港区塔楼：近三年租售观察" \
  --output-dir data/output/minato_tower_report
```

输出目录会包含 `summary.json`、`monthly_metrics.csv` 和待审核的
`xiaohongshu_draft.md`。静态网站预览：

```bash
python3 -m http.server 8787 -d web
```

## Schema 开发边界

`supabase/migrations/` 是唯一允许新增的 forward migration history。
`backend/sql/` 仅保留历史 bootstrap、恢复、生成或比对材料，不能拼接成新的建库入口。
当前 `migration_baseline_status = canonical_local_pass_live_reconciliation_required`；
这表示 canonical history 已通过本地验证，但 staging/production reconciliation 仍未获批。

提交 schema 相关改动前，从仓库根目录运行只读审计：

```bash
python3 scripts/check_schema_ownership.py
npm run check:schema-ownership
```

审计清单、重复对象与 forward-fix/恢复门槛见
[`docs/architecture/schema-ownership-audit.md`](docs/architecture/schema-ownership-audit.md)。
不要执行 linked `db push`、`migration repair`、staging/production reset 或未经批准的 live SQL。

## 输入字段与发布原则

详见 [`docs/data-dictionary.md`](docs/data-dictionary.md)。最少应包含交易/挂牌日期、租售类型、区域、建筑名称、面积、价格或月租、来源链接、核验日期和权利确认。

- 单条房源信息仅作研究底稿；公开内容以聚合趋势为主。
- 不发布可识别的个人信息、房东/租客信息、室内照片、户型图或受版权保护的描述。
- `listing`（挂牌）与 `closed`（已成交）必须区分；挂牌价不等于成交价。
- 文章内说明样本范围、数据来源类型和局限性，避免把样本结果表述为全市场事实。
