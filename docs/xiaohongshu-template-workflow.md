# jphouse 房产数据生成流程

这个流程用于把“日本房产数据主题”快速生成成网站可展示的数据内容。

模板名：`jphouse`

适合以后复用的场景：

- 换标题：例如“东京港区塔楼，租还是买？”改成“大阪市中心公寓，租还是买？”
- 换区域：港区、涩谷区、中央区、大阪、京都等
- 换资产类型：塔楼、公寓、民宿、酒店、土地等
- 换数据月份：每月更新一次

## 1. 数据采集原则

公开发布内容只使用聚合数据，不直接搬运单套房源文案、图片、户型图、联系方式。

目前建议采集这些字段：

- 地区：例如东京港区
- 房型：1LDK / 2LDK / 3LDK
- 面积段：例如约40–45㎡
- 租金：日元/月
- 租金每平方米单价：日元/㎡/月
- 成交均价：日元
- 买卖每平方米单价：日元/㎡
- 发布当天汇率：100日元≈多少RMB
- 数据来源链接：只放在配置或底稿里，不默认放进网站展示正文

## 2. 模板配置

当前模板文件示例：

```bash
configs/xhs_minato_tower.json
configs/jphouse_tokyo_chuo_tower.json
```

以后最常改这些字段：

```json
{
  "title": "东京港区塔楼，租还是买？",
  "publish_month": "2026年8月",
  "cover": {
    "line1": "东京港区",
    "line2": "塔楼租还是买？"
  }
}
```

如果只想换标题和封面标题，改这几个字段就够。

如果换数据，改：

```json
{
  "sections": {
    "rental": {
      "rows": []
    },
    "sale": {
      "rows": []
    }
  },
  "summary": {
    "line": "1LDK｜约3.36%｜2LDK｜约2.62%｜3LDK｜约3.26%"
  }
}
```

## 3. 生成数据素材

推荐用 Codex 自带 Python 环境运行，因为里面已经有图片库：

```bash
/Users/gordonmac/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  scripts/generate_xhs_package.py \
  --config configs/xhs_minato_tower.json \
  --output-dir data/output/minato_property_synthetic_report
```

生成结果：

```bash
data/output/minato_property_synthetic_report/
├── data_detail.md
├── source_config.json
└── images/
    ├── 01-cover-clean.png
    ├── 02-rental-all-layouts-clean.png
    └── 03-sale-all-layouts-clean.png
```

## 4. 网站展示内容

图片仍然会生成，供网站详情页展示：

1. 封面：`01-cover-clean.png`
2. 租房子：`02-rental-all-layouts-clean.png`
3. 买房子：`03-sale-all-layouts-clean.png`

数据正文使用：

```bash
data/output/minato_property_synthetic_report/data_detail.md
```

检查：

- 标题是否符合这次主题
- 图片是否是新版
- 日元和 RMB 是否都有
- 汇率月份是否正确
- 是否还有小红书发布语气、话题标签、评论区尾巴等不该进网站的内容

## 5. 以后怎么让我生成新内容

可以直接说：

> 用 jphouse 模板，标题改成「东京中央区塔楼，租还是买？」，月份用本月，数据我稍后给你。

或者：

> 复制港区模板，做一篇涩谷区 1LDK/2LDK/3LDK 租售对比。

我会优先改配置文件，再运行生成器，不再从零写文案和图片。

也可以直接说：

> 用 jphouse 模板，标题换成东京中央区塔楼，数据按本月生成。
