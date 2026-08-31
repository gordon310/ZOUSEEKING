# 日本装修分析 API

版本：`0.1.0`
价格快照：`jp-renovation-2026-08-31-v1`

这个 API 是无状态的日本住宅室内装修初筛服务。它输出 JPY 区间、图片状态观察、估价假设、排除项和实际采用的公开价格来源；不保存上传图片，不返回施工报价，也不判断隐藏结构安全。

## API 入口

### `POST /api/renovation/estimates`

适用于已经由 ZOUBEACON/Skill/人工完成图片观察的请求。它只做结构化结果校验和价格计算，不需要 OpenAI API Key。

```json
{
  "context": {
    "location_hint": "大阪市大正区",
    "floor_area_m2": 80,
    "built_year": 1980,
    "structure": "detached",
    "renovation_goal": "purchase_screening"
  },
  "photos": [
    {
      "id": "bathroom-01",
      "room": "bathroom",
      "observations": [
        {
          "component": "unit_bath",
          "condition": "aged",
          "scope": "replace",
          "confidence": "medium",
          "quantity": 1,
          "notes": "浴槽、墙板有明显使用年限感"
        }
      ]
    },
    {
      "id": "living-01",
      "room": "living_room",
      "observations": [
        {
          "component": "wallpaper",
          "condition": "stained",
          "scope": "surface_refresh",
          "confidence": "medium",
          "quantity": 1,
          "area_m2": 20,
          "notes": "墙面有污渍，施工面积由用户测量"
        }
      ]
    }
  ]
}
```

`room` 只能使用 `exterior`、`bathroom`、`kitchen`、`living_room`、`bedroom`、`balcony`。它是照片整理标签，不是自动识别结论。

`component` 当前支持：

- `unit_bath`：整体卫浴/ユニットバス
- `wallpaper`：墙纸/墙布/クロス
- `flooring`：复合地板
- `kitchen`：系统厨房
- `toilet`：厕所设备
- `washstand`：洗面化妆台
- `tatami`：畳表替え

面积型项目必须提供 `area_m2`。API 不会从一张照片推造施工面积。`unit` 型项目使用 `quantity`，同一房间同一构件的重复照片只计一次。

### `POST /api/renovation/analyses`

适用于直接上传图片的流程，使用 `multipart/form-data`：

- `manifest`：上面请求的 JSON 字符串；上传模式下每个 photo 还必须有 `filename`。
- `images`：与 manifest 的 `filename` 一一对应的 JPG/PNG，单文件沿用 20 MiB 限制，最多 12 张。

如果 manifest 已包含 `observations`，API 直接使用这些结构化观察。如果没有观察，API 只在配置 `RENOVATION_VISION_API_URL` 后调用视觉提供方；没有配置时返回：

```json
{
  "detail": {
    "code": "vision_provider_not_configured",
    "message": "图片状态识别服务尚未配置；可先在 /api/renovation/estimates 提交结构化照片观察。"
  }
}
```

因此，当前没有 OpenAI Key 时，推荐由 ZOUBEACON 的 Skill 或其他已授权视觉模型读取图片，生成 `observations` 后调用 `/estimates`。API 本身不会把文件名、EXIF、图片模糊程度冒充装修识别结果。

视觉提供方的最小 HTTP 契约：

```json
{
  "context": {},
  "photos": [
    {
      "id": "bathroom-01",
      "room": "bathroom",
      "filename": "bathroom-01.jpg",
      "media_type": "image/jpeg",
      "content_base64": "..."
    }
  ]
}
```

提供方返回：

```json
{
  "photos": [
    {
      "id": "bathroom-01",
      "observations": [
        {
          "component": "unit_bath",
          "condition": "aged",
          "scope": "replace",
          "confidence": "medium",
          "quantity": 1,
          "notes": "浴室设备明显老化"
        }
      ]
    }
  ]
}
```

## 2026-08-31 价格快照

下列价格是公开资料的参考区间，不是本 API 自行声称的全国统一单价。每次响应会返回实际使用的 `sources`、`retrieved_on` 和 `price_snapshot_version`。

| 项目 | 当前快照区间 | 计价单位 | 价格依据 |
| --- | ---: | --- | --- |
| 整体卫浴更换 | ¥600,000–¥1,500,000 | 一套 | [リフォームガイド](https://www.reform-guide.jp/topics/unitbath-koukan/)，并用 [TOTO 户建参考价格](https://jp.toto.com/reform/library/cost/bathreformhouse/) 交叉核验 |
| 标准墙纸/クロス | ¥1,100–¥1,550 | m² | [ホームプロ](https://www.homepro.jp/kabegami/kabegami-basic/2270la)，2026-01-16 更新；未含下地调整 |
| 系统厨房（I 型 2550mm，含部分内装） | ¥760,000–¥1,330,000 | 一套 | [TOTO 厨房参考价格](https://jp.toto.com/reform/library/cost/kitchenreform/)，含税、特定规格 |
| 复合地板 | ¥15,000–¥20,000 | m² | [ホームプロ公寓改修参考](https://www.homepro.jp/renovation/renovation-point/13461-wg/)，按每10m² ¥150,000–¥200,000换算 |
| 普通洋式厕所更换 | ¥80,000–¥350,000 | 一套 | [アンドリフォーム](https://andreform.jp/article/toilet-cost)，2026-08-26 更新 |
| 洗面化妆台同尺寸更换 | ¥150,000–¥300,000 | 一套 | [イズホーム](https://ishome.ltd/mizu/reform-guide/washroom/)，大阪/兵库/和歌山数据，不代表全国 |
| 标准畳表替え | ¥8,000–¥10,500 | 畳 | [ミツモア](https://meetsmore.com/services/tatami-exchange)，基于近两年报价数据 |

用户提出的墙纸 `¥800/m²` 可以作为内部自定义低价档，但当前快照的标准施工参考从 `¥1,100/m²` 起；下地处理、拆除、废材和家具移动需另行确认。

## 计算与解释规则

1. 只对 `scope=replace` 或 `scope=surface_refresh` 的可计价观察生成项目。
2. 维修、监测、未知状态只进入限制说明，不自动按更换收费。
3. 同一 `room + component` 的重复照片合并；面积取已提供观察中的最大值，避免重复计费。
4. 总区间是去重后分项区间的相加；税费总口径固定返回 `approximate`，因为来源含税/未税口径不完全一致。
5. 缺少地区、面积、房龄、结构或装修目标时，降低 `confidence` 并写入假设；不伪造当前市场价。
6. 管线、承重结构、地基、石棉、防水层和隐藏漏水不由照片确认，也不默认计入。

## API 设计决定

- 沿用 ZOUBEACON 现有未版本化 `/api/...` 路径；破坏性变更时新增 `/api/v2/...`，不原地改变 v0.1 响应字段。
- `/estimates` 和 `/analyses` 都是无状态计算，没有数据库写入，因此同一请求重试不会产生重复记录，不需要 `Idempotency-Key`。
- 价格目录是小型有界快照，不提供分页；结果携带版本和来源，便于客户端缓存和审计。
- 上传分析在视觉提供方未配置时失败得明确，不返回低质量或伪造的装修状态。
