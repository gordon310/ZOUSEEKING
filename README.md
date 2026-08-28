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
python3 -m jp_property_publisher normalize \
  --input data/input/minato_tower_sample.csv \
  --output data/output/minato_tower_normalized.csv

python3 -m jp_property_publisher report \
  --input data/output/minato_tower_normalized.csv \
  --title "东京港区塔楼：近三年租售观察" \
  --output-dir data/output/minato_tower_report
```

输出目录会包含：

- `summary.json`：可复核的聚合指标；
- `monthly_metrics.csv`：按月份统计；
- `xiaohongshu_draft.md`：待人工审核的发布草稿。

## 小红书内容库与手机查询页

生成小红书素材包时，也可以同步写入内容库，并生成一个手机优先的查询页面：

```bash
/Users/gordonmac/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  scripts/generate_xhs_package.py \
  --config configs/xhs_minato_tower.json \
  --output-dir data/output/minato_property_synthetic_report
```

内容库文件：

- `data/content_library.json`：长期保存的结构化内容库；
- `web/content-library.json`：手机网站读取的数据副本；
- `web/library/<slug>/images/`：网站展示用配图。

本地预览手机查询页：

```bash
python3 -m http.server 8787 -d web
```

然后打开：

```text
http://localhost:8787
```

目前支持按标题、地区、月份、房型、RMB、正文关键词做模糊搜索。

## 输入字段

详见 `docs/data-dictionary.md`。最少应包含：交易/挂牌日期、租售类型、区域、建筑名称、面积、价格或月租、来源链接、核验日期和权利确认。

## 数据与发布原则

- 单条房源信息仅作研究底稿；公开内容以聚合趋势为主。
- 不发布可识别的个人信息、房东/租客信息、室内照片、户型图或受版权保护的描述。
- `listing`（挂牌）与 `closed`（已成交）必须区分；挂牌价不等于成交价。
- 文章内说明样本范围、数据来源类型和局限性，避免把样本结果表述为全市场事实。
