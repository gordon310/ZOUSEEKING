# 小象房产套件(ZOUSEEKING/ZOUBEACON)· 完整技术架构与前后端逻辑

> 生成时间:2026-09-11 · 代码基线:`5c71a26`

> 本文档由 5 路并行代码深读汇总;每条关键结论附 `文件:行号` 证据。


## 目录

1. 后端消费端业务域(物件录入/免费预览/深度报告/照片定位)

2. 后端平台域(计费/额度/后台/隐私/鉴权)

3. 前端全部页面与逻辑

4. 数据层与数据库 schema/RLS

5. 采集管道 + 部署运维


---


# 第 1 部分 · 后端消费端业务域(物件录入/免费预览/深度报告/照片定位)


# 后端消费端业务域技术说明(小象避坑/小象数据)

> 范围:`/Users/gordonmac/GordonDev/JPPropDIs`(只读分析,未修改任何文件)。所有结论附 `文件:行号`;无法从代码确认的标注「未确认」。

---

## 1. 模块职责一览

| 文件 | 一句话职责 |
|---|---|
| `backend/app/intake/models.py` | 物件录入的 Pydantic 请求/响应契约 + 服务端字段单位表 `FIELD_UNITS` |
| `backend/app/intake/completeness.py` | 确定性完整度/风险汇总/可比市场检查,并组装免费预览 |
| `backend/app/intake/cost_estimator.py` | 取得费用估算(法定上限/官定表可算项 + needs_input 项) |
| `backend/app/intake/fx.py` | 汇率换算(JPY 为规范币种,带来源/日期) |
| `backend/app/intake/geocoding.py` | GSI 反向地理编码适配(设备坐标→町级地址候选) |
| `backend/app/intake/market_engine.py` | 采集快照加载、地址/行政区匹配、成交参考报告生成 |
| `backend/app/intake/repository.py` | 参数化持久化(会话/输入/字段/预览/转换/项目/限流/过期清理) |
| `backend/app/intake/storage.py` | Supabase Storage 私有大桶上传/删除 + 文件类型/大小校验 |
| `backend/app/intake/tokens.py` | 匿名会话 token 生成与 SHA-256 摘要校验 |
| `backend/app/routes/intake.py` | `/api/intake` 边界:会话、输入、文件、定位、字段、预览、转换、项目读取 |
| `backend/app/jphouse_service.py` | 查询 key/标题、本地记录匹配、占位 xhs、占位报告来源 |
| `backend/app/recognition/exif.py` | 纯 stdlib、零依赖的 JPEG EXIF GPS 解析 |
| `backend/app/recognition/municipality.py` | JIS 团体代码→行政区映射(含汉字→简体转换) |
| `backend/app/recognition/service.py` | 识别编排:EXIF→GSI→muniCd→可选 AI 房源识别 |
| `backend/app/recognition/routes.py` | `/api/recognition` 边界(需登录) |
| `backend/app/services/analysis_contracts.py` | 版本化指标/风险/政策引用数据契约(MetricResult/RiskFinding/PolicyDocument) |
| `backend/app/services/provenance.py` | 来源/快照/证据记录(可审计) |
| `backend/app/renovation/models.py` | 装修估算请求/响应契约(房间/部件/状况/范围枚举) |
| `backend/app/renovation/pricing.py` | 有日期的公开价格快照 + 确定性概算规则 |
| `backend/app/renovation/vision.py` | 可选的图片状况识别 provider 适配(HTTP) |

---

## 2. 完整业务逻辑

### 2.1 物件录入会话流程

**会话状态机**:`draft → preview_ready → converted`(过期→`expired`),DB 约束锁定枚举 `backend/sql/.../20260825000400_property_intake.sql:55-56`。

1. **创建会话** `POST /api/intake/sessions`(`routes/intake.py:189-215`)
   - 限流 `session_create` 每小时 10 次(`routes/intake.py:197`),按来源 IP 哈希(`routes/intake.py:115-123`)。
   - 生成 `token_urlsafe(32)` 明文 token 仅返回一次,库里只存 SHA-256 摘要(`tokens.py:23-25`;`routes/intake.py:198,204`)。
   - TTL 24 小时 `SESSION_TTL`(`routes/intake.py:58`;测试断言 `expires_in_seconds==86400`,`tests/api/test_intake_routes.py:13`);`expires_at` 约束 ≤ 创建+24h5m(`...property_intake.sql:62-63`)。
   - 返回后注册后台清理任务(`routes/intake.py:209`)。

2. **添加文本/URL 输入** `POST /api/intake/sessions/{id}/inputs`(`routes/intake.py:218-231`)
   - 限流 `input_create` 30/小时(`:227`)。
   - 校验(`models.py:54-102`):`text` 必带 `raw_text`(≤20000),`url` 必带 `source_url`(≤2048);URL 必须 https、有 hostname、含 `.`、不得含用户名/密码/fragment、不得含空白(`models.py:59-102`;测试 `test_intake_models.py:23-29`)。
   - 落库 `processing_status='manual_review'`,输入不做自动解析(`repository.py:155`;测试 `test_intake_routes.py:35`)。

3. **上传文件** `POST /api/intake/sessions/{id}/files`(`routes/intake.py:234-278`)
   - 限流 `file_upload` 10/小时(`:244`)。
   - 读 `MAX_UPLOAD_BYTES+1`,超 20 MiB → 413(`:245-247`;`storage.py:15`)。
   - 类型/内容校验:仅 pdf/jpeg/png,扩展名须与魔数匹配(`storage.py:16-20,44-56`);失败 400。
   - 先上传 Supabase Storage 私有桶(env `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`/`INTAKE_BUCKET`,默认桶 `property-intake`),路径 `{session_id}/{uuid4}{ext}`,写失败 503;随后写 `project_inputs`,DB 失败则回滚删除对象(`routes/intake.py:252-277`;`storage.py:59-78,81-109`)。
   - 文件类输入的 `input_type` = `pdf`(application/pdf)否则 `image`,`processing_status='pending'`(`repository.py:177-195`)。

4. **保存定位** `PUT /api/intake/sessions/{id}/location`(`routes/intake.py:281-307`)
   - 限流 `location_capture` 5/小时,按 `session:{id}` 维度(`:291`)。
   - 校验(`LocationRequest`,`models.py:105-134`):lat∈[-90,90]、lng∈[-180,180]、`accuracy_m`∈(0,100000]、数值有限、`captured_at` 必须带时区、`consent_version` 非空 ≤100;`source` 固定 `device_geolocation`(`models.py:17,111`)。
   - 反向地理编码在 worker 线程执行(`asyncio.to_thread`),失败则候选为 None 但仍保存坐标(`routes/intake.py:292-302`)。
   - 保存到 `analysis_sessions`(`latitude/longitude/location_accuracy_m/location_source/location_captured_at/location_consent_version/address_candidate/address_source/address_precision`),仅当 `status<>'converted'`(`repository.py:312-351`)。

5. **确认字段** `PUT /api/intake/sessions/{id}/fields/{field_name}`(`routes/intake.py:310-335`)
   - `field_name` 必须在 `FIELD_UNITS` 白名单(16 个字段),否则 422(`models.py:19-37,156-162`;测试 `test_intake_routes.py:59-64`)。
   - 路径字段与请求体 `field_name` 不一致 → 422(`routes/intake.py:319-320`)。
   - 若引用 `source_input_id`,必须属于本会话,否则 404(`repository.py:224-235`;测试 `test_intake_routes.py:67-79`)。
   - 事务内先写 `project_field_evidence`(`extraction_method='manual'`,`confidence='unreviewed'`),再 upsert `project_fields`(`repository.py:220-274`)。单位由服务端 `FIELD_UNITS` 推导,客户端不能提交越权字段(如 `owner_user_id`)。

6. **免费预览** `POST /api/intake/sessions/{id}/preview`(`routes/intake.py:338-350`)
   - 限流 `preview_create` 20/小时,按会话(`:346`)。
   - `get_fields` → `build_free_preview` → `save_preview`;`save_preview` 同时把会话置 `status='preview_ready'` 并写 `purpose_locked_at`(首次)(`repository.py:276-310`)。**这是“字段/用途冻结”点**。

7. **转换为用户项目(注册后)** `POST /api/intake/sessions/{id}/convert`(**需登录** `require_user`,`routes/intake.py:353-388`)
   - 会话必须处于 `preview_ready`(`repository.py:384`);已转换且同 owner 可幂等返回原项目,否则 404(`repository.py:380-383`)。
   - 项目名 = 手工名或地址;都没有 → 422 `project_name_required`(`repository.py:399-404`;`routes/intake.py:370-374`)。
   - 地址归一化重复检查(owner 维度)→ 409 `duplicate_address`(`repository.py:406-419`;`routes/intake.py:375-379`)。
   - 名称占用检查/唯一约束 → 409 `project_name_taken`(`repository.py:421-432,464-465`;`routes/intake.py:380-384`)。
   - 落库 `properties`(owner_user_id, project_type='residential', prefecture='大阪府', city='大阪市', data_class='user_submitted', confidence='unreviewed', 带定位与地址来源)+ `residential_details`(`repository.py:434-480`),再更新会话 `owner_user_id/property_id/project_name/status='converted'/converted_at`(`repository.py:481-497`)。

8. **读取项目** `GET /api/intake/projects/{property_id}`(需登录,owner 限定,`routes/intake.py:391-401`;`repository.py:499-514`)。

### 2.2 免费预览 vs 完整/深度报告

| 维度 | 免费预览 | 完整/深度报告 |
|---|---|---|
| 入口 | `POST /api/intake/sessions/{id}/preview`(`routes/intake.py:338-350`) | `GET /api/reports/{query_key}`(`main.py:560-589`) |
| 鉴权 | 仅会话 token 头 `X-Analysis-Session`(匿名可用) | 必须登录 `require_user`(`main.py:561`) |
| 内容 | `completeness` + `acquisition_costs` + `risk_summary` + `comparable`(`completeness.py:194-209`;`models.py:213-220`) | `property_reports` 全量:`markdown/rental/sale/summary/images/data_sources/raw_record`(`main.py:196-217`) |
| 判定 | 由字段完整度确定性计算,无付费墙 | 由 `_has_report_unlock` 判定(`main.py:116-148,576-589`) |

**解锁判定 `_has_report_unlock`(任一满足)**:
- `payment_orders` 中 `product_code='risk_report_single'` 且 `subject_id={query_key}` 且 `status='paid'`(`main.py:120-123`);
- `c_plus_monthly` 订阅 active/trialing 且当月 `usage_quotas` 报告额度未耗尽(`main.py:126-134`);
- 或存在对应 `usage_events` consume 记录(fingerprint `c-plus-report:{key}`)(`main.py:136-141`)。

未解锁 → 只返回元数据 `{locked:true, query_key, slug, title, publish_month, unlock_hint}`,内容字段绝不外发(`main.py:577-588`;测试 `test_report_access.py:91-104`)。解锁后返回 `row_to_report`(`main.py:589`)。

### 2.3 完整度判定(`completeness.py`)

- 6 个维度(必需字段集,关键字段集):`identity / price_cost / yield / building_management / legal_transaction / source_trust`(`completeness.py:18-43`)。
- 字段值 = `FieldValue(value, confirmation_status, confidence, has_evidence)`(`completeness.py:10-15`)。
- 维度语义:
  - `_is_confirmed` = 值非空且状态 ∈ {confirmed, corrected}(`completeness.py:45,60-61`);
  - `status`:有缺失关键字段 → `insufficient_data`;全确认 → `complete`;部分 → `partial`;全缺 → `empty`(按 percent = 已确认/必需)(`completeness.py:68-86`);
  - `conflicts`:状态为 `conflict` 的字段单列(`completeness.py:71-75`)。
- `source_trust` 特殊:`_is_trusted` = 已确认 **且** has_evidence **且** confidence ∈ {high, medium}(`completeness.py:46,64-65,101-120`;测试 `test_completeness.py:69-79`)。
- `risk_summary`:missing_critical→severity `high`;conflict→`medium`;整体 `data_warnings`/`no_data_warnings`(`completeness.py:127-155`)。

### 2.4 comparable 判定(`_comparable_check`,`completeness.py:158-191`)

- 取已确认 `address`;无地址 → `{status:"not_checked"}`(`:171-174`)。
- 用 `match_snapshot_from_address` 匹配快照;无匹配 → `insufficient`(说明仅覆盖 东京23区/大阪市23区/横滨市18区)(`:184-186`)。
- 匹配 → `sufficient`,reference 为 `build_sale_report(...)["sale"]` 行(`:186-191`)。**绝不跨区近似**(`:166`)。

### 2.5 市场引擎如何匹配快照与地址(`market_engine.py`)

- 快照来源三族:`jphouse_23ku`(东京都)/`jphouse_osaka_wards`(大阪府)/`jphouse_yokohama_wards`(神奈川县)(`market_engine.py:32-36`)。
- 数据目录:优先 `data/collected/`,缺失回退内嵌 `backend/data/market_snapshots/`(`market_engine.py:123-124`);实测两目录 + `tests/fixtures/market_snapshots/` 均存在三份同名文件。
- 支持资产:`{塔楼,公寓,中古マンション,マンション}`(`:40`);`一户建/一戸建て`及非マンション → 返回 None(诚实空态)(`:163-167`)。
- 布局 `1LDK/2LDK/3LDK`(`:75`);单位换算 `MAN_YEN_TO_YEN=10000`(`:77`);`unit_yen_per_sqm`/`layout_amount_yen` 由 man-yen 转 yen(`:100-108`;测试 `test_market_engine.py:41-48`)。
- `match_snapshot`:先 prefecture 相等;有 ward 则归一化后按 ward 严格相等;ward 为空/`全部区` 时退回 city 层匹配(`:148-178`)。
- **地址变体归一化**:
  - 前端简体区名 → 日文区名:`WARD_ALIASES`(17 条,显式全名映射,非通用字符转换)(`:46-64,80-86`);
  - 都道府县变体:`PREFECTURE_ALIASES`(含简/日/去后缀)(`:69-73`);
  - `match_snapshot_from_address`:prefecture 别名前缀 + 快照 ward 名或简体反向查表(`:181-200`;测试 `test_market_engine.py:59-77`)。
- `build_sale_report`:仅成交侧(sale),`rental=[]`(D6a 未授权不输出)(`:216-222,278`);每行含数值 `amount_yen/unit_yen_per_sqm` + 展示串 + `data_class='scraped_aggregate'` + 期间 + 可选 CNY/USD(`:231-249`);并生成 markdown、`data_sources`(国交省取引価格情報)、`raw_record`(`:250-302`)。

### 2.6 汇率与成本估算口径

- **汇率**(`fx.py`):rates 存 `data/input/fx_rates.json`(当前 `version 2026-09-08-cfets-saf`,`as_of 2026-09-08`,CNY 0.043098,USD 0.006357,来源国家外汇管理局交叉换算);`convert_jpy` 返回 `amount=round(yen*rate)`+rate/as_of/source/version;无金额/无币种/无快照 → `None`(绝不臆造)(`fx.py:31-53,56-65`)。
- **取得成本**(`cost_estimator.py`,规则 `data/input/acquisition_cost_rules.json` `version 2026-09-08-r1`):
  - 可从申报价精确估算的项:中介手续费(宅建业法报酬上限阶梯:≤200万 5%;200万–400万 4%+2万;>400万 3%+6万)(`cost_estimator.py:44-53`)、印花税(国税庁 No.7140 第1号文书本则阶梯)(`:56-62`);
  - 依赖评估额/贷款/物件细节的 7 项一律 `needs_input`,给 basis 不猜金额(`:76-79,117-125`);
  - `estimated_total_jpy` 只累计已估项;`status` ∈ {`estimated`,`partial`,`insufficient_input`};`calculation_version=acquisition-cost-{version}`(`:81-133`;测试 `test_cost_estimator.py:30-39`,`test_completeness.py:25-44`)。

---

## 3. 照片定位链(recognition)

### 3.1 EXIF GPS 解析(纯 stdlib,`recognition/exif.py`)

- 入口 `parse_exif_gps(bytes)` → `{latitude, longitude}` 或 `None`(任何异常→None)(`exif.py:9-38`)。
- 流程:`SOI(FFD8)`→逐段扫描找 `APP1(0xE1)` 且段以 `Exif\0\0` 开头 → 取 TIFF(`exif.py:41-63`);TIFF 头判字节序 `II`(little)/`MM`(big),校验 marker=42,取 IFD0 偏移(`:66-77`);IFD0 找 GPS 子 IFD tag `0x8825`(`:17,95-99`;`_find_tag` 要求 type=4,count=1)。
- GPS 标签:`0x0001` 纬度半球(N/S)、`0x0003` 经度半球(E/W)、`0x0002` 纬度度分秒、`0x0004` 经度度分秒(`:21-24`)。
- 半球必须 ∈ {N,S} / {E,W},度量三元组长度必须为 3,否则 None(`:25-28`)。
- **度分秒换算**:`deg + min/60 + sec/3600`;值域 0–90 / 0–180;S/W 取负(`:29-36`;测试 `test_recognition_exif.py:28-39`)。
- rationals 用 type=5,分母为 0 → 返回空 → None(`_read_rationals` `:124-136`);内联值 ≤4 字节直接读,否则按偏移读取并做边界检查(`_value_bytes` `:102-116`)。

### 3.2 GSI 反向地理编码(`intake/geocoding.py`)

- 端点默认 `https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress`,可配 `REVERSE_GEOCODER_URL`(`geocoding.py:14-16,65-66`)。
- 请求 `?lon=&lat=`;超时 `REVERSE_GEOCODER_TIMEOUT_SECONDS` 默认 5,钳制 [1,15](`:64-75`);响应上限 64 KiB,超限报错(`:17,88-90`)。
- 只解析文档化字段:`results.lv01Nm`(町级地址)、`results.muniCd`(团体代码);`source='gsi_reverse_geocoder'`,`precision='town'`(`:39-58`;测试 `test_intake_geocoding.py:12-19`)。
- 无地址候选 → `ReverseGeocoderError`(`:49-50`)。

### 3.3 muniCd → 行政区映射(含汉字转换,`recognition/municipality.py`)

- 代码表 `data/municipality_codes.json`(实测 1747 条,如 `01100→{北海道,札幌市}`),由 `scripts/build_municipality_codes.py` 从 xlsx 构建(`municipality.py:11,61-65`;`test_municipality_codes.py:10-22`)。
- 都道府县名先查 `_PREFECTURE_QUERY_NAMES`(日→简,如 東京都→东京都),兜底走通用 `_JAPANESE_TO_QUERY` 译表(`municipality.py:41-54,57-58,72-74`);市名走译表。
- 用正则 `(.+市)(.+区)` 拆分政令市→市+区,其余市町村 ward 为空(`:77-80`;`test_municipality_codes.py:25-30`)。
- 未命中代码/字段缺失 → `None`(`:69-76`)。

### 3.4 定位编排与降级(`service.resolve_location`,`service.py:95-121`)

顺序解码 data URL → EXIF GPS → GSI → muniCd 映射:
- EXIF 无 GPS → `{"location":None,"location_reason":"no_exif_gps"}`(`:96-98`);
- 反向地理编码失败(`ReverseGeocoderError`)→ `"geocode_failed"`(`:99-106`);
- muniCd 无法映射 → `"code_not_mapped"`(`:107-109`);
- 成功 → `{prefecture, city, ward(=muniCd 结果或地址推断 `_region_parts`), latitude, longitude, source:"exif"}`,`location_reason=None`(`:110-121`)。

### 3.5 `use_ai` 与 `RECOGNITION_AI_ENABLED`(`service.recognize`,`service.py:168-184`)

- `ai_enabled` = env `RECOGNITION_AI_ENABLED` ∈ {`1,true,yes,on`},默认 false(`:176`)。
- `use_ai=true` 且 AI 未启用 → 直接返回 `{...location, listing:None, ai_disabled:True}`,**不再调用上游**(`:177-178`;测试 `test_recognition_routes.py:30-51`)。
- `listing = analyze(...)` 仅当 `use_ai and not resolve_location_only`(`:179`);即 `resolve_location_only=true` 时永不调用 AI。
- 有 listing 时合并并附 `disclaimer="AI 识别,请核对"`(`:181-183`)。
- `analyze`:POST `JPPSKILL_BASE_URL`(默认 `http://jpsskill:8100`)+`/api/analyze`,超时 `JPPSKILL_TIMEOUT_SECONDS` 默认 30;仅透传 `matched_listing/listing_candidates/confidence`,缺失补默认(`:124-165`)。
- 上游异常映射:`RecognitionUpstreamTimeout`→504、`RecognitionUpstreamError`→502、`RecognitionNotConfigured`→503(`routes.py:49-62`)。
- 入参校验:仅 jpeg/png/webp data URL,解码后 ≤2 MiB(`service.py:19-21,36-49`;`routes.py:15-30`);`note` ≤1000。

---

## 4. API 清单(逐条)

> 全局:所有响应经 `RELEASE_PHASE` 释放范围中间件过滤(`main.py:66-73`;`release_scope.py:73-90`)。`development`/`consumer_active` 阶段全放行;`consumer_intake_preview` 阶段仅白名单(含 intake 六端点 + health + diagnostics)(`release_scope.py:13-24,83-90`)。

### 4.1 `/api/intake`(匿名会话,前缀 `routes/intake.py:48`)

| # | 方法/路径 | 鉴权 | 请求 | 响应 | 错误 |
|---|---|---|---|---|---|
| 1 | POST `/api/intake/sessions` | 无(限流 10/h) | `purpose`∈{self_use,rental_investment},`consent_version`≤100 | 201 `session_id/session_token/expires_at/expires_in_seconds` | 422;429(`Retry-After:3600`);503 |
| 2 | POST `/api/intake/sessions/{id}/inputs` | 会话 token 头 | `input_type`∈{text,url},`source_url`≤2048/`raw_text`≤20000 | 201 `input_id/processing_status` | 404(会话);422;429;503 |
| 3 | POST `/api/intake/sessions/{id}/files` | 会话 token | multipart `file`(pdf/jpg/png ≤20MiB) | 201 `input_id/processing_status` | 400(类型);404;413(超限);429;503 |
| 4 | PUT `/api/intake/sessions/{id}/location` | 会话 token(限流 5/h/会话) | `latitude/longitude/accuracy_m/captured_at/consent_version/source` | `LocationResponse`(`models.py:192-199`) | 404;422;429;503 |
| 5 | PUT `/api/intake/sessions/{id}/fields/{field_name}` | 会话 token | `field_name`(须白名单),`value`,`confirmation_status`,`source_input_id?`,`locator?` | `FieldView`(`models.py:203-210`) | 404(引用越权/会话);422(字段不符/非法名);503 |
| 6 | POST `/api/intake/sessions/{id}/preview` | 会话 token(限流 20/h/会话) | 无体 | `FreePreviewResponse`(`models.py:213-220`) | 404;429 |
| 7 | POST `/api/intake/sessions/{id}/convert` | **Bearer**(`require_user`) | `{project_name?}`≤200 | `{owner_user_id, property_id}` | 404;409(重复地址/重名);422(缺名);503 |
| 8 | GET `/api/intake/projects/{property_id}` | **Bearer**,owner 限定 | — | `properties`+`residential_details` 原始行 | 404 |

- 会话 token 一律走请求头 `X-Analysis-Session`(`routes/intake.py:223,239,286,315,342,357`);错误/过期一律统一 404「分析项目不存在或已过期。」以避免枚举(`routes/intake.py:50,82-99`;测试 `test_intake_routes.py:17-24`)。
- `_require_editable_session` 对已 `converted` 会话一律 404(`routes/intake.py:102-108`)。

### 4.2 深度报告 / 查询(`main.py`)

| # | 方法/路径 | 鉴权 | 说明 | 错误 |
|---|---|---|---|---|
| 9 | POST `/api/query` | **Bearer** | 命中缓存直接返回完成态报告;否则建 `queries`+`generation_jobs`,后台生成,返回 pending(`main.py:333-380`) | 422 |
| 10 | POST `/api/jobs/{query_id}/run` | **Bearer**(owner) | 启动/重试查询对应的生成任务(原子 claim)(`main.py:383-480`) | 404;409(正在处理) |
| 11 | GET `/api/jobs/{job_id}` | **Bearer**(owner) | 任务状态;完成时附 `report`(`main.py:483-520`) | 404 |
| 12 | GET `/api/my/queries` | **Bearer** | 本人查询+任务列表(≤100)(`main.py:523-557`) | — |
| 13 | GET `/api/reports/{query_key}` | **Bearer**(owner) | 未解锁→locked 元数据;解锁→全量报告(`main.py:560-589`) | 404 |
| 14 | GET `/internal/provenance/diagnostics` | 内部 token 头 | 来源状态元数据(`main.py:93-106`) | 404/403 |

### 4.3 `/api/recognition`(需登录,`routes.py:12,34`)

| 方法/路径 | 鉴权 | 请求 | 响应 | 错误 |
|---|---|---|---|---|
| POST `/api/recognition` | **Bearer** | `image`(jpeg/png/webp data URL≤2MiB),`note`≤1000,`resolve_location_only`=false,`use_ai`=false | `{location, location_reason, listing, [ai_disabled], [matched_listing/listing_candidates/confidence/disclaimer]}` | 400 `invalid_image`;503 `recognition_not_configured`;504 `recognition_upstream_timeout`;502 `recognition_upstream_error` |

### 4.4 `/api/renovation`(前缀 `routes/renovation.py:24`)

| 方法/路径 | 鉴权 | 请求 | 响应 | 错误 |
|---|---|---|---|---|
| POST `/api/renovation/estimates` | 无(限流 30/h scope=renovation) | `{context, photos[]}`(结构化观察,photos 1–30,唯一 id)(`routes/renovation.py:37-45`) | `RenovationEstimateResponse`(data_class=`modeled_estimate`)(`models.py:142-156`) | 422;429 |
| POST `/api/renovation/analyses` | 无(限流 10/h) | multipart `manifest`+`images[]`(与 manifest filename 一一对应,jpg/png)(`:47-111`) | 同上(status=vision_provider 或 structured_observations) | 400;413;422;503 `vision_provider_not_configured`/`vision_provider_unavailable` |

---

## 5. 数据流图(文字版):匿名查询 → 免费预览 → 注册 → 报告解锁

```
[匿名] POST /api/intake/sessions ──► analysis_sessions(draft, token_hash, expires_at=+24h)
   │  (仅返回一次明文 token;库中仅摘要 tokens.py:23-25)
   ├─ POST .../inputs (text|url) ──► project_inputs(processing_status='manual_review')
   ├─ POST .../files ──► Storage 私有桶{session}/{uuid}{ext} ──► project_inputs(pending)
   ├─ PUT  .../location ──► GSI 反查 ──► analysis_sessions(lat/lng/address_candidate/...)
   ├─ PUT  .../fields/{name} ──► project_field_evidence(manual/unreviewed)
   │                             └► project_fields(confirmed_value/status)  ← 人工确认
   └─ POST .../preview ──► build_free_preview
            ├ calculate_completeness(fields)          completeness.py:98
            ├ estimate_acquisition_costs(fields)       cost_estimator.py:65
            ├ _risk_summary(dimensions)                completeness.py:127
            └ _comparable_check(address→snapshot)      completeness.py:158
          └─► free_previews(upsert) + analysis_sessions.status='preview_ready', purpose_locked_at
                                          ↑ 【冻结点/免费预览交付】
[注册/登录用户] Authorization: Bearer <Supabase token>  (auth.py:44)
   └─ POST /api/intake/sessions/{id}/convert
        └─► properties(data_class='user_submitted') + residential_details
            └ analysis_sessions.status='converted' (owner_user_id/property_id)
[会员查询] POST /api/query ──► 命中缓存? → 直接返回报告
                              └ 否则 queries+generation_jobs ─► 后台 run_generation_job
                                 ├ match_snapshot(load_snapshots())  market_engine.py:148
                                 ├ 命中: build_sale_report(snapshot)  market_engine.py:216
                                 ├ 未命中: placeholder 报告(诚实空态) jphouse_service.py:85
                                 └ save_report(property_reports) + _consume_c_plus_report_quota
[报告解锁] GET /api/reports/{query_key}
        ├ owner 校验(queries.owner_user_id=user)
        ├ _has_report_unlock: payment_orders(risk_report_single,single报告) 
        │                    OR c_plus_monthly 订阅额度残留 
        │                    OR usage_events consume 指纹
        ├ 未解锁 → {locked:true, slug/title/publish_month/unlock_hint}   ← 内容不外发
        └ 已解锁 → row_to_report(property_reports 全量)
```

**落库表汇总**:`analysis_sessions`、`project_inputs`、`project_field_evidence`、`project_fields`、`free_previews`、`intake_rate_limits`(`repository.py`);`properties`、`residential_details`(`repository.py:434-480`);`queries`、`generation_jobs`、`property_reports`(`main.py`);解锁相关 `payment_orders`/`subscriptions`/`usage_quotas`/`usage_events`(`main.py:116-193`)。

---

## 6. 关键业务规则与常量

| 常量 | 值 | 证据 |
|---|---|---|
| 会话 TTL | 24h(`expires_in_seconds=86400`,DB 约束 ≤+24h5m) | `routes/intake.py:58`;`...property_intake.sql:62-63` |
| 会话状态 | draft/preview_ready/converted/expired | `...property_intake.sql:55-56` |
| 用途 | self_use / rental_investment | `models.py:14` |
| 字段白名单 | 16 字段(building_name…monthly_rent_jpy)+ 单位表 | `models.py:19-37` |
| 确认状态 | confirmed/corrected/unknown(DB 另含 unreviewed/conflict) | `models.py:16`;`...property_intake.sql:112` |
| 可评审置信度 | high/medium | `completeness.py:46` |
| 可比状态 | not_checked/sufficient/insufficient | `...property_intake.sql:131` |
| 上传上限/类型 | 20 MiB;pdf/jpeg/png(魔数校验) | `storage.py:15-20` |
| 识别图上限/类型 | 2 MiB;jpeg/png/webp | `service.py:19-21` |
| 限流(每小时) | session 10 / input 30 / file 10 / preview 20 / location 5(会话维度) | `routes/intake.py:197,227,244,291,346` |
| 限流窗口 | 自然小时(started=整点) | `routes/intake.py:134` |
| 会话 token | token_urlsafe(32),SHA-256 摘要入库 | `tokens.py:23-25` |
| 布局/换算 | 1LDK/2LDK/3LDK;1万日元=10000 | `market_engine.py:75,77` |
| 面积参考带 | 1LDK≈39–45㎡ / 2LDK≈59–65㎡ / 3LDK≈79–85㎡ | `market_engine.py:203-205` |
| 覆盖 | 东京23区/大阪市23区/横滨市18区(≥64 快照) | `market_engine.py:32-36`;`test_market_engine.py:31-38` |
| 汇率快照 | version 2026-09-08-cfets-saf;CNY 0.043098 / USD 0.006357 | `data/input/fx_rates.json:2-14` |
| 取得成本规则 | version 2026-09-08-r1;报酬阶梯 5%/4%+2万/3%+6万 | `data/input/acquisition_cost_rules.json:2,20-23` |
| 印花税带 | 1,000万超5,000万→2万;5,000万超1亿→6万… | `acquisition_cost_rules.json:35-40` |
| 预览计算版本 | `free-preview-v1` | `completeness.py:208` |
| 装修价格快照 | `jp-renovation-2026-08-31-v1` | `renovation/pricing.py:25` |
| 装修范围可计价 | 仅 replace / surface_refresh | `renovation/pricing.py:274` |

---

## 7. 坑 / 注意事项

1. **预览即冻结**:预览会把会话置 `preview_ready` 并写 `purpose_locked_at`(`repository.py:300-309`);转换只接受 `preview_ready`(`repository.py:384`)。已推进到 `converted` 后,所有写端点(`inputs/files/location/fields`)的 SQL 均带 `status<>'converted'` 条件,直接返回 404(`routes/intake.py:102-108`;`repository.py:306,335`)。
2. **付费墙只在一处**:解锁判定 `_has_report_unlock` 仅出现在 `GET /api/reports/{query_key}`(`main.py:576`)。`POST /api/query` 命中缓存时直接返回全量报告(`main.py:352-353`),`GET /api/jobs/{job_id}` 完成时也直接附 `report`(`main.py:499-519`),二者**未见**解锁校验——即付费墙未覆盖这两条读取路径。此为代码事实,是否属预期未确认。
3. **授权源限制(D6a)**:租金侧(SUUMO 来源)未获商用授权,数据层保留但**永不进入报告**:`build_sale_report.rental=[]`(`market_engine.py:217,278`),占位报告 `data_sources=[]`(`jphouse_service.py:94-96`)。当前报告成交口径为「中古マンション成交均价」。
4. **真实 vs synthetic vs modeled**:`data/input/minato_property_synthetic.csv` 为 synthetic 夹具;市场快照 `data_class='scraped_aggregate'`(`market_engine.py:241,290`);转换落库 `properties.data_class='user_submitted'`(`repository.py:444`);装修估算 `data_class='modeled_estimate'`(`renovation/models.py:145`);预览为确定性计算(markdown 将来源标「国交省取引数据整理」)。禁止把 modeled/synthetic 当采集事实——见 `AGENTS.md` 数据真实性规则。
5. **人工确认影响 source_trust**:手工 upsert 的 evidence `confidence='unreviewed'`、`extraction_method='manual'`(`repository.py:241`),而 `source_trust` 只计 high/medium 置信度(`completeness.py:64-65`),因此纯手工录入在 source_trust 维度会偏低——属预期但易被误读为「缺证据」。
6. **地址/行政区归一化是显式有限映射,非通用转换**:`WARD_ALIASES` 仅 17 条全名(`market_engine.py:46-64`),新简体区名若不在表内将匹配失败 → `insufficient`/`not_checked`;`normalize_address` 仅 NFKC+去空白(`repository.py:85-91`),不做同义/繁简对齐。
7. **muniCd 缺失即定位失败**:即使 EXIF GPS 解析成功,GSI 未返回 `muniCd` 或代码不在 1747 条表中,`resolve_location` 也返回 `code_not_mapped` 且 `location=None`(`service.py:107-109`;`municipality.py:69-76`)。
8. **`RecognitionNotConfigured` 基本不可达**:`analyze` 的 `JPPSKILL_BASE_URL` 默认非空(`http://jpsskill:8100`),故仅当环境变量被显式置空时才抛 503(`service.py:125-127`);默认部署会真实发起上游请求。
9. **测试用夹具而非运行时真数据**:`data/collected/` 被 gitignore,CI 用 `tests/fixtures/market_snapshots/`(SHA 相同副本)断言(`test_completeness.py:5-8`;`test_market_engine.py:18-23`)。生产读取回退顺序为 `data/collected` → `backend/data/market_snapshots`(`market_engine.py:123-124`)。
10. **匿名可读写同一 session 行**:预览/字段写入仅凭 token 摘要,无 RLS 层在 FastAPI 路径内可见;`require_user` 仅用于 convert/项目读取/报告(`routes/intake.py:358,394`)。会话过期依赖后台清理任务(`routes/intake.py:150-159`;`repository.py:544-589`),`main.py` 启动时也会跑一次(`main.py:58`)。
11. **汇率/成本必须走配置文件**:`fx.py` 与 `cost_estimator.py` 均从 `data/input/*.json` 读取并带 version/as_of(`fx.py:14,19-28`;`cost_estimator.py:18,23-29`),代码内无硬编码汇率——新增金额展示须沿用 provenance 字段。
12. **未确认项**:`data/collected/jphouse_runs` 的内容与运行时采集管线细节未在本任务范围内核实;`backend/app/collection/`、`billing/`、`admin/`、`usage/`、`services/privacy.py` 仅做了接口级了解,未逐行审阅;前端 `web/` 的预览/报告呈现与后端字段的对应关系未验证。

---

### 交付说明
- 未创建/修改任何文件;全部结论来自只读代码与测试阅读,每条附 `文件:行号`。
- 已核对的关键测试:`tests/unit/test_completeness.py`、`test_cost_estimator.py`、`test_market_engine.py`、`test_recognition_exif.py`、`test_municipality_codes.py`、`test_intake_models.py`、`test_intake_geocoding.py`、`tests/api/test_report_access.py`、`test_intake_routes.py`、`test_recognition_routes.py`。
- 主要不确定点已在第 7 节第 2、12 条以「未确认」标注。


---


# 第 2 部分 · 后端平台域(计费/额度/后台/隐私/鉴权)


All verified. Here is the deliverable.

---

# 后端平台域技术说明(计费 / 额度 / 后台 / 隐私 / 鉴权)

范围: `/Users/gordonmac/GordonDev/JPPropDIs/backend/app` 及其测试。本说明只读代码,未修改任何文件。

---

## 1. 模块职责一览

| 模块 | 文件 | 职责 |
|---|---|---|
| 计费目录 | `backend/app/billing/catalog.py` | 商品/地区/价格目录;DB 驱动 + 代码兜底 + TTL 缓存 |
| 计费编排 | `backend/app/billing/service.py` | 与支付商无关的下单/门户/取消/退款/Webhook 编排与安全规则 |
| Stripe 网关 | `backend/app/billing/gateway.py` | 标准库 urllib 的 Stripe HTTP 客户端,嵌套参数括号编码 |
| 计费契约 | `backend/app/billing/ports.py` | `BillingSubject/BillingStatus/ProviderEvent/AuditRecord/OutboxAction` 等 dataclass 与 Protocol |
| 计费路由 | `backend/app/billing/routes.py` | `/api/billing/*`(默认未配置 → 503) |
| Webhook 验签 | `backend/app/billing/signatures.py` | Stripe 兼容原始报文 HMAC-SHA256 验签 + 事件信封解析 |
| 计费持久化 | `backend/app/billing/store.py` | V1 表(asyncpg)上的 `PostgresBillingStore`,含会员等级/额度联动 |
| 额度账本(离线模型) | `backend/app/usage/ledger.py` | 线程安全内存版计量契约(consume/reserve/commit/release),供确定性测试 |
| 额度账本(DB 适配) | `backend/app/usage/db_ledger.py` | `PostgresLedger`,原子计量 + 幂等 + 并发安全 |
| 额度路由 | `backend/app/usage/routes.py` | `POST /api/usage/events`(默认未配置 → 503) |
| 额度服务 | `backend/app/usage/service.py` | 服务端解析 scope/limit 后调用 `Ledger` |
| 后台鉴权 | `backend/app/admin/auth.py` | 角色模型 `AdminPrincipal` 与 `require_admin_role` 依赖 |
| 后台数据 | `backend/app/admin/service.py` | 会员/审计/财务/采集/角色/定价 的只读查询与两类写 |
| 后台路由 | `backend/app/admin/routes.py` | `/api/admin/*`(默认 `ADMIN_ENABLED` 关 → 503) |
| 账号契约 | `backend/app/account_controls.py` | 离线账号/组织/权限契约(字段白名单、密码策略、recent-auth) |
| 鉴权边界 | `backend/app/auth.py` | Supabase Auth token 校验,产出 `AuthUser` |
| 发布阶段 | `backend/app/release_scope.py` | 发布阶段语义与 API 白名单中间件规则 |
| DB | `backend/app/db.py` | asyncpg 连接池;`get_pool()`;schema 初始化(仅本地) |
| 模型 | `backend/app/models.py` | `QueryRequest/QueryResponse/JobResponse` |
| 隐私契约 | `backend/app/services/privacy.py` | 同意记录、保留期 SLA、隐私元数据(无 DB/Auth 调用) |
| 隐私路由 | `backend/app/routes/privacy.py` | `GET /api/privacy`、`POST /api/account/deletion-request` |
| 健康 | `backend/app/routes/health.py` | `GET /health`、`/health/live`、`/health/ready` |
| 应用装配 | `backend/app/main.py` | lifespan、发布阶段中间件、CORS、路由挂载、报告解锁判定 |

---

## 2. 计费与定价完整逻辑

### 2.1 三个商品与价格目录

商品码与结算模式枚举:`ProductCode = Literal["risk_report_single", "c_plus_monthly", "b_data_pro_monthly"]`,`CheckoutMode = Literal["payment","subscription"]`(`backend/app/billing/catalog.py:15-16`)。

代码内**兜底价格表** `_PRICE_SPECS`(`catalog.py:65-84`),金额为最小货币单位(minor units):

| 商品 | 模式 | 区域→币种价目(CNY/JPY/USD/TWD/HKD/SGD) |
|---|---|---|
| `risk_report_single` | payment | 500 / 100 / 99 / 3000 / 800 / 150 |
| `c_plus_monthly` | subscription | 4900 / 990 / 990 / 30000 / 8000 / 1500 |
| `b_data_pro_monthly` | subscription | 19900 / 3999 / 3990 / 120000 / 32000 / 6000 |

价格版本常量 `PRICE_VERSION = "v1-2026-08"`(`catalog.py:31`)。

代码内兜底**套餐定义** `_fallback_rows()["plans"]`(`catalog.py:119-123`):
- `free`: 月查询 3、月报告 0、订阅位 0、月导出行 0
- `c_plus`: 月查询 100、月报告 12、订阅位 3、月导出行 0
- `b_data_pro`: 月查询 500、月报告 100、订阅位 10、月导出行 10000

`PlanDefinition` 字段:`plan_code, name, monthly_query_limit, monthly_report_quota, subscription_slots, export_rows_monthly`(`catalog.py:55-62`)。

### 2.2 区域→币种映射(CN/JP/MO 等)

`REGION_CURRENCY`(`catalog.py:20-29`):
```
CN→CNY, JP→JPY, US→USD, TW→TWD, HK→HKD, SG→SGD, MO→HKD
```
注释明确:只有已确认本地价的区域可购买,价格是服务端拥有的本地金额,**不施加客户端汇率**(`catalog.py:18-19`);澳门按 HKD 结算,MOP 留待后续价格版本(`catalog.py:27-28`)。

### 2.3 DB 驱动 + 代码兜底 + 60s 缓存 的读取路径

`PriceCatalog.__init__`(`catalog.py:90-101`):
- 入参 `price_ids`(形如 `{"c_plus_monthly:CNY": "price_..."}`,来自 `STRIPE_PRICE_IDS` 环境变量)。
- `cache_ttl` 默认取环境变量 `PRICING_CACHE_TTL_SECONDS`,缺省 **"60" 秒**(`catalog.py:95`)。
- `_load_lock` 惰性构造 asyncio.Lock(`catalog.py:98-101`)。

`ensure_loaded(force=False)`(`catalog.py:126-161`)流程:
1. 未过期(`self._db_rows is not None` 且 `monotonic()-_loaded_at < cache_ttl`)直接返回(`:127-128`)。
2. 取锁后二次检查(双检锁,`:131-133`)。
3. 查询 DB(`:135-144`):
   - `public.pricing_products`(active)
   - `public.pricing_regions`(active)
   - `public.pricing_prices` join `pricing_products`,用 `distinct on (product_code,currency)` 按 `price_version desc, effective_from desc, created_at desc` 取最新一版
   - `public.pricing_plans`(active)
4. 若三张主表任一为空 → `raise LookupError("pricing catalog is empty")`(`:145-146`)。
5. `except Exception` → 记 warning 日志并**回落到代码兜底** `_fallback_rows()`(`:158-160`)。日志只记异常类型名(`type(exc).__name__`),不记内容。

`resolve(product_code, billing_region, currency=None)`(`catalog.py:193-216`):
- `currency` 参数一旦传入即 `PriceUnavailable("currency is selected by billing region")` —— 币种由区域决定,客户端不能切换(`:200-201`)。
- 区域大写后查 `regions`,无 → `PriceUnavailable("no local price for billing region")`(`:203-206`)。
- 命中 `prices[(product, currency)]`:若 `stripe_price_id` 空或 `active=false` → `PriceUnavailable("price is not configured")`(`:209-212`);否则返回 `PriceDefinition`(`:214`)。`mode` 优先取 `products` 表的 checkout_mode,否则退回价格行自带 mode(`:213`)。
- 未命中 → `PriceUnavailable("unknown product")`(`:216`)。

`list_public()`(`catalog.py:171-177`)只输出 `product_code, price_version, currency, amount_minor, mode, available`,**绝不暴露 `stripe_price_id`**;`available=bool(stripe_price_id)`。

### 2.4 下单流程(checkout / portal / cancel / refunds / webhook)

路由前缀 `/api/billing`,tag `billing`(`routes.py:25`)。依赖 `get_billing_service`(`routes.py:43-62`)要求 `STRIPE_SECRET_KEY` 与 `STRIPE_WEBHOOK_SECRET` 同时存在,否则 503(`:44-47`);解析 `STRIPE_PRICE_IDS`(JSON)失败 → 503(`:48-52`)。

**POST /api/billing/checkout**(`routes.py:96-121`):
- 请求体 `CheckoutRequest{product_code, billing_region(2 位字母), query_key?}`;`extra="forbid"` 使 `price_id/amount_minor/currency/success_url` 等客户端字段直接 422(`routes.py:29-34`;测试 `tests/billing/test_routes.py:94-110`)。
- 鉴权 `require_user`。`service.create_checkout(...)` 传入 `report_key=query_key`。
- 返回 `session_id/url/product_code/price_version/currency/amount_minor/mode`。

`BillingService.create_checkout`(`service.py:184-262`):
1. `catalog.ensure_loaded()`(`:194`)、`resolve`(`:195`)。
2. **payment 模式必须有 report_key**,否则 `BillingConflict`(409)(`:196-197`)。
3. `store.get_subject(user_id, product_code)`,失败 → `BillingNotFound`(404)(`:198-201`)。
4. `checkout_subject_id` = payment 模式取 `report_key`,sub 模式取 `subject.subject_id`(`:203`)。
5. metadata 固定写入 `user_id, subject_id, product_code, price_version, billing_region`(`:204-210`)——全部服务端生成。
6. Stripe 参数:`mode/line_items[{price,quantity:1}]/success_url/cancel_url/allow_promotion_codes:true/client_reference_id/metadata`(`:211-219`);订阅模式额外 `subscription_data.metadata`(`:220-221`)。
7. 有 `stripe_customer_id` → `customer`;否则用登录邮箱 `customer_email`,邮箱空 → 409(`:222-228`)。
8. 网关异常统一转 `TransientBillingError`(500)(`:230-235`),再写审计 `billing.checkout.created`(`:236-253`)。

**POST /api/billing/portal**(`routes.py:124-133`;`service.py:264-289`):取个人 `get_portal_subject`,无 customer → 409,否则创建门户会话并审计 `billing.portal.created`。

**GET /api/billing/status**(`routes.py:136-144`;`service.py:291-295`):返回 `_status_payload`(`routes.py:75-86`),含 `entitlement_active`。

**POST /api/billing/cancel**(`routes.py:147-160`;`service.py:297-325`):始终 `at_period_end=True`;已请求过则 `already_requested=True` 幂等返回(`:304-305`);否则调网关取消 + `store.record_cancel` + 审计 `billing.subscription.cancel_requested`。

**POST /api/billing/refunds**(`routes.py:163-181`;`service.py:327-355`):请求体 `payment_intent_id`。资格判定(`:334-341`):`status=="eligible"` 且 `0 <= age <= 48h` 且 `not used_entitlement`,否则 `RefundNotEligible`(409)。退款审批 `approve_refund`(`:357-402`)要求 actor 角色含 `finance`(`:365-366`),否则 403;临时失败按 `RetryPolicy` 记重试。

**POST /api/billing/webhook**(`routes.py:184-204`):读取 `await request.body()` 原始字节 + `Stripe-Signature` 头,交给 `service.handle_webhook`。

### 2.5 Webhook 验签与事件处理

**验签** `construct_event(payload, signature_header, secret, *, now, tolerance_seconds=300)`(`signatures.py:48-93`):
- `_parse_header` 解析 `t=` 与一个或多个 `v1=`(`:23-45`);时间戳重复/缺失/非法 → 无效。
- 计算 `HMAC-SHA256(secret, "{t}.{payload}")`,任一候选用 `hmac.compare_digest` 命中即通过(`:64-67`)。
- 时间戳容差 ±300 秒(`:54,69-71`)。
- JSON 解析必须是 dict,且 `id`、`type` 为非空字符串、`data` 为 dict(`:73-85`);返回 `ProviderEvent{event_id,event_type,payload,received_at}`。
- 所有失败统一 `SignatureVerificationError("invalid webhook signature or payload")`,不泄露细节(`signatures.py:18-20`)。

**处理** `BillingService.handle_webhook`(`service.py:404-460`):
- 支持事件集 `_SUPPORTED_EVENTS`(`service.py:113-122`):`checkout.session.completed`、`customer.subscription.created/updated/deleted`、`invoice.paid`、`invoice.payment_failed`、`refund.created/updated`。
- `claim_provider_event` 返回 `in_progress` → 抛 `TransientBillingError`(让 Stripe 重投)(`:420-423`);`processed/dead_letter` → 幂等返回 `duplicate`(`:424-425`)。
- 副作用 `_event_side_effects`(`:462-513`):从 `data.object` 取 `id`;不支持类型 → 审计 `billing.event.ignored` 且 `ignored=True`(`:470-484`);`invoice.payment_failed` 生成 `OutboxAction(kind="billing.dunning")`(`:507-512`)。
- 失败:permanent → `mark_provider_event_failed(permanent, "invalid_event", None)`;transient/未知 → 依 `RetryPolicy.next_retry_at`(`:73-79`,指数退避 5→…→300s,最多 3 次)记 transient。

**审计脱敏**:`_sanitize_value`/`sanitize_reason`(`service.py:142-157`)按 `_SENSITIVE_KEYS`(`:124-133`)替换为 `[redacted]`,并对字符串内的邮箱做 `[redacted-email]` 替换,reason 截断 500 字符。

### 2.6 DB 侧 Webhook 副作用与订阅生命周期

`PostgresBillingStore`(`store.py`)一个事务/操作(`store.py:1-11`);`claim/process/mark_failed` 用**分离事务**(claim 先持久化,失败标记需在回滚后仍可写)(`store.py:6-11`)。

事件台账 `payment_events`:
- `claim_provider_event`(`store.py:407-477`):插入 `provider_event_id` 唯一行,冲突时按现有 status 分支——`processed/ignored→processed`、`received→in_progress`、`failed` 且末次 permanent → `dead_letter`、transient → 重claim 为 `received` 并返回 `retry`(`:462-477`)。`attempt_count` = 已记录的 `billing.event.failed` 审计行数 + 1(`:455-461`)。
- 只存**规范化 JSON 的 sha256**(`_payload_sha256` `store.py:214-221`),不存明文。
- `payment_events` 无 attempt/next_attempt_at 列,failure_class/error_code/next_attempt_at 记进 `audit_events`(`store.py:48-56,1138-1189`)。

副作用分发 `_apply_event_side_effects`(`store.py:544-568`):
- `checkout.session.completed` → `_on_checkout_completed`(`store.py:776-883`):upsert `billing_customers`;订阅模式 upsert `subscriptions` 镜像(状态 `paid→active` 否则 `incomplete`);payment 模式 upsert `payment_orders`,订单号 `ord_{session_id}`,写入 `subject_id = metadata.subject_id`(`:876`),`status='paid'|'pending'`,`paid_at`。
- `customer.subscription.created/updated/deleted` → `_on_subscription_mirror_event`(`store.py:885-929`):按 `stripe_subscription_id` upsert 镜像;`deleted` 强制 `canceled`;`paused` 状态无 V1 表示 → 抛错 dead-letter(`:896-898`,常量 `_STATUS_CANNOT_PROCESS` `:158`)。产品/价格/币种/金额列**仅插入时写入,后续事件不改写**(`store.py:36-40,725-730`)。
- `invoice.paid` → `_on_invoice_paid`(`store.py:931-1009`):订阅设 `active` 并联动权益;无订阅的一次性发票按 `payment_intent` 匹配订单补 `paid`(`:936-955`);有订阅则按 `ord_{intent}` upsert 收款订单(`:987-1008`)。
- `invoice.payment_failed` → `_on_invoice_payment_failed`(`store.py:1011-1039`):订阅置 `past_due` 并联动权益。
- `refund.created/updated` → `_on_refund_event`(`store.py:1041-1123`):按 `provider_refund_id` 同步 `refunds`(可凭空建行),成功则重算父订单 `refunded/partially_refunded`(`store.py:1125-1136`),整单退款且为订阅商品则取消订阅并撤销权益(`:1103-1122`)。

**会员等级 / 额度更新** `_sync_membership_entitlement`(`store.py:99-150`):
- 仅订阅商品生效(`:109-110`)。
- `active = status in {active,trialing} and (period_end is None or period_end > now)`(`:111-113`)。
- `tier = product_code.removesuffix("_monthly") if active else "free"`(`:114`)。
- `daily_limit = {c_plus:100, b_data_pro:500}.get(tier, 3)`(`:115`)。
- 更新 `public.user_profiles.membership_tier, daily_query_limit`;组织范围走 `organization_members` 关联更新(`:116-131`)。
- 预置当月(UTC+8)额度行 `public.usage_quotas`(`:132-150`):`c_plus` → `[("report",12)]`;`b_data_pro` → `[("query",500),("stats_query",100),("export_row",10000),("subscription_slot",10)]`;`on conflict ... limit_units = case when $active then excluded else consumed+reserved end`(降级时把上限压到已用量)。

价格版本整数化:`checkout.metadata.price_version` 是目录标签(如 `"v1-2026-08"`),冻结表存整数;`_coerce_price_version`(`store.py:233-247`)以 `_KNOWN_PRICE_VERSION_LABELS`(`:163`)映射,未知回退 1。币种统一大写(`_currency` `store.py:250-253`)。订阅状态白名单 `_ALLOWED_SUBSCRIPTION_STATUSES`(`store.py:153-155`)。

---

## 3. 按份报告解锁

### 3.1 订单 `subject_id` 语义(报告标识)

`payment_orders.subject_id text` 由迁移 `supabase/migrations/20260911000100_report_purchase_subject.sql:3-4` 新增,并建索引 `(owner_user_id, product_code, subject_id, status)`(`:6-7`)。语义:一次性支付订单用它承载**报告标识(query_key)**;下单时 `checkout_subject_id = report_key`(`service.py:203`),并写入 `metadata.subject_id` 与 `client_reference_id`(`service.py:206,217`),Webhook 落订单时写入 `subject_id`(`store.py:876`)。旧订单 `subject_id` 为 NULL,因此不解锁任何报告(迁移注释 `:2`)。

### 3.2 `_has_report_unlock` 判定

`main.py:116-148`,对 `(user_id, report_key, 当月 UTC+8)` 做三段 UNION,任一命中即解锁:
1. `payment_orders`:`owner_user_id=user_id and product_code='risk_report_single' and subject_id=report_key and status='paid'`(`main.py:121-123`)——按份支付。
2. `subscriptions s` join `usage_quotas uq`(`scope_key='user:'||user_id`、`usage_kind='report'`、`period_key=当月`):`s.product_code='c_plus_monthly'`、状态 `active/trialing`、`current_period_end > now()`、且 `consumed+reserved < limit`(`main.py:126-134`)——C Plus 订阅额度。
3. `usage_events`:存在 `usage_kind='report' and operation='consume' and fingerprint='c-plus-report:'||report_key`(`main.py:137-141`)——**该报告一旦在订阅期内生成过,即使后来额度耗尽或订阅终止也保持解锁**。

当月键 `_current_month_key()` = UTC+8 的 `%Y-%m`(`main.py:112-113`)。

### 3.3 C Plus 订阅额度消费路径

`_consume_c_plus_report_quota(user_id, report_key)`(`main.py:151-193`),在报告生成后台任务中于 `save_report` 之后调用(`main.py:315-316`):
1. 校验存在可用 `c_plus_monthly` 订阅(否则返回 False)(`:157-166`)。
2. 预置 `usage_quotas` 行 `('report', period_key, limit=12)`(`:167-173`)。
3. 以 `fingerprint='c-plus-report:'||report_key` 插入 `usage_events`,`on conflict (scope_key,usage_kind,operation,fingerprint) do nothing`(`:174-182`);已存在 → 返回 True(幂等)。
4. 条件自增 `consumed_units+1 WHERE consumed+reserved < limit`(`:185-190`);更新行数≠1 → `raise RuntimeError("subscription report quota exhausted")`(`:191-192`)。

### 3.4 读取端与额度用尽回落

`GET /api/reports/{query_key}`(`main.py:560-589`):查 `property_reports` 且必须 `q.owner_user_id=user_id`(非本人 → 404,`:574-575`);未解锁返回 `locked:true` 的**仅元数据**响应(`query_key/slug/title/publish_month/unlock_hint`),**内容字段不返回**(`:577-588`);解锁返回完整 `row_to_report`(`:196-217`)。

回落规则:额度用尽或订阅失效时,判定 2 不再命中;若该报告从未在订阅期内消费过(判定 3 也不命中),则回落为需按份购买 `risk_report_single`(测试 `tests/api/test_report_access.py:140-147`;解锁/锁定/跨报告解锁边界见 `:91-137`)。

> 注:写路径消费额度耗尽的 `RuntimeError`(`main.py:191-192`)会落入生成任务的 `except Exception`(`main.py:323-330`)并把该 job 标记为 `failed`,尽管报告已 `save_report` 成功。这是代码事实,未在本任务中修改。

---

## 4. 额度账本

### 4.1 表结构(迁移 `supabase/migrations/20260905000300_v1_usage_ledger.sql`)

`public.usage_quotas`(`:38-71`):`id, scope_key, usage_kind, period_key, limit_units, consumed_units, reserved_units, reset_at, updated_at`;唯一约束 `(scope_key, usage_kind, period_key)`(`:63`);`scope_key`/`period_key` 有正则 CHECK(`:50-56`);`usage_kind ∈ {query,report,stats_query,export_row,subscription_slot}`(`:57-59`);容量界宽松 CHECK `consumed+reserved <= limit+100000`(`:68-70`)。

`public.usage_events`(`:84-124`):`id, scope_key, usage_kind, operation, units, period_key, idempotency_key, fingerprint, reservation_key, reversal_of, actor_user_id, note, created_at`;`operation ∈ {consume,reserve,commit,release,reversal}`(`:113-115`);**append-only 触发器禁止 UPDATE/DELETE**(`:136-153`);唯一索引 `(scope_key,usage_kind,operation,fingerprint)`(`:128-130`)。

`public.usage_idempotency`(`:159-182`):`id, scope_key, usage_kind, operation, idempotency_key, fingerprint, processed_at`;两条唯一约束 `fingerprint_unique` 与 `client_key_unique`(`:176-181`)。

RLS:三表 `enable row level security`,撤销 `anon/authenticated` 全部权限;`authenticated` 可 `select` 自己的 `usage_quotas/usage_events`(按 `scope_key` 前缀匹配 `auth.uid()` 或组织成员)(`:187-225`);`service_role` 全权;`usage_idempotency` 无 policy(纯服务端)(`:227-228`)。

### 4.2 计量口径

- 种类词汇:离线枚举 `UsageKind = {query, analysis, subscription, export, report}`(`ledger.py:24-29`);DB CHECK 词表 `{query, report, stats_query, export_row, subscription_slot}`(`db_ledger.py:144-146`);`_normalise_kind` 只接受 DB 词表(`db_ledger.py:164-174`)。
- 单位 `units`:每事件一段整数(查询次数、报告份数、导出行数、订阅位等由 `usage_kind` 语义决定;`usage_events.units > 0` CHECK `:116`)。导出行口径以 `export_row` 的 `units` 为行数,上限 10000 由 `_sync_membership_entitlement` 预置(`store.py:138`)。
- 周期:UTC+8 日桶 `YYYY-MM-DD` / 月桶 `YYYY-MM`(`ledger.py:130-148`;`db_ledger.py:185-191`),桶末**排他**。
- 离线模型容量检查 `consumed+reserved+units > limit → QuotaExceeded`(`ledger.py:231-234`)。

### 4.3 幂等与并发安全

DB 适配 `PostgresLedger`(`db_ledger.py`):
- 两层串行化(`db_ledger.py:33-41`):
  - 事务级 advisory lock `pg_advisory_xact_lock(hash(scope,kind,operation,idempotency_key))`(`db_ledger.py:291-301`,调用点 `:621,761`);
  - 对计费行 `SELECT ... FOR UPDATE`(`_lock_quota_or_provision` `:334-377`)。
- 容量硬约束来自**条件 UPDATE + RETURNING**:`... set {consumed|reserved}_units = ...+$1 where ... and consumed_units+reserved_units+$1 <= limit_units returning ...`,无返回行 → `QuotaExceeded`(`:641-653`)。
- 提交/释放:`reserved_units -= $1 ... and reserved_units >= $1`(`:838-866`);提交时把用量的 `period_key` 固定为**原 reserve 的周期**(`:809-810,874`),跨日期桶也正确归集。
- 幂等语义(`:70-98`):同 key 同指纹 → `duplicate`;同 key 异指纹 → `IdempotencyConflict`;同指纹异 key → `duplicate`。
- 指纹 = `(scope.kind, scope.id, kind, units, actor_user_id, operation, limit, reservation_key, period_key)` 的确定性 JSON(`db_ledger.py:208-230`),前 8 项与离线模型一致,末项追加周期以支持跨周期重置。
- 首个 `usage_quotas` 未预置且未传 `limit` → `QuotaExceeded`(零容量)(`:353-355`)。

离线模型 `Ledger` 用 `RLock` 串行化(`ledger.py:155,248`),reserve→commit/release 状态机与幂等见 `ledger.py:260-352`。

### 4.4 路由与服务(默认关闭)

`POST /api/usage/events`(`routes.py:92-115`):头 `Idempotency-Key` 必填 1–128(`:95`);体 `UsageRequest{kind, units>0, operation(默认 consume), period(默认 day), reservation_key?}`(`:30-49`),`extra="forbid"`;服务端派生 scope/limit/actor,客户端字段(如 `owner_user_id/limit_units`)→ 422(测试 `tests/api/test_usage_routes.py:70-84`)。错误映射:`QuotaExceeded→429 quota_exceeded`、`IdempotencyConflict→409`、`ReservationNotFound→409`、`ReservationStateError→409`、`ValueError→422`、其它→`503 usage_unavailable`(`routes.py:104-115`)。

`get_usage_service` **始终抛 503**(`routes.py:66-69`)——生产未接线 `PostgresLedger`。`UsageService.apply` 通过注入的 `scope_resolver/limit_resolver/clock` 调用账本(`service.py:38-55`)。

> 未确认:仓库内除 `report` 外没有路径真正消费 `query/stats_query/export_row/subscription_slot` 额度;`daily_query_limit` 仅在联动与后台展示中被写,未见查询侧强制读取(全仓库搜索 `daily_query_limit` 仅出现在 `account_controls.py`、`store.py`、`sql/`)。

---

## 5. 后台 admin

### 5.1 鉴权模型

角色词汇(冻结于 DB CHECK):`member_ops, data_ops, task_dispatcher, reviewer, finance, super_admin`(`admin/auth.py:16-19,31-40`)。角色存 `public.internal_role_assignments`,`expires_at` 为空或未来才有效(`admin/auth.py:1-6,383-392`)。

- `AdminPrincipal` = 认证用户 + 活跃角色集,提供 `role_set/has_role`(`admin/auth.py:43-57`)。
- `require_admin_role(*roles)`(`admin/auth.py:83-104`):先 `require_user`(401),再 `get_admin_service`(503),最后角色检查;**无任何角色 → 403「当前账号没有后台访问权限」,角色不匹配 → 403「无权访问该后台资源」**(`:76-80`)。空角色集或未知角色在构造依赖时即 `ValueError`。
- `require_admin_viewer()`(`admin/auth.py:107-122`):仅认证 + env 门,**不做角色 403**,用于 `GET /api/admin/internal/me` 返回调用者自身的角色集。
- 权限按角色逐动作,无隐式全能(`admin/auth.py:18-19`)。

`get_admin_service`(`admin/service.py:1157-1171`):环境门 `ADMIN_ENABLED`(默认 `false`),不在 `{1,true,yes,on}` → 503「admin 未配置」;池不可用 → 同 503。

邮箱可见性:`EMAIL_VISIBLE_ROLES = {member_ops, finance, super_admin}`(`admin/service.py:56`);`mask_email` 输出 `l***@domain`(`:128-136`);序列化按 `email_visible` 决定(`:167-186`)。`member_ops` 审计范围由 `MEMBER_OPS_ACTION_PREFIXES` 前缀限定(`:63-71`),`super_admin` 看全量。模块不做日志(`:26-30`)。

### 5.2 定价后台化 API

| 方法 | 路径 | 角色 | 说明 |
|---|---|---|---|
| GET | `/api/admin/pricing` | finance, super_admin | 返回 `products/prices/regions/plans`(`routes.py:286-291`) |
| POST | `/api/admin/pricing/prices` | finance, super_admin | 新增价格版本,201(`routes.py:294-306`) |
| POST | `/api/admin/pricing/regions` | finance, super_admin | upsert 区域,201(`routes.py:309-318`) |
| POST | `/api/admin/pricing/prices/{price_id}/status` | finance, super_admin | 启停某价格版本(`routes.py:321-335`,不存在→404,id 非法→400) |
| POST | `/api/admin/pricing/plans` | finance, super_admin | upsert 套餐,201(`routes.py:338-351`) |

服务实现:
- `get_pricing`(`admin/service.py:1092-1106`)四表 SELECT;`_pricing_row` 把 UUID/datetime 序列化(`:1108-1116`)。
- `add_pricing_price`(`:1118-1128`):`for update` 锁产品行,`price_version = max(price_version)+1`(按 product+currency),插入后写审计 `admin.pricing.price_created`。
- `set_pricing_price_active`(`:1130-1137`):更新 active,审计 `admin.pricing.price_status_changed`。
- `upsert_pricing_region`(`:1139-1144`):`on conflict (region_code) do update`,审计 `admin.pricing.region_upserted`。
- `upsert_pricing_plan`(`:1146-1154`):`on conflict (plan_code) do update ... plan_version = pricing_plans.plan_version + 1`,审计 `admin.pricing.plan_upserted`。

### 5.3 版本化与审计字段

定价三表(`supabase/migrations/20260912000100_pricing_admin.sql`):
- `pricing_products(product_code PK, name, checkout_mode, active, created_at)`(`:4-10`)。
- `pricing_prices(id, product_code FK, currency CHECK(7 币种含 MOP), amount_minor>0, stripe_price_id, price_version>0, active, effective_from, created_by, created_at, note)`(`:12-24`),注释「append-only 本地价格版本;订单保留所选 price_version」(`:61-62`)。
- `pricing_regions(region_code PK, currency, active, created_by, created_at)`(`:29-35`)。
- `pricing_plans(plan_code PK, name, 四额度列>=0, plan_version>0 默认 1, active, created_by, created_at)`(`:37-48`);注释「服务端拥有权益默认值;每次后台变更 plan_version +1」(`:63-64`)。
- RLS:四表 enable RLS,`revoke all from anon, authenticated`,`grant all to service_role`(`:50-59`)。

审计行统一含 `actor_user_id, action, target_type, target_id, summary(jsonb), occurred_at`;写操作与审计在同一事务内提交(如 `admin/service.py:1120-1127`)。

---

## 6. 账号控制与隐私

### 6.1 account_controls 的作用

离线账号/组织/授权契约,**不触库、不触身份提供方**(`account_controls.py:1-5`),定义未来账号路由必须执行的边界:
- 字段白名单:可编辑 `PROFILE_EDITABLE_FIELDS = {display_name,city,favorite_area,favorite_asset_type,bio}`(`:14-22`);服务端管理字段 `PROFILE_MANAGED_FIELDS = {user_id,email,username,membership_tier,daily_query_limit,organization_id,organization_role,internal_roles,partner_status}`(`:23-35`);字段长度上限 `PROFILE_FIELD_LIMITS`(`:36-42`)。
- `validate_profile_patch`(`:76-104`):拒绝托管字段、未知字段、非文本、控制字符、超长。
- 密码策略 `PASSWORD_MIN_LENGTH=12 / MAX=128`(`:44-45`),`validate_password`(`:107-116`)。
- `public_auth_failure` 统一登录失败响应,防账号枚举(`:119-125`)。
- `RECENT_AUTH_WINDOW = 15 分钟`(`:46`),`require_recent_auth`(`:128-145`)。
- 组织:`MAX_ACTIVE_ORGANIZATION_MEMBERS = 5`(`:47`),`can_invite_member/can_manage_billing/can_view_contact`(`:148-159`)。
- 内部权限映射 `INTERNAL_ROLE_PERMISSIONS`(`:49-60`)与 `has_internal_permission/can_grant_internal_role`(`:162-167`)。

> 注:`INTERNAL_ROLE_PERMISSIONS` 的词表(`task_dispatch, database_ops, backup_operator, security_reviewer, release_owner` 等)与 `admin/auth.py` 的 DB CHECK 词表(`task_dispatcher` 而非 `task_dispatch` 等)**不一致**;该模块是离线契约,未接任何路由(全仓库无引用其函数的路由)。

### 6.2 隐私端点

`GET /api/privacy`(`routes/privacy.py:58-60`,公开):返回 `privacy_metadata()`(`services/privacy.py:86-121`)——版本 `privacy-2026-08` / `terms-2026-08`(`:16-17`)、同意要求、retention SLA(24h/24h/30d/90d,`:19-22,104-109`)、账户删除状态 `unavailable_without_trusted_executor` 且 `no_side_effect_on_unavailable=true`(`:110-114`)、支持信息占位、`migration_baseline_status=reconciliation_required`。

`POST /api/account/deletion-request`(`routes/privacy.py:63-93`,需登录,202):
- 体 `AccountDeletionRequest{privacy_policy_version, terms_version, confirmation=="DELETE_ACCOUNT"}`(`:23-30`);`extra="ignore"` 使客户端身份字段被忽略而非回显(`:24-26`)。
- 版本不匹配 → 409(`:69-73`,测试 `tests/api/test_privacy_routes.py:59-72`)。
- 执行器 `UnavailableDeletionExecutor` 恒抛 `DeletionServiceUnavailable` → 503「account deletion service is not configured; no account data was changed」(`routes/privacy.py:33-35,77-81`);其它异常同样 503 且不含内部细节(`:82-87`)。
- 回执只保留 `_PUBLIC_DELETION_RECEIPT_FIELDS`(`:39-49`),**不含 email**(测试 `:93-128`)。

`build_consent_record/ConsentRecord.as_auth_metadata`(`services/privacy.py:35-70`)产出 `consent_version/consent_at/terms_version/consent_source`;`build_deletion_plan` 计算各 SLA 到期时间(`:73-83`)。

> 关于「DATA-SUBJECT REQUEST」:代码中**未找到**该命名的端点或函数;现有载体是 `POST /api/account/deletion-request` 与 `privacy_metadata` 的治理描述。未确认是否存在前端侧对应文案。

### 6.3 release_scope 阶段语义

阶段常量:`PHASE_ONE="consumer_intake_preview"`(`:7`)、`CONSUMER_ACTIVE="consumer_active"`(`:10`,注释:staging 验收阶段,业务 API 全可达,安全由服务层鉴权/`ADMIN_ENABLED`/RLS 承担,**禁止用于生产**)、`MANAGED_ENVIRONMENTS={"staging","production"}`(`:11`)。

`current_release_phase()`(`:65-70`):优先 `RELEASE_PHASE` 环境变量;否则 `ENVIRONMENT ∈ {staging,production}` → `"unconfigured_managed"`,否则 `"development"`。

`request_allowed(method, path)`(`:73-90`)放行规则:
1. `OPTIONS` 恒放行(`:76-77`)。
2. `_ALWAYS_ALLOWED` = `PHASE_ONE_API_CONTRACT[:4]`(`:49`),即 `GET /health`、`GET /health/live`、`GET /health/ready`、`GET /internal/provenance/diagnostics`,恒放行(`:78-82`)。
3. `phase in ("development", CONSUMER_ACTIVE)` → **全放行**(`:83-84`)。
4. `phase != PHASE_ONE`(即 `unconfigured_managed` 或他值)→ **全拒**(`:85-86`)。
5. `phase == PHASE_ONE` → 仅放行契约内规则(`:87-90`)。

`PHASE_ONE_API_CONTRACT`(`:13-24`)含 10 条:三个健康检查、`/internal/provenance/diagnostics`、6 个 intake 端点;再追加 `ADMIN_API_CONTRACT`(`:33-46`)的 12 条后台端点(`:48`)。

> 提示(代码事实):`ADMIN_API_CONTRACT` 未包含 `/api/admin/pricing*`、`/collection/sources`、`/overview`、`/service/tasks`;`/api/billing/*`、`/api/usage/*`、`/api/query`、`/api/reports/*` 也未在契约内。因此在 `RELEASE_PHASE=consumer_intake_preview` 下这些路径会被中间件返回 **404**「operation unavailable in current release phase」(中间件 `main.py:66-73`;usage 未入白名单的测试 `tests/api/test_usage_routes.py:115-126`)。

---

## 7. API 清单

鉴权图例:`公开`=无鉴权;`用户`=Supabase Bearer(`require_user`);`角色`=上述角色之一;`env`=依赖环境门(`ADMIN_ENABLED`/Stripe 配置)。

**健康 / 隐私**

| 方法 | 路径 | 鉴权 | 请求 | 响应 / 错误 |
|---|---|---|---|---|
| GET | `/health` | 公开 | — | `{status:"ok"}`(`health.py:18-21`) |
| GET | `/health/live` | 公开 | — | `{status:"ok"}`(`health.py:13-15`) |
| GET | `/health/ready` | 公开 | — | `{status, database, version}`;DB 不可用 503(`health.py:24-35`) |
| GET | `/api/privacy` | 公开 | — | `privacy_metadata()`(`privacy.py:58-60`) |
| POST | `/api/account/deletion-request` | 用户 | `{privacy_policy_version,terms_version,confirmation}` | 202 回执;409 版本不符;503 执行器未配置(`privacy.py:63-93`) |

**计费 `/api/billing`**(`env`:无 Stripe 配置 → 503)

| 方法 | 路径 | 鉴权 | 请求 | 响应 / 错误 |
|---|---|---|---|---|
| GET | `/api/billing/prices` | 公开 | — | 价格数组,无 `stripe_price_id`(`routes.py:89-93`) |
| POST | `/api/billing/checkout` | 用户 | `{product_code,billing_region,query_key?}` | 200 会话;409 价格不可用/需 report_key;404 无 subject;422 客户端字段;503(`routes.py:96-121`) |
| POST | `/api/billing/portal` | 用户 | — | 200 `{url}`;409 无 customer;404;503(`routes.py:124-133`) |
| GET | `/api/billing/status` | 用户 | — | 200 状态;404;503(`routes.py:136-144`) |
| POST | `/api/billing/cancel` | 用户 | — | 200 `{subscription_id,at_period_end,already_requested}`;404;503(`routes.py:147-160`) |
| POST | `/api/billing/refunds` | 用户 | `{payment_intent_id}` | 200;409 不合格;404;503(`routes.py:163-181`) |
| POST | `/api/billing/webhook` | 公开(验签) | 原始体 + `Stripe-Signature` | 200 `{status,event_id,duplicate,ignored}`;400 验签失败;500 暂时不可用(`routes.py:184-204`) |

`_http_error` 映射(`routes.py:65-72`):`SignatureVerificationError→400`、`PriceUnavailable→409`、其它 `BillingError→其 status_code`、兜底 `500`。

**额度 `/api/usage`**

| 方法 | 路径 | 鉴权 | 请求 | 响应 / 错误 |
|---|---|---|---|---|
| POST | `/api/usage/events` | 用户(默认 503) | 头 `Idempotency-Key`;体 `{kind,units>0,operation,period,reservation_key?}` | 200 `UsageResponse`;429 quota_exceeded;409 conflict/reservation;422;503(`routes.py:92-115`) |

**后台 `/api/admin`**(`env`:未启用 → 503)

| 方法 | 路径 | 角色 |
|---|---|---|
| GET | `/api/admin/members` | member_ops, super_admin(`routes.py:271-283`) |
| GET | `/api/admin/members/{user_id}` | member_ops, super_admin(`:354-366`) |
| POST | `/api/admin/members/{user_id}/status` | member_ops, super_admin(`:619-647`) |
| GET | `/api/admin/audit` | member_ops(限域)/ super_admin(全量)(`:369-386`) |
| GET | `/api/admin/finance/orders` | finance, super_admin(`:389-398`) |
| GET | `/api/admin/finance/refunds` | finance, super_admin(`:401-410`) |
| GET | `/api/admin/collection/runs` | member_ops, data_ops, super_admin(`:413-436`) |
| POST | `/api/admin/collection/runs` | data_ops, super_admin(`:501-520`) |
| GET | `/api/admin/collection/sources` | member_ops, data_ops, super_admin(`:439-455`) |
| POST | `/api/admin/collection/sources` | data_ops, super_admin(`:458-486`) |
| GET | `/api/admin/overview` | member_ops, data_ops, super_admin(`:489-498`) |
| GET | `/api/admin/service/tasks` | member_ops, super_admin(`:523-538`) |
| GET | `/api/admin/pricing` | finance, super_admin(`:286-291`) |
| POST | `/api/admin/pricing/prices` | finance, super_admin(`:294-306`) |
| POST | `/api/admin/pricing/regions` | finance, super_admin(`:309-318`) |
| POST | `/api/admin/pricing/prices/{price_id}/status` | finance, super_admin(`:321-335`) |
| POST | `/api/admin/pricing/plans` | finance, super_admin(`:338-351`) |
| GET | `/api/admin/internal/me` | 任意已认证(仅自身角色)(`:550-560`) |
| GET | `/api/admin/internal/roles` | super_admin(`:541-547`) |
| POST | `/api/admin/internal/roles` | super_admin(`:563-588`) |
| DELETE | `/api/admin/internal/roles/{user_id}/{role}` | super_admin(`:591-616`) |

后台错误码:400(角色/状态/user_id/过期时间非法、目标用户不存在)、403(无角色/角色不足)、404(会员/角色分配/价格版本不存在)、409(角色已持有)、422(`_parse_user_id` 形状非法)、503(env 未启用)。路由矩阵另见源码注释 `admin/routes.py:14-51`。

**报告相关(平台域)** `main.py`

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/api/reports/{query_key}` | 用户 | 解锁判定 + 锁定/完整响应(`main.py:560-589`) |
| GET | `/api/my/queries` | 用户 | 仅本人查询任务(`:523-557`) |
| POST | `/api/query` | 用户 | 生成请求(`:333+`) |
| POST | `/api/jobs/{query_id}/run` | 用户 | 触发后台生成(`:383`) |
| GET | `/api/jobs/{job_id}` | 用户 | 作业状态(`:483`) |
| GET | `/internal/provenance/diagnostics` | 头 token | env 未配置 → 404;token 不符 → 403(`:93-106`) |

---

## 8. 关键业务规则、常量、坑

**常量**
- `PRICE_VERSION="v1-2026-08"`(`catalog.py:31`);缓存 `PRICING_CACHE_TTL_SECONDS` 默认 `60`(`catalog.py:95`)。
- 区域币种 `CN/JP/US/TW/HK/SG→本币,MO→HKD`(`catalog.py:20-29`)。
- Webhook 容差 300s(`signatures.py:54`);重试策略 3 次、基数 5s、上限 300s(`service.py:68-71`)。
- 退款窗口 48h(`service.py:338`);`RECENT_AUTH_WINDOW=15min`、密码 12–128、组织上限 5(`account_controls.py:44-47`)。
- 隐私 SLA 24h/24h/30d/90d,版本 `privacy-2026-08`/`terms-2026-08`(`services/privacy.py:16-22`)。
- 分页默认 20 / 上限 100;审计默认 100 / 上限 500(`admin/service.py:47-50`)。
- 会员状态仅 `active|suspended`(`admin/service.py:75`);订单状态 6 种、退款状态 3 种(`:77-85`)。

**业务规则**
1. 币种与金额一律服务端所有,`resolve` 拒绝任何 `currency` 入参(`catalog.py:200-201`),checkout 体 `extra="forbid"` 拒绝客户端价格/金额/回跳字段(`routes.py:29-34`)。
2. payment 模式必须携带报告标识 `query_key/report_key`,否则 409(`service.py:196-197`);该标识贯穿 metadata→`client_reference_id`→`payment_orders.subject_id`→`_has_report_unlock`。
3. 订阅镜像的价格字段不可被后续事件改写(`store.py:36-40`);`paused` 无 V1 表示 → dead-letter 让人工处理(`store.py:156-158,896-898`)。
4. 权益联动 `_sync_membership_entitlement` 只在 status∈{active,trialing} 且周期未过时授予;否则降回 `free` 且 `daily_query_limit=3`(`store.py:109-115`)。
5. C Plus 报告额度 12/月(UTC+8),以报告为幂等键消费(`main.py:151-193`);已消费过的报告永久保持解锁(判定 3,`main.py:137-141`)。
6. 额度硬约束在 DB 用条件 UPDATE,不是应用层先查后写(`db_ledger.py:641-653`);跨周期重放靠 advisory lock + 指纹含周期(`db_ledger.py:33-41,208-230`)。
7. 后台写操作(角色授予/撤销、会员状态、采集入队、定价四项)全部与 `audit_events` 同事务提交(`admin/service.py:947-984,995-1019,1045-1088,1118-1154`)。
8. `super_admin` 不能撤销自己的 `super_admin`(防锁死,400)(`admin/routes.py:591-611`)。
9. 会员状态幂等:设为当前值 → `changed=false` 且不写审计(`admin/service.py:1056-1062`)。
10. 发布阶段:生产/staging 未显式配置阶段 → `unconfigured_managed` → 除四个 always-allowed 外全拒;`consumer_intake_preview` 仅放行白名单;`consumer_active`/`development` 全放行(`release_scope.py:65-90`)。

**坑 / 未确认**
- `usage/routes.get_usage_service` 恒 503,`PostgresLedger` 未接线;计费则需 `STRIPE_SECRET_KEY`+`STRIPE_WEBHOOK_SECRET` 才可用(`routes.py:43-47`)。两者在 `consumer_intake_preview` 阶段还会被中间件 404。
- `/api/billing/prices` 使用模块级 `_PUBLIC_CATALOG = PriceCatalog({})`(`routes.py:26`),无 env 价目,只有 DB 可用时 `available` 才多为真;测试环境回落到代码兜底时 `available=false`(测试 `tests/billing/test_routes.py:80-91`)。
- 定价后台化只写 `pricing_products/prices/regions/plans`;而**权益联动额度是硬编码**(`store.py:115,137-138`),并不读取 `pricing_plans`(`catalog.get_plan` 也未参与下单/权益路径)。改后台套餐数值当前不会改变实际授予额度 —— 未确认是否有其它消费者。
- 报告额度耗尽时,写路径抛 `RuntimeError`(`main.py:191-192`)会被生成任务 `except Exception`(`main.py:323-330`)捕获并把 job 标记失败,尽管报告已保存。
- `account_controls.INTERNAL_ROLE_PERMISSIONS` 与 `admin` 的 DB CHECK 角色词表不一致,且该模块无路由接线。
- `db.py.init_schema()` 直接读取 `backend/sql/schema.sql` 全量执行(`db.py:36-39`),仅在 `INIT_SCHEMA=true` 且 `ENVIRONMENT∈{local,development,test}` 时于 lifespan 调用(`main.py:47-50`);与 Supabase 迁移历史并存(仓库 AGENTS.md 已标注 schema 归属未决)。
- 后台端点未纳入应用日志(`admin/service.py:26-30`),成员视图中邮箱按角色脱敏。

---

## 验证情况

- 运行(只读,未改文件):`backend/.venv/bin/python -m pytest -q tests/billing` → **47 passed**;`tests/unit/test_account_controls.py tests/unit/test_privacy_contracts.py` → **12 passed**;`tests/api/test_report_access.py tests/api/test_usage_routes.py tests/api/test_privacy_routes.py` → **19 passed**;`tests/unit/test_admin_api.py tests/unit/test_usage_ledger.py` → **70 passed, 21 skipped**(skip 为需要真实 PostgreSQL 的用例)。
- 未运行需要真实 DB 的 `tests/unit/test_db_ledger.py`、`tests/unit/test_billing_store.py`(依赖 `_migrated_database`,本环境无 Supabase/Postgres),其中并发/幂等结论来自源码与迁移文件,标注为代码事实而非本机实测。
- 未修改/创建任何文件。


---


# 第 3 部分 · 前端全部页面与逻辑


I've read all 19 pages and 14 JS modules. Here's the complete technical specification.

---

# 小象房产套件 — 前端全部页面与逻辑技术说明

> 范围:`/Users/gordonmac/GordonDev/JPPropDIs/web/`。只读分析,未改动任何文件。
> 全部结论附 `文件:行号`;无法从前端代码确认的标注「未确认」。

## 0. 总览:无构建静态站

- 无打包器/转译器/框架。页面直接 `<script src>` 加载原生脚本;ES module 页面用 `<script type="module">`(`web/property-analysis.html:346`、`web/project.html:559`)。
- 两套并存运行时:
  - **经典脚本(全局挂载)**:`config.js` → `js/release-boundary.js` → `js/i18n.js` → `app.js` → 页面脚本(B 端/C 端登录页)。
  - **ES module**:`property-analysis.html` / `projects.html` / `project.html` 通过 `import` 引用 `js/api-client.js` 等。
- 资源用 `?v=YYYYMMDD-NN` 查询串做缓存失效(如 `web/index.html:10`、`web/admin.html:527-533`)。
- `.nojekyll`(`web/.nojekyll`)用于禁用 GitHub Pages 的 Jekyll 处理(未确认实际托管是否仍用 Pages)。

---

## 1. 页面清单

| 页面 | 用途 | 加载的 JS 模块(文件:行号) | 主要交互 |
|---|---|---|---|
| `index.html` | B 端数据工作台首页;登录/注册入口 + 最近更新列表 | `config.js`、`release-boundary.js`、`i18n.js`、`app.js`、`js/business.js`(`index.html:149-154`);内联注册 SW(`:157-161`) | 登录/注册/找回密码;最新列表分页;卡片点开的详情;图片放大对话框(`:135-147`) |
| `property-analysis.html` | **C 端**「分析一个日本物件」5 步流程 | `config.js`、`i18n.js`(经典)、`js/property-intake.js`、`js/recognition.js`(module,`:344-347`)。**不加载 release-boundary** | 用途→资料→字段确认→免费预览→注册保存;拍照/上传/拖拽;EXIF 定位;进度环与清单 |
| `data-query.html` | B 端结构化数据查询 | 同 index + `js/business.js`(`:167-171`) | 都道府县/市区町村/区/物件类型/年/月下拉联动;查询/生成;查询历史 chip(`:117-130`) |
| `analysis.html` | B 端趋势图与比较 | `config.js`、`release-boundary.js`、`i18n.js`、`app.js`(`:185-188`) | 关键词/指标(月租金、买房总价、租售比)/面积段;canvas 趋势图;多记录比较(`:117-134`) |
| `mypage.html` | B 端「数据与服务工作台」 | 同 index(无 business.js)(`:145-148`) | 登录后展示查询任务卡片、手动执行 JPHOUSE、查看结果、刷新(`:112-128`) |
| `profile.html` | B 端账户资料/安全/隐私 | `config.js`、`release-boundary.js`、`i18n.js`、`app.js`、`js/profile-role.js`(`:201-205`) | 编辑资料、改密码、账户删除对话框(`:188-199`)、`?role=consumer` 切换品牌为 C 端 |
| `admin.html` | 后台维护(9 个 tab) | `config.js`、`release-boundary.js`、`i18n.js`、`js/admin-mode.js`、`js/admin-api-client.js`、`js/admin-views.js`、`js/admin.js`(`:527-533`) | 总览 KPI、采集、质量、服务派单、会员、审计、财务、定价、内部角色 |
| `project.html` | C 端项目工作台(报告版本/状态) | `js/project-workspace.js`(module,`:559`)。无 i18n | URL `?demo=1&state=<preview\|ready\|running\|completed\|failed\|update>&version=<v1..v3>` 驱动状态机 |
| `projects.html` | C 端我的项目列表 | `js/projects.js`(module,`:79`) | `?demo=1` / `?empty=1`;状态筛选;项目卡跳 `project.html?demo=1&state=...` |
| `organization.html` | B 端机构与成员 | `config.js`、`release-boundary.js`、`i18n.js`、`js/business-pages.js`(`:96-99`) | 成员列表、邀请按钮、席位汇总(演示) |
| `billing.html` | B 端套餐与账单 | 同上(`:108-111`) | 币种切换(CNY/JPY/USD)、选套餐、自动续费开关(演示) |
| `usage.html` | B 端用量与额度 | 同上(`:89-92`) | 额度卡片(演示) |
| `subscriptions.html` | B 端统计订阅 | 同上(`:89-92`) | 订阅列表 + 新建订阅表单(演示) |
| `exports.html` | B 端数据导出 | 同上(`:90-93`) | 数据集/格式选择、导出任务(演示) |
| `service-tasks.html` | B 端服务任务池 | 同上(`:87-90`) | 状态筛选、接单、打开详情(演示) |
| `privacy.html` | 隐私政策(静态离线草案) | **无脚本**(`privacy.html:1-45`) | 纯静态;标注 `no real customer data`(`:30`) |
| `terms.html` | 服务条款(静态草案) | 无脚本 | 纯静态 |
| `support.html` | 客服与资料主体请求 | 无脚本 | 纯静态 |
| `ui-review.html` | 三角色前端流程评审索引 | 无脚本;内联 `<style>`(`:8-38`) | 链接聚合:C 端/B 端/管理员演示入口(`:56-81`) |

> `index.html` 的 `js/business.js` 只处理 `[data-service-task]`/`#businessTaskFilter`,index 页面无此类元素,属无害冗余(`web/js/business.js:2-4`)。

---

## 2. 前端架构

### 2.1 模块加载方式
- **经典脚本**页面按固定顺序内联 `src`(顺序即依赖):`config.js`(全局配置)→ `release-boundary.js`(门控,可能拦截 `fetch`)→ `i18n.js`(立即 `apply(document)`,`i18n.js:1429`)→ `app.js` → 页面脚本。
- **module 页面**(`property-analysis`/`projects`/`project`)不走经典脚本链:`api-client.js` 通过 `import` 被引入(`property-intake.js:1-10`),`config.js` 与 `i18n.js` 仍以经典脚本先加载(`property-analysis.html:344-345`)。
- `api-client.js` 是唯一被复用的 module;`admin-api-client.js`(经典)注释明确说明因 admin 页用经典脚本链而**复制**了约 20 行 token 读取逻辑(`admin-api-client.js:7-10`)。

### 2.2 API base / config 注入 / `ZOUSEEKING_*` 全局
- 部署期生成的 `web/config.js`(`deploy/render-frontend-config.py:29-38`)设置 4 个全局:
  - `ZOUSEEKING_API_BASE_URL`
  - `ZOUSEEKING_SUPABASE_URL`
  - `ZOUSEEKING_SUPABASE_ANON_KEY`
  - `ZOUSEEKING_RELEASE_SCOPE`(冻结对象 `{phase, businessOperations, adminOperations}`)
- git 树内 `config.js` 为开发默认:`api_base = https://zouseeking-api-staging.onrender.com`,scope 为 `consumer_intake_preview` + `businessOperations:false` + `adminOperations:false`(`web/config.js:1-8`)。
- **生成脚本**`render-frontend-config.py`:默认 api base `https://api.zoubeacon.com`(`:23`),`business_operations = phase != "consumer_intake_preview"`(`:24`),`adminOperations` 与 business 同值(`:36`);要求 `SUPABASE_URL`/`SUPABASE_ANON_KEY`(`:55-62`);默认输出 `web/config.js`(`:44`)。`web/config.js` 被 `.gitignore`(`.gitignore:2`),部署文档要求每次更新前运行(`deploy/README.md:65-68`)。
- **读取优先级**:
  - `api-client.js`:仅 `window.ZOUSEEKING_API_BASE_URL`(`api-client.js:1`)。
  - `app.js`:`window.ZOUSEEKING_API_BASE_URL || localStorage["zou_house_api_base"]`,Supabase 同理带 localStorage 回退(`app.js:6-8`)。
  - `admin-mode.js`:`window.ZOUSEEKING_API_BASE_URL || localStorage["zou_house_api_base"]`(`admin-mode.js:33-35`)。

### 2.3 请求构造
- **C 端 intake(`api-client.js`)**:
  - `request(path, {method, body, sessionToken, accessToken})`(`api-client.js:12-44`)。
  - 相对路径拼 `${API_BASE_URL}${path}`,base 去尾斜杠(`:1`、`:24`)。
  - 匿名会话令牌走**自定义头** `X-Analysis-Session`(`:15`);已登录走 `Authorization: Bearer <accessToken>`(`:16`)。
  - `body` 非 `FormData` 时自动 `JSON.stringify` + `Content-Type: application/json`(`:17-20`);`uploadFiles` 用 `FormData`(`:63-77`)。
  - 端点:`POST /api/intake/sessions`(`:47`)、`/inputs`(`:56`)、`/files`(`:69`)、`PUT /fields/{name}`(`:90`)、`PUT /location`(`:100`)、`POST /preview`(`:108`)、`POST /convert`(`:115`)。
- **B 端(`app.js`)**:
  - `apiFetch(path, options)` 打 `${API_BASE_URL}${path}`,有 session 时加 `Authorization: Bearer`(`app.js:555-563`)。
  - `supabaseAuthFetch` 打 `${SUPABASE_URL}/auth/v1`(`:449-472`);`supabaseFetch` 打 `${SUPABASE_URL}/rest/v1`(匿名 apikey,`:642-659`);`supabaseUserFetch` 用用户 access token(`:661-668`,均带 `apikey` + `Authorization`)。
- **后台(`admin-api-client.js`)**:`request` 拼 `${ZouAdminMode.apiBaseUrl}${path}${query}`(`:57`),`buildQuery` 跳过 `undefined/null/""`(`:41-49`),仅带 `Authorization: Bearer`(无自定义头,`:66`)。

### 2.4 鉴权(如何带 JWT)
- 单一来源:本地会话对象的 `accessToken`。
- **B 端**:`state.session` 存于 `localStorage["zou_house_session"]`(`app.js:1`、`:474-481`),由 Supabase Auth 流程写入(`sessionFromAuth`,`:483-496`);`apiFetch`/`supabaseUserFetch` 从中取 token(`:560`、`:667`)。
- **C 端 intake/module 页**:`getExistingAccessToken()` 按序读 `window.ZOUSEEKING_AUTH_SESSION` / `__ZOUSEEKING_AUTH_SESSION__` → `sessionStorage["zou_house_auth_session"]` → `localStorage["zou_house_session"]`(仅 `provider==="supabase"`)(`api-client.js:123-144`)。**注意:匿名资料用 sessionStorage,登录凭证只读 localStorage**。
- **后台**:`admin-api-client.getAccessToken()` 复制同逻辑(`admin-api-client.js:12-29`),额外允许 `sessionStorage["zou_house_auth_session"]`;无 token 抛 `AdminApiError(...,"no_session")`(`:54-56`)。
- 说明:`sessionStorage["zou_house_auth_session"]` 在前端代码中**只被读取、未见写入**(`grep` 全仓仅读取处:`api-client.js:128`、`admin-api-client.js:16`);其写入者「未确认」(推测为注入/部署层)。

### 2.5 错误处理
- `api-client.request`:网络异常统一抛「暂时无法连接分析服务…」(`api-client.js:29-31`);非 2xx 从 `payload.detail|message` 提取,挂 `error.status/code/payload`(`:34-41`);`parseResponse` 容错非 JSON(`:3-10`)。
- `app.js apiFetch`:非 2xx 抛错(具体在 `:564` 起);`supabaseAuthFetch` 从 `msg/message/error_description/error` 取消息(`:468`)。
- `admin-api-client`:无 token → `no_session`;网络 → `network`;非 2xx 抛 `AdminApiError(status, payload)`(`:70-86`)。
- UI 侧统一 `setStatus(message, tone)` 并用 `role="alert" aria-live="assertive"`(`property-analysis.html:82`;`property-intake.js:177-184`)。

---

## 3. 核心流程

### 3.1 C 端查询流(5 步)
步进器与阶段(`property-analysis.html:57-63`;`property-intake.js:196` `setStage`):`purpose→submit→confirm→preview→save`。

1. **选择用途**:`self_use` / `rental_investment` 单选(`property-analysis.html:93-103`)。
2. **提交资料** — `startIntake()`(`property-intake.js:615-675`):
   - 校验用途、物件类型(必填)、以及「来源 text/文件/照片至少其一」(`:625-635`);
   - `createSession(purpose)` → 存匿名会话(含 `sessionId/rawToken/expiresAt/assetType`,`:644-650`);
   - 有文本/URL 则 `addTextOrUrlInput`(`:651`,自动判 `^https://` 走 url,`:55`);
   - 文件+照片 `uploadFiles`(`:652-654`);
   - 进入 `confirm`,`focus` 售价字段(`:665-667`)。
   - 文件限额 20MB(`:12`;`validateFiles:220`、`validatePhotoFiles:238`)。
3. **确认字段** — 5 个可确认字段:`asking_price_jpy, area_sqm, building_name, address, land_right`(`:51-57`;DOM `property-analysis.html:233-257`);实时「已填写 n/5」与进度条(`:251-255`)。定位按钮生成地址建议(`:411-471`),回填 `[data-field='address']`(`:449-453`)。
4. **免费预览** — `createFreePreview()`(`property-intake.js:677-725`):逐字段 `confirmField(...,"confirmed")`,地址附证据 locator(`:703-712`),再 `generatePreview` 渲染完整度/费用/风险/可比(`:713-717`;渲染 `renderPreview:536-614`)。
5. **注册保存** — `saveProject()`(`property-intake.js:727-772`):无 accessToken 时提示先登录(`:742-745`);`convertSession(sessionId, rawToken, accessToken, projectName)` 绑定账户并返回 `property_id`(`:749-763`)。项目名冲突由 `handleProjectNameError` 处理(`:765`、`:483`)。

### 3.2 拍照识别 → EXIF 定位 → 预填
- `recognition.js`:选照片后 `resolveLocation(file)`(`:36-61`),要求已登录 + api base(`:37-38`);`fileToDataUrl`(`:15-22`)后 `POST /api/recognition`,body `{image, resolve_location_only:true}`,带 Bearer(`:43-47`)。
- 返回 `payload.location` 时 `saveLocationPrefill` 写 `sessionStorage["zou_recognition_prefill"]`(`:24-30`)。**C 端本身使用设备定位**(`requestDevicePosition`,`property-intake.js:392-403`;`saveLocation`),与 EXIF 是两条独立路径。
- 预填消费:`app.js consumeRecognitionPrefill()` 读并删除该 key,`applyOptionsToForm` 后提示「识别结果已预填」(`app.js:2158-2170`;`init` 在 `:2065` 调用)。即 EXIF 结果用于 **B 端 data-query 表单预填**(省/市/区)。

### 3.3 报告查看与「按份解锁」UI
- 拉报告:`viewReportByQueryKey(key)` 优先 `GET /api/reports/{key}`,否则 Supabase `property_reports`(`app.js:1337-1341`)。
- **锁定分支**:`report.locked` 为真时,把一条 `{locked:true, query_key, title, unlock_hint}` 伪记录推入列表并渲染解锁卡,**不返回正文**(`app.js:1346-1362`)。
- **解锁卡 UI**:`renderDetail()` 中 `record.locked` 时渲染 `🔒 + unlock_hint`、按份文案 `report.singleUnlockCopy`、按钮 `data-unlock-report`(`app.js:1971-1979`);已解锁显示「已解锁」pill(`:1997`)。
- 文案:「购买后解锁本份深度报告」/「解锁深度报告」(`i18n.js:186-188`,英 `:639-641`,日 `:1092-1094`)。

### 3.4 付费入口(checkout)
- `startReportUnlock(queryKey)`(`app.js:1373-1398`):未连接后端提示「支付服务未连接」(`:1374-1376`);`POST /api/billing/checkout`,body `{product_code:"risk_report_single", billing_region:"CN", query_key}`(`:1381-1388`);拿到 `checkout.url` 即 `window.location.assign` 跳转(`:1389-1391`,应为 Stripe Checkout,`admin.html:419` 出现 `Stripe price id` 字段)。
- 客户端不做解锁判定:解锁状态由后端 `report.locked` 决定(`:1346`)。
- V1 区域硬编码 `"CN"`,注释「region picker follows」(`:1385`)——区域选择器尚未实现。

### 3.5 B 端数据查询 / 分析 / 导出 / 订阅
- **查询**:`data-query.html` 表单 → `handleStructuredQuery()`(`app.js:1737-1773`);读选项 `readQueryOptions`(`:1591`);本地命中计数(`:1745`);有后端时 `runBackendQuery`(POST `/api/query`,无 report 则轮询 `/api/jobs/{id}` 最多 30 次 ×900ms,`app.js:1692-1735`);无后端时仅本地 + 提示(`:1757-1759`);写历史 `saveQuery`(`:1602-1617`,`localStorage["zou_house_query_history"]`,`:2`)。
- **分析**:`analysis.html` 表单 → `renderAnalysis` + `drawAnalysisChart`(canvas 折线,`app.js:1194-1248`);指标 `rent/sale/ratio`(`:1024-1040`);租售比从 `summary.line` 字符串里按 `｜` 切分解析(`ratioForLayout`,`app.js:1015-1021`)。
- **导出 / 订阅 / 用量 / 机构 / 服务任务**:全部由 `js/business-pages.js` 的 `renderExports/renderSubscriptions/renderUsage/renderOrganization/renderServiceTasks` 渲染,**纯本地演示数据**(`:82-392`;init `:393-402`)。导出/订阅只有本地状态变更,无真实 API。
- 数据来源:`content-library.json`(`app.js:2056`)与 `field-options.json`(`:427`);有 Supabase 时再用 `query_field_options` 覆盖(`:440-443`)。

### 3.6 后台 admin 各 tab
`admin.js` 仅做协调;tab→`data-admin-section` 显隐(`admin.js:1384-1395`),`data-admin-section` 含 `overview` 的 section 在「总览」也可见。9 个 tab(`admin.html:91-99`):

| tab | 数据源 | 说明 |
|---|---|---|
| 总览 | `/api/admin/overview`(live) | KPI 卡片,`loadOverviewKpis`(`admin.js:1282`) |
| 采集 | `/api/admin/collection/runs`;写 `POST`(data_ops/super_admin) | 演示表 + 真实表,发起采集入队 queued(`admin-api-client.js:134-157`;`admin.js:862-965`) |
| 质量 | `/api/admin/collection/runs?status=failed` | failed/swept 队列,可重投(`admin.js:1015-1157`) |
| 服务派单 | `/api/admin/service/tasks`(只读) | C 端服务任务台账(`admin-api-client.js:145-150`) |
| 会员 | `/api/admin/members`;写 `/members/{id}/status` | 搜索/分页/停用恢复,写审计(`:106-121`;`admin.js:270-375`) |
| 审计 | `/api/admin/audit?actor&action&since&limit` | 只读(`admin-api-client.js:122-125`) |
| 财务 | `/api/admin/finance/orders`、`/refunds` | 只读,金额按 ISO 最小单位(`:126-133`) |
| 定价 | `/api/admin/pricing`(+写 prices/regions/plans) | 数据库驱动,改价新增版本(`:91-105`;`admin.html:408-440`) |
| 内部角色 | `/api/admin/internal/me` + roles 授予/撤销 | super_admin 专属,不能撤销自己(`admin.js:537-752`) |

模式判定:`isLive = mode.live && api && views`(`admin.js:14-17`);`live` 由 api base 非空 ∧ 非 `?demo=1` ∧ `ZOUSEEKING_REAL_OPERATIONS_DISABLED!==true` 决定(`admin-mode.js:36-38`)。演示默认;liver 下 403/失败渲染可见状态而非回退演示数据(`admin.js:2-12`)。

---

## 4. i18n

- **语言集合**:`["zh-CN","en","ja"]`(`i18n.js:3`)。
- **key 组织**:单一 `DICTIONARY` 对象,`zh-CN`(`:5-457`)、`en`(`:458-910`)、`ja`(`:911-1363`)。key 用点分命名空间:`nav.* / account.* / query.* / analysis.* / report.* / business.* / admin.* / recognition.* / region.* / common.*` 等。
- **覆盖度**:三语各 **451** 个 key,**完全对齐**(0 缺失/0 多余,经脚本比对)。
- **切换机制**:`data-locale-switcher` 下拉(`index.html:37-41` 等);`apply()` 绑定 change → `setLocale`(`i18n.js:1405-1409`),`setLocale` 写 `localStorage["zou_ui_locale"]`、`apply(document)` 后 `window.location.reload()`(`:1417-1426`)。
- **应用方式**:`data-i18n`(textContent)、`data-i18n-placeholder`、`data-i18n-aria-label`、`data-i18n-title`,并设 `document.documentElement.lang`(`:1392-1411`)。
- **缺失回退**:`t(key, fallback) = DICT[当前] || DICT["zh-CN"] || fallback`(`:1380-1382`);`apply` 未命中时以元素当前文本为 fallback(`:1396`)。启动即 `readLocale`(`localStorage`,异常回退 `zh-CN`,`:1370-1378`)并 `apply(document)`(`:1429`)。
- 注意:`project.html` / `projects.html` / `property-analysis.html` 的部分文案**未走 i18n**(硬编码中文);`property-analysis.html` 引 `i18n.js` 但流程正文为硬编码。

---

## 5. `release-boundary.js` 的作用

- IIFE,在 `config.js` 之后、业务脚本之前运行(`web/index.html:150-151` 等)。
- 读取 `ZOUSEEKING_RELEASE_SCOPE` 与 `document.body.dataset.role`;当 `phase === "consumer_intake_preview"` 且(role=business 且 `businessOperations===false`)或(role=admin 且 `adminOperations===false`)时判定为 demo-only(`release-boundary.js:2-7`)。
- demo-only 时**覆盖 `window.fetch`**:仅放行同源 GET `/content-library.json` 与 `/field-options.json`(静态公开数据),其余一律 reject `"real operations are disabled on this demo-only surface"`(`:10-24`);并置 `window.ZOUSEEKING_REAL_OPERATIONS_DISABLED = true`(`:25`)。
- 对前端行为的影响:
  - `admin-mode.js` 据此把 admin 面标为非 live(`admin-mode.js:37-38`);
  - `app.js` 的 `ensureUserProfile` / `saveProfile` 在 flag 为真时直接跳过真实写入(`app.js:770`、`:842`)。
- 范围限制:仅加载该脚本的页面受影响(index/data-query/analysis/mypage/profile/B 端各页/admin)。**C 端 `property-analysis.html`、`projects.html`、`project.html` 不加载**,故不受此门控。
- git 树默认 scope 为 `consumer_intake_preview`(`config.js:4-8`),故默认所有 business/admin 面均被门控为 demo;部署时 `RELEASE_PHASE != consumer_intake_preview` 才会置业务/admin 为 true(`render-frontend-config.py:24,36`)。

---

## 6. PWA

- **manifest**(`manifest.webmanifest:1-16`):`name=小象数据 ZOUSEEKING`,`short_name=小象`,`lang=zh-CN`,`start_url=./index.html`,`scope=./`,`display=standalone`,`background_color=#ffffff`,`theme_color=#0b1020`;图标 192/512 + maskable(复用 512)。各页 `<link rel="manifest">` 与 `<meta theme-color>`(如 `index.html:6-7`)。
- **service worker**(`sw.js`):
  - 版本 `2026-09-09-r1`(`:9`),`CACHE_NAME = zouseeking-shell-<ver>`(`:11`);
  - install 只预缓存 `./index.html` 并 `skipWaiting`(`:10,13-17`);
  - activate 清理旧 cache 并 `clients.claim`(`:19-26`);
  - **缓存策略**:同源静态资源 stale-while-revalidate(先返回缓存、后台更新,`:41-54`);`isStaticAsset` 只缓存 `/assets/*` 与 `css/js/json/webmanifest/svg/png/ico/woff2` 后缀,`/api/` 与跨域(auth/rest/functions)永不缓存(`:28-39`)。
  - 破缓存方式:改 `SW_VERSION`(`:7` 注释)。
- **注册**:仅 `index.html` 内联注册,要求 `serviceWorker in navigator` 且 `isSecureContext`,在 `load` 时 `register("sw.js",{scope:"./"})`,失败静默(`index.html:157-161`)。
- **安装提示**:**未实现自定义安装提示**(无 `beforeinstallprompt`/`appinstalled` 监听,全仓 grep 无命中);安装依赖浏览器原生 UI。

---

## 7. 状态管理(localStorage / sessionStorage)

| 存储 | key | 写入处 | 读取处 | 用途 |
|---|---|---|---|---|
| localStorage | `zou_house_session` | `app.js:477`(saveSession,登出移除 `:479`) | `app.js:205`、`api-client.js:138`、`admin-api-client.js:23` | B 端登录会话(username/email/userId/accessToken/refreshToken/provider) |
| localStorage | `zou_house_query_history` | `app.js:263` | `app.js:259` | 查询历史(最近 5 条 chip) |
| localStorage | `zou_house_api_base` | 无前端写入 | `app.js:6`、`admin-mode.js:34` | 每浏览器 API base 覆盖 |
| localStorage | `zou_house_supabase_url` / `zou_house_supabase_anon_key` | 无前端写入 | `app.js:7-8` | Supabase 覆盖 |
| localStorage | `zou_ui_locale` | `i18n.js:1420` | `i18n.js:1372` | 界面语言 |
| sessionStorage | `zou_house_property_intake_session` | `property-intake.js:170` | `property-intake.js:159` | C 端匿名 intake 会话(`{sessionId,rawToken,expiresAt,assetType}`;DEMO 模式不写 `:157,168`) |
| sessionStorage | `zou_recognition_prefill` | `recognition.js:25` | `app.js:2160` | EXIF 识别出的 prefecture/city/ward → B 端查询表单预填 |
| sessionStorage | `zou_house_auth_session` | 仅读取(未确认写入者) | `api-client.js:128`、`admin-api-client.js:16` | 供 module 页/admin 读取登录 token |

- 页面内状态:`property-intake.js` 的 `state`(`:100-110`);`app.js` 的 `state`(`:199-215`,含 `records/query/queryOptions/page/session/fieldOptions/myTasks/profile/compareIds`);`project-workspace.js` 的 `state`(`:7-11`,由 URL query 驱动)。
- 跨页数据传递主要靠:`localStorage`(会话/历史/语言)+ `sessionStorage`(匿名 intake/EXIF 预填)+ URL query(`?demo/?role/?state/?version/?empty`)。

---

## 8. 坑 / 注意事项

1. **门控只在前端**:`release-boundary.js` 通过覆盖 `fetch` 禁用「真实操作」(`:12-24`),但这是 UI 层限制,不是授权控制(与 `AGENTS.md` 的「前端限制不是授权控制」一致)。
2. **token 读取键不一致**:B 端写 `localStorage["zou_house_session"]`(`app.js:1,477`),而 module/admin 客户端优先读 `sessionStorage["zou_house_auth_session"]`(`api-client.js:128`)。该 sessionStorage 键**前端无写入点**(未确认谁写),实际登录后 module 页能否取到 token 取决于外部注入。
3. **两套 API 客户端重复**:`api-client.js`(module)与 `admin-api-client.js`(经典)各自复制了 token 读取与错误处理(`api-client.js:12-44` vs `admin-api-client.js:51-88`),修改需同步。
4. **C 端与 B 端模块互斥**:`property-analysis.html` 只引 module 客户端,**不引 `app.js`**,因此无 `ZouI18n` 之外的共享状态;`api-client.js` 与 `app.js` 各自维护自己的 `API_BASE_URL`。
5. **大量 B 端页面是纯演示**:`business-pages.js`、`business.js`、`projects.js`、`project-workspace.js` 全部为本地/synthetic 数据,按钮只改本地状态(`business-pages.js:82-392`;`projects.js:4-10`;`project-workspace.js:44-94`)。不要误判为已接后端。
6. **admin 演示 vs live 混排**:演示表(`#collectionDemoWrap` 等)与真实表(`#collectionLiveWrap`)并存,由 `isLive` 显隐(`admin.js:14-17,1646-1664`);live 失败时**不回退演示**,而是渲染错误态(`admin.js:2-12`)。
7. **分析页解析展示字符串**:租售比从 `summary.line` 用 `｜` 切分再 `numberFromText`(`app.js:1015-1021`),与 `AGENTS.md` 已知阻塞项「分析页从展示字符串取值」一致。
8. **付费区域硬编码** `billing_region:"CN"`,注释说明区域选择器待做(`app.js:1385`);解锁判定完全依赖后端 `report.locked`(`:1346`)。
9. **SW 只预缓存 index.html**(`sw.js:10`),其它页首访仍走网络;改部署后须手动 bump `SW_VERSION`(`sw.js:7-9`)否则 app shell 可能陈旧。
10. **`config.js` 是生成物且被 git 忽略**(`.gitignore:2`),git 树内版本指向 staging + 全 demo;本地起服务看到的行为与生产不同。
11. **域名/路由**:nginx 将 `zoubeacon.app` 的 `/` 重写到 `property-analysis.html`(C 端),`try_files` 回退 `index.html`(B 端);`platform.zoubeacon.com` 同 `html-site` 目录;`zoubeacon.com` 指向独立的 `html-corp`(`deploy/nginx/default.conf:22,39-43,59-60`;`deploy/docker-compose.prod.yml:54-55`)。`html-corp`(公司官网)内容不在仓库 `web/` 中,「未确认」。
12. **样式组织**:基础共用 `styles.css`;B 端 `business.css` + 二级页 `business-pages.css`;C 端 `property-analysis.css`;工作台/评审 `project-workspace.css` + `projects.css`;后台 `admin.css`。各页按需 `<link>`,并用 `?v=` 版本化;`privacy/terms/support/ui-review` 额外内联 `<style>`(如 `privacy.html:10-21`、`ui-review.html:8-38`)。
13. **key 与页面文案重复维护**:`data-i18n` 的 fallback 是元素当前文本(`i18n.js:1396`),硬编码与字典可能漂移;新增页面若漏 `data-i18n` 则切语言不生效。

---

### 交付说明
- **做了什么**:只读通读 `web/` 下 19 个 HTML、`app.js`(2177 行)、`web/js/*` 全部 14 个模块、`config.js`、`sw.js`、`manifest.webmanifest`,以及部署侧 `deploy/render-frontend-config.py`、`deploy/nginx/default.conf`、`deploy/docker-compose.prod.yml` 以确认 config 注入与域名路由。
- **关键结论**:无构建静态站,经典脚本链 + 少量 ES module 并存;`config.js` 部署期生成并注入 4 个 `ZOUSEEKING_*` 全局;JWT 经 `Authorization: Bearer` 传递,匿名 intake 走 `X-Analysis-Session`;C 端 5 步流程真实接 `/api/intake/*`;付费为按份 `risk_report_single`(Stripe Checkout)→ 后端 `locked` 驱动解锁 UI;B 端多数业务页与后台「审核/派单」为本地演示;i18n 三语各 451 key 完全对齐。
- **未创建/修改任何文件**(遵守只读约束)。
- **待确认项**:`sessionStorage["zou_house_auth_session"]` 的写入者;公司官网 `zoubeacon.com` 的 `html-corp` 内容;生产 `RELEASE_PHASE` 实际取值。


---


# 第 4 部分 · 数据层与数据库 schema/RLS


以下为「数据层与数据库 schema/RLS」完整技术说明。已通读 `supabase/migrations/` 全部 24 个 SQL、`data/`、`configs/`、`backend/data/`、3 个构建脚本及迁移 README / schema-ownership 文档。所有关键结论附 `文件:行号`。

---

# 小象房产套件 · 数据层与数据库 schema/RLS 技术说明

> 托管 Supabase 项目 ref `fnogxuytbabxmqousifh`（新加坡区）。迁移目录 `supabase/migrations/` 是**唯一前向迁移历史**（`supabase/migrations/README.md:3`；`docs/architecture/schema-ownership-audit.md:12`）。
> 基线状态：`canonical_staging_reconciled_production_pending`（`supabase/migrations/README.md:13`；`docs/architecture/schema-ownership.json:5`）。

---

## 1. 迁移清单（按时间顺序）

编号不连续处标「缺口」，历史缺失 ID **未 repair/伪造**（`supabase/migrations/README.md:21-24`）。文件列共 **24 个**，`docs/architecture/schema-ownership.json` 的 `forward_migration_files` 已完整登记；最新两条分别登记报告购买主体与后台定价目录。

### A. Baseline / 数据契约（2026-08-24 批次）

| 文件 | 目的 | 关键 DDL |
|---|---|---|
| `20260824000100_legacy_schema_baseline.sql`（85 行）**baseline** | 建新装基线 schema，无客户数据 | 扩展 `pgcrypto`/`pg_trgm`（`:3-4`）；表 `queries`（`:6-13`，`query_key` unique、`status` default `'pending'`、`requested_by_name/email`）、`query_field_options`（`:14-18`，unique `(option_type,parent_value,value)`）、`generation_jobs`（`:19-23`，`progress` 0–100 check）、`property_reports`（`:24-31`，`query_key`/`slug` unique，`rental/sale/summary/images/data_sources/raw_record` jsonb）、`data_sources`（`:32-36`）、`user_profiles`（`:37-42`，PK `user_id` refs `auth.users` on delete cascade，`membership_tier` default `'free'`、`daily_query_limit` default `3`）；索引 `:44-63`；`set_updated_at()` 触发器函数 `:65-67` + 5 个触发器 `:68-77`；RLS enable `:79-84`；`revoke all … from anon, authenticated` `:85` |
| `20260824000200_foundation_data_contract.sql`（75 行）**baseline/数据契约** | 来源/物业/证据/指标/风险/policy 基础域 | `data_class` enum：`verified_observation, scraped_aggregate, modeled_estimate, synthetic_fixture, user_submitted`（`:2-4`）；表 `sources`（`:6-10`）、`properties`（`:11-22`，`project_type` check `('residential','new_build','commercial_investment')` `:13`，`data_class` default `user_submitted` `:18`，`confidence` check `:19`）、`residential_details`（`:23-29`）、`new_build_details`（`:30-34`）、`commercial_investment_details`（`:35-39`）、`evidences`（`:40-44`）、`analysis_metrics`（`:45-49`，unique `(property_id,metric_name,calculation_version)`）、`risk_findings`（`:50-54`，`severity` check）、`policy_documents`（`:55-60`，unique `(policy_key,effective_from)`）、`product_events`（`:61-65`）；索引 `:66-71`；`set_sources/properties_updated_at` 触发器 `:72-75` |
| `20260824000300_private_project_rls.sql`（97 行）**RLS baseline** | owner 字段 + 服务角色保护 + owner-scoped RLS 起点 | `queries/property_reports/data_sources` 加 `owner_user_id uuid refs auth.users on delete set null`（`:3-5`）；唯一索引 `uq_property_reports_query_id`（`:9-10`）；`is_service_role()`（`:12-15`，判断 `current_user in ('postgres','service_role','supabase_admin')` 或 `request.jwt.claim.role`）；`prevent_client_ownership_change()`（`:16-24`）+ 3 触发器 `:25-30`；RLS enable 16 表 `:32-47`；drop/recreate 全部 policy `:49-61`；`revoke all … from anon, authenticated`（`:62-65`），`grant select`（`:66-68`）、`grant select,insert,update on user_profiles`（`:69`）；owner-select policy `:71-85`；`prevent_client_membership_change()`（`:87-95`）+ `protect_membership_fields` 触发器 `:96-97`（非 service_role 不能设 `membership_tier<>'free'` 或 `daily_query_limit<>3`） |
| `20260824000400_analysis_policy_versions.sql`（25 行）**业务域** | policy 版本不重叠 + 指标历史保护起点（**已被 000500 取代**） | `policy_documents_effective_dates_check`（`:2-3`）；索引 `:4`；`prevent_policy_version_overlap()` + 触发器（`:5-17`，后被 `000500:129-130` 删除）；`prevent_published_metric_update()`（`:18-25`，后被 `000500` 替换） |
| `20260824000500_provenance_and_immutable_contract.sql`（171 行）**业务域** | provenance + 不可变约束 | `sources` 加 `source_period/limitations`（`:5-7`）、`permission_status` check（`:9-11`）；`property_reports` 加 8 列（`data_class, source_url, source_locator, source_period, observed_at, transformation_version, limitations, report_status` default `generating`）（`:13-21`）、`report_status` check `('free_preview','full_report','generating','failed','insufficient_data')`（`:23-25`）、published-provenance check（`:26-40`）；`analysis_metrics` 加 15 列 + 多个 check（`:43-95`）；`risk_findings` 加列 + check（`:97-124`）；**GiST 排除约束** `policy_documents_no_overlapping_versions`（`:127-158`，启用 `btree_gist`，用 `daterange … &&` 防并发重叠）；`reject_analysis_metric_mutation()`（`:160-171`，指标 append-only，update/delete 一律抛错） |
| `20260824000600_provenance_contract_hardening.sql`（94 行）**业务域** | 收紧 V1 provenance 契约 | `sources` 加 `data_class/observed_at/transformation_version`（`:4-7`）、`set not null`（`:9-14`）、`permission_status drop default`（`:15`）、url HTTP check（`:17-18`）、非空 check（`:19-24`）；`property_reports` 加 `source_id/report_version`（`:26-28`）+ provenance check（`:30-46`）；`enforce_published_source_rights()`（`:48-80`，要求 `rights_confirmed` 来源、`data_class` 与来源一致，**跳过 synthetic 与 user_submitted**）+ `revoke all … from public,anon,authenticated`（`:81`）+ 3 表触发器 `:83-94` |
| `20260824000700_user_submitted_source_rights.sql`（86 行）**业务域/repair** | 用户提交发布需 rights-bearing source + evidence locator | 重写 `property_reports_published_provenance_check`（`:4-17`，`synthetic_fixture or source_id is not null` 且 `user_submitted` 需 `source_locator`）；`analysis_metrics` check（`:19-37`）；`risk_findings` check（`:39-51`）；**重写 `enforce_published_source_rights()`**（`:53-85`，改为**只跳过 synthetic**，`user_submitted` 也需来源）+ `revoke`（`:86`） |

### B. Intake / 私有数据（2026-08-25 ~ 08-29）

| 文件 | 目的 | 关键 DDL |
|---|---|---|
| `20260825000400_property_intake.sql`（232 行）**业务域** | 匿名 intake 会话/输入/证据/预览/限流 | 前置检查 `:6-46`；`analysis_sessions`（`:48-64`，`token_hash char(64)` unique、`purpose` check `('self_use','rental_investment')`、`status` check、约束 `expires_at > created_at and <= created_at + interval '24 hours 5 minutes'` `:62-63`）；`project_inputs`（`:66-81`，`input_type` check、`size_bytes` 1–20971520）；`project_field_evidence`（`:83-102`，`field_name` 白名单 check `:94-99`）；`project_fields`（`:104-123`，unique `(session_id,field_name)`）；`free_previews`（`:125-134`，`comparable_status` check）；`intake_rate_limits`（`:136-143`，PK `(abuse_key_hash,action,window_started_at)`）；索引 `:145-157`；RLS enable `:159-164`；`revoke` `:166-172`；`set_intake_updated_at()` `:174-182` + 触发器 `:184-192`；`prevent_intake_identity_change()`（`:194-227`，`security definer`）+ 触发器 `:229-232` |
| `20260827000500_legacy_private_data_rls.sql`（201 行）**repair/hardening** | 旧区域报告表 RLS 加固 | 前置检查 `:7-21`；重复加 `owner_user_id`（`:23-30`，`if not exists`）+ 索引 `:32-34`；重定义 `is_service_role()`（`:36-45`）、`prevent_client_ownership_change()`（`:47-61`）+ 触发器 `:63-76`；RLS enable `:78-82`；drop policy `:84-102`；`revoke … from public`（`:104-109`）与 `from anon,authenticated`（`:110-115`）；`grant select` `:117-121`、`grant select,insert,update on user_profiles`（`:122`）；owner-select policy `:124-161`（**用裸 `auth.uid()`**，与 29000100 的 `(select auth.uid())` 写法不同）；`prevent_client_membership_change()` `:163-183` + 触发器 `:185-188`；profile policy `:190-201` |
| `20260828000100_property_photo_location.sql`（106 行）**业务域** | 拍照定位/地址候选/项目名（README 明确此文件保持原字节拥有这些字段，`README.md:44-46`） | `analysis_sessions` 加 `project_name/latitude/longitude/location_accuracy_m/location_source/location_captured_at/location_consent_version/address_candidate/address_source/address_precision`（`:4-14`）；`properties` 加 `project_name/lat/long/accuracy/source/captured_at/address_source/address_precision`（`:16-24`）；约束：纬度 -90~90、经度 -180~180、accuracy > 0、`location_source in ('','device_geolocation')`、`address_source in ('manual','gsi_reverse_geocoder','unavailable')`（`:26-97`）；owner-scoped 索引 `idx_properties_owner_address`（`:100-102`）与 **唯一部分索引** `idx_properties_owner_project_name`（`:104-106`） |
| `20260829000100_baseline_access_contract.sql`（251 行）**V1/访问契约** | 22 张 application 表最终 RLS/grant | 22 表前置存在性检查 `:6-23`；RLS enable 22 表 `:25-46`；drop 所有 policy `:48-72`；`revoke all … from public,anon,authenticated`（`:74-96`）；**唯一匿名读** `grant select on query_field_options to anon`（`:98`）；`grant select` to authenticated 12 表 `:100-112`；`grant select,insert,update on user_profiles`（`:114`）；anon policy `"public can read active field options"`（`:116-118`，`is_active=true`）；owner-scoped policy `:120-244`（**用 `(select auth.uid())`**）；索引 `:246-249`；`alter function set_intake_updated_at() set search_path=public`（`:251`） |

### C. Staging 协调（2026-09-02，**唯一应用到 staging 的 migration**）

| 文件 | 目的 | 关键 DDL |
|---|---|---|
| `20260902000100_staging_baseline_reconciliation.sql`（611 行）**repair/reconciliation** | 把空 staging 基线协到 canonical 终态；不伪造旧 ledger | 前置检查 + **已有数据 provenance 分类守卫**（若已有 `sources/property_reports/analysis_metrics/risk_findings` 行但缺 `data_class/report_status` 列则抛错）`:6-90`；Storage client policy 检查 `:82-90`；`sources` 加列 + not null + 各类非空/url check `:94-…`；重建 `policy_documents_no_overlapping_versions` `:290-309`；`reject_analysis_metric_mutation()` `:311-324`；`enforce_published_source_rights()` `:326-361` + `revoke` `:363-364` + 3 触发器 `:366-381`；RLS/grant/policy 段 `~455-604`；索引 `:606-609` |
| `20260902000200_service_role_grant_portability.sql`（27 行）**repair** | 固定不同 CLI 版本下的 service_role 权限 | `grant all privileges on table` 22 张 application 表 `to service_role`（`:4-27`） |

### D. Intake 增补（2026-09-04）

| 文件 | 目的 | 关键 DDL |
|---|---|---|
| `20260904000100_intake_renovation_observations.sql`（49 行）**业务域** | 装修观测行喂免费预览 | `analysis_sessions` 加 `asset_type` check `('apartment','tower','detached_house','other')`（`:3-5`）；`renovation_observations`（`:7-34`，`room/component/condition/scope` 四个白名单 check，`unique(session_id,room,component)`）；索引 `:36-37`；RLS enable `:39`；`revoke` `:41`；触发器 `:43-46`；`free_previews` 加 `renovation_estimate jsonb`（`:48-49`） |

### E. V1 业务域（2026-09-05，**字段冻结集**）

> 冻结依据：`docs/superpowers/plans/2026-09-05-b2-v1-business-migrations.md:1,3,6`（"字段冻结，已评审入库；任何字段变动只允许新增 forward migration"）。

| 文件 | 目的 | 关键 DDL |
|---|---|---|
| `20260905000100_v1_organizations.sql`（199 行）**V1** | 机构 + 成员席位 | `organizations`（`:46-60`，`partner_status` check `('none','pending','certified','suspended')`）；RLS `:62`；`organization_members`（`:64-77`，`role` check `owner/member`、`status` check、unique `(organization_id,user_id)`）；索引 `:81-88`（**部分唯一索引** `uq_organization_members_active_owner` `:86-88`）；`grant all … to service_role` `:91`、`revoke` `:93`、`grant select` `:95`、**列级 `grant update (name)`** `:100`；policy `:102-141`；`enforce_organization_member_active_seat_cap()`（`:148-179`，SECURITY DEFINER，≤5 活跃席）+ 触发器 `:184-188`；`set_updated_at` 触发器 `:190-199`；**重跑守卫**（表已存在则抛错）`:40-42` |
| `20260905000200_v1_products_subscriptions.sql`（192 行）**V1** | 价格目录/客户/订阅 | `product_prices`（`:39-67`，`product_code` 3 值、`mode`、`currency` 6 值、`price_version`、`mode_matches_code` check、unique `(product_code,currency,price_version)`）；`billing_customers`（`:70-81`，`single_scope` check）；唯一索引 `:84-89`；`subscriptions`（`:92-128`，`single_scope`/`scope_matches_product`/`status` check、`stripe_subscription_unique`）；索引 `:132-135`；RLS enable `:138-140`；`revoke` `:142-145`；`grant select` `:151-153`；policy：生效价格 `:155-161`、自身订阅 `:163-175`；`grant all … service_role` `:178-181`；触发器 `:184-192` |
| `20260905000300_v1_usage_ledger.sql`（228 行）**V1** | 原子用量账本 | `usage_quotas`（`:38-71`，`scope_key` 正则 check `^(user|org):uuid$` `:50-52`、`period_key` YYYY-MM / YYYY-MM-DD 正则 `:53-56`、`usage_kind` 5 值、unique `(scope_key,usage_kind,period_key)`、容量上界 `consumed+reserved <= limit+100000` `:68-70`）；触发器 `:76-79`；`usage_events`（`:84-124`，append-only、`operation` check `consume/reserve/commit/release/reversal`、`reversal_target` check `:120-123`）；**幂等指纹唯一索引** `uq_usage_events_fingerprint`（`:128-130`）；`prevent_usage_event_mutation()`（`:136-153`，禁 update/delete）；`usage_idempotency`（`:159-182`，双唯一约束 `:176-181`）；RLS enable `:187-189`；`revoke` `:191-192`；`grant select` `:196`；`grant all … service_role` `:198-199`；`users can read own usage quotas/events` policy（`:201-225`，用 `starts_with(scope_key,'user:'||uid)` 或 org 成员） |
| `20260905000400_v1_service_tasks_contacts.sql`（574 行）**V1** | 服务任务池 + 联系授权 | `service_tasks`（`:86-122`，`status` 10 状态 check `:115-120`、`public_description` 10–2000 字符 check）；索引 `:131-135`；`task_applications`（`:140-155`，unique `(task_id,organization_id)`）+ **单匹配部分唯一索引** `:167-169` + 索引 `:173-176`；`task_status_history`（`:181-210`，append-only，`from<>to` check `:207-209`）；`contact_consents`（`:226-…`，unique `(task_id)`，仅双向授权后存邮箱）；SECURITY DEFINER 助手 `is_active_org_member`（`:357-371`）、`is_org_owner_or_assigned_member`（`:375-393`）、`is_task_creator`（`:396-409`）、`is_matched_task_b_participant`（`:413-428`）+ `revoke/grant execute` `:430-440`；SELECT-only policy `:450-500`；**唯一邮箱披露通道** `get_task_contact_email(uuid)`（`:513-568`，双向 granted + 30 天窗口内才返回对方邮箱）+ `revoke/grant` `:570-574` |
| `20260905000500_v1_finance_admin_audit.sql`（250 行）**V1** | 支付/退款/webhook/后台角色/审计 | `payment_orders`（`:35-66`，`single_scope` check、`status` check、`provider in ('stripe')`、`paid_at` 状态 check）；`refunds`（`:72-96`，`reason` 6 值、`status` check）；索引 `:98`；`payment_events`（`:105-118`，**只存 `payload_sha256`**，`provider_event_id` unique）；`internal_role_assignments`（`:123-138`，role 6 值含 `super_admin`，unique `(user_id,role)`）；`audit_events`（`:143-151`）+ 索引 `:153-156`；`audit_events_append_only()`（`:160-183`，update/delete/**truncate** 三重触发器）；`set_finance_updated_at()` `:186-200` + 触发器 `:197-205`；RLS enable `:209-213`；`revoke` `:215-221`；`grant all … service_role` `:223-229` |

### F. V1 增补 + 采集 + 定价（2026-09-05 之后的 forward-only）

| 文件 | 目的 | 关键 DDL |
|---|---|---|
| `20260905000600_member_status.sql`（113 行）**V1 增补A** | 会员 active/suspended 状态 | `user_profiles` 加 `status text not null default 'active'`（`:52-53`）、`user_profiles_status_allowed` check（`:55-57`）、列注释（`:59-62`）；**`revoke update on user_profiles from authenticated`**（`:71`）→ **列级 allowlist** `grant update (email,username,display_name,city,favorite_area,favorite_asset_type,bio)`（`:73-74`）；重写 `prevent_client_membership_change()` 纳入 `status`（`:82-108`）+ 触发器 `:110-113` |
| `20260905000601_collection_runs.sql`（90 行）**V1 采集** | 采集执行台账 | `collection_runs`（`:33-58`，`source_type` 5 值 check、`status` 5 值 check、`completed_at` 需 `started_at` check）；索引 `:62-65`；RLS enable `:69`；`revoke … from anon,authenticated`（`:71`）；`grant all … service_role`（`:73`）；表/列注释 `:75-91`（内部域） |
| `20260906000100_collection_sources.sql`（84 行）**采集/来源登记 P1.3** | 授权来源登记 | `collection_sources`（`:30-56`，**`source_key` 为主键**、`rights_confirmed boolean default false`、`robots_policy`/`rate_limit_note`/`retention_policy`、`cadence` check `daily/weekly/monthly/event`、`url_or_note` check）；触发器 `:58-60`（**未加 `drop if exists`**）；索引 `:64-65`；RLS enable `:67`；`revoke … from anon,authenticated`（`:69`）；`grant all … service_role`（`:71`）；注释 `:73-84`（`rights_confirmed=yes` 是 live 采集前置） |
| `20260911000100_report_purchase_subject.sql`（7 行）**定价/业务域** | 一次性购买的报告主体 | `payment_orders` 加 `subject_id text`（`:3-4`）；索引 `idx_payment_orders_owner_product_subject_status`（`:6-7`）；既有 order `subject_id` 保持 NULL、不解锁任何报告（`:1-2`） |
| `20260912000100_pricing_admin.sql`（64 行）**定价** | 后台定价目录（已登记于 schema-ownership.json） | `pricing_products`（`:4-10`，`checkout_mode` check）；`pricing_prices`（`:12-24`，`currency` 7 值含 `SGD`、`amount_minor > 0`、`price_version > 0`）；索引 `:26-27`；`pricing_regions`（`:29-35`）；`pricing_plans`（`:37-48`，`monthly_query_limit/monthly_report_quota/subscription_slots/export_rows_monthly`）；**DO 循环**统一 RLS enable + revoke + grant service_role（`:50-59`）；注释 `:61-64`（价格 append-only、plan `plan_version` 递增） |

---

## 2. 数据模型全景（文字版 ER）

### 2.1 用户 / 身份
- `user_profiles` — PK `user_id`（=`auth.users.id`，cascade）(`20260824000100:37-42`)。字段：`email, username, display_name, city, favorite_area, favorite_asset_type, bio`，服务端管理 `membership_tier`（default `free`）、`daily_query_limit`（default `3`）、`status`（default `active`，`20260905000600:52`）。
- `organizations` / `organization_members` — 机构画像 + 席位（`20260905000100:46-77`）。`organization_members.user_id` 是 org-scoped 数据的所有权边界；≤5 活跃席、单活跃 owner（`:86-88`、`:148-179`）。
- `product_events` — 归 `user_id`（`20260824000200:61-65`）。

### 2.2 查询与报告（legacy 区域报告域）
`queries`（`query_key` unique）→ 1:N `generation_jobs`（`query_id` cascade `20260824000100:20`）→ 1:1 `property_reports`（`uq_property_reports_query_id`，`20260824000300:9-10`）→ 1:N `data_sources`（`20260824000100:33`）。`query_field_options` 独立（`:14-18`），`property_reports` 通过 `source_id → sources` 关联 provenance（`20260824000600:27`）。

### 2.3 物业 / 私有项目域
`sources`（来源）→ `properties`（`source_id`，`20260824000200:20`）→ 1:1 三个明细表 `residential_details`/`new_build_details`/`commercial_investment_details`（PK 均为 `property_id`，cascade `:23-39`）→ 1:N `evidences`（`:40-44`）、`analysis_metrics`（`:45-49`）、`risk_findings`（`:50-54`）。`analysis_metrics`/`risk_findings` 可引用 `sources(id)`（`20260824000500:45,99`）。
Intake（2026-08-25）：`analysis_sessions`（`token_hash` unique）→ 1:N `project_inputs`（`:66-81`）、`project_field_evidence`（`:83-102`）、`project_fields`（`:104-123`，唯一 `(session_id,field_name)`，`selected_evidence_id` → `project_field_evidence`）、1:1 `free_previews`（`:125-134`）；`intake_rate_limits` 独立（`:136-143`）；`renovation_observations` → `analysis_sessions`（`20260904000100:7-34`），并可引用 `project_inputs`（`:17`）。

### 2.4 计费域
- `product_prices`（版本化目录，`20260905000200:39-67`）— `billing_customers`（个人或机构二选一，`:70-81`）— `subscriptions`（快照 product/price/currency/amount，镜像 Stripe subscription，`:92-128`）。
- `payment_orders`（一次性购买，`20260905000500:35-66`）→ 1:N `refunds`（`:72-96`）；`subject_id` 标识报告主体（`20260911000100:3`）。
- `payment_events` — webhook 幂等账本（只存 payload sha256，`20260905000500:105-118`）。
- 定价后台目录：`pricing_products`/`pricing_prices`/`pricing_regions`/`pricing_plans`（`20260912000100:4-48`）。

### 2.5 用量账本
`usage_quotas`（每 (scope,kind,period) 一行计数器，`20260905000300:38-71`）、`usage_events`（append-only 事实 + 幂等指纹，`:84-130`）、`usage_idempotency`（键/指纹登记，`:159-182`）。`scope_key` = `user:<uuid>` 或 `org:<uuid>`。

### 2.6 采集域
`collection_sources`（来源登记，PK `source_key`，`20260906000100:30-56`）→ `collection_runs`（每次执行一行，`source_key` 对齐，`20260905000601:33-58`）。

### 2.7 服务任务 / 联系授权
`service_tasks`（公开列表，禁 PII，`20260905000400:86-122`）→ `task_applications`（单匹配部分唯一索引，`:167-169`）、`task_status_history`（append-only，`:181-210`）、`contact_consents`（1:1 `task_id`，只在双方 granted 后存邮箱，`:226-`）。

### 2.8 隐私 / 审计
`internal_role_assignments`（后台角色，`:123-138`）、`audit_events`（append-only，`:143-183`）；`policy_documents`（":55-60`）；来源授权登记 `collection_sources`。

---

## 3. RLS 与权限模型

- **启用范围**：README 定稿「22 张 application 表启用 RLS」，`anon` 仅有 active `query_field_options` SELECT（`supabase/migrations/README.md:63-65`；`20260829000100:98,116-118`）。V1 后新增表也全部 enable（org/products/usage/tasks/finance/collection/pricing），B2 计划记录「表 22→39，39/39 开 RLS」（`docs/superpowers/plans/2026-09-05-b2-v1-business-migrations.md:32`）。
- **`is_service_role()`**：`current_user in ('postgres','service_role','supabase_admin')` 或 `request.jwt.claim.role in ('service_role','supabase_admin')`（`20260824000300:12-15`，`20260827000500:36-45` 重定义）。
- **服务端管理字段触发器保护**：
  - `prevent_client_ownership_change()` — 非 service_role 不能改 `owner_user_id`（`20260824000300:16-24`）。
  - `prevent_client_membership_change()` — 非 service_role 不能设/改 `membership_tier`、`daily_query_limit`（`20260824000300:87-95`；`20260827000500:163-183` 重定义；`20260905000600:82-108` 扩展纳入 `status`）。**客户端不可写字段：`membership_tier`、`daily_query_limit`、`status`**。
  - `prevent_intake_identity_change()` — 非 service_role 不能改 intake 的 `owner_user_id/property_id/token_hash/expires_at/converted_at`，且 purpose 锁定后不能改（`20260825000400:194-227`）。
- **策略要点**：所有 owner 读取用 `owner_user_id = auth.uid()` 或经 `queries.query_id` 间接判定（`20260829000100:120-244`）；跨表用 `auth.uid()`（早期文件裸写，29000100 用 `(select auth.uid())` 包裹）。
- **列级权限**：
  - `organizations`：authenticated 仅 `grant update (name)`（`20260905000100:100`）。
  - `user_profiles`：2026-09-05 起 `revoke update`（表级）→ `grant update (7 个偏好列)`（`20260905000600:71-74`）。
  - `contact_consents`：邮箱列无 SELECT 权限，仅经 `get_task_contact_email()` SECURITY DEFINER 通道（`20260905000400:28-33,513-568`）。
- **内部域（service_role only，anon/authenticated 零权限、无 policy）**：`payment_orders/refunds/payment_events/internal_role_assignments/audit_events`（`20260905000500:207-229`）、`collection_runs`（`20260905000601:67-73`）、`collection_sources`（`20260906000100:67-71`）、`pricing_*`（`20260912000100:50-59`）、`renovation_observations`（`20260904000100:41`）、`usage_idempotency`（`20260905000300:227-228`）。
- **新表 RLS 读范围**：`usage_quotas/events` 按 `scope_key` 前缀 + org 成员判定（`20260905000300:201-225`）；`subscriptions` 按 `user_id` 或活跃 org 成员（`20260905000200:163-175`）。
- **SECURITY DEFINER 成员助手**（`20260905000400:357-428`）防 RLS 递归、`search_path` 固定、anon 不可执行。
- **约束新增**：owner/membership 不从 email 推导（`20260824000300:1-2`）。

---

## 4. 数据文件

### 4.1 内容库 `data/content_library.json`
- 结构：**数组，3 条记录**（slug `jphouse_auto_b6cc4820b3`/`jphouse_auto_1c84e0aad9`/`jphouse_auto_9feb3b69b1`）。
- 记录字段（`data/content_library.json:1-17,77-81`）：`id, slug, template_name, title, publish_month, generated_at, regions[], asset_type, layouts[], status, summary{title,line,note}, rental[], sale[], markdown, hashtags[], data_sources[], images, search_text`。
- `rental`/`sale` 元素均为**展示字符串**（`layout/area/amount_jpy/amount_rmb/unit_jpy/unit_rmb`，如 `"约3,853万日元"`），非数值（`data/content_library.json:24-74`）——与 AGENTS.md「禁止解析展示字符串做分析」一致。
- `data_sources` 每项 `{name,url,usage}`；含占位 `https://suumo.jp/`、`https://tochidai.info/`（`data/content_library.json:78-81`，标注"后续真实采集"）。
- 与 `web/content-library.json` 语义重复（AGENTS.md 提及二者需同源同步）。

### 4.2 授权聚合数据 `data/collected_licensed/*.json`
- 3 个家族：`jphouse_23ku_sources.json`、`jphouse_osaka_wards_sources.json`、`jphouse_yokohama_wards_sources.json`。
- 由 `scripts/build_licensed_aggregate.py` 从 `data/collected/<family>_sources.json` 生成（`:89-99`），规则版本 `licensed-aggregate-v1`（`:14`）。
- **白名单保留字段**：`ward, config, output, sale.{layout_price_man_yen, unit_man_yen_per_sqm, updated}`（`:20-22,109-110`）；其余（如 `rents`、`suumo_updated`→改名 `source_update`）被过滤。
- **`_filtered` 元数据**：`{"fields":[被剔除字段...], "reason":"unlicensed_source", "rules_version":"licensed-aggregate-v1"}`（`:76-80`）；输出顶层为 `{collected:[...], _filtered:{...}, generated_at}`（`:81-85`）。
- 实测 `data/collected_licensed/jphouse_23ku_sources.json`：`collected` 23 条、`_filtered.fields = ['rents','source_update']`、`generated_at=2026-08-23T02:59:42Z`；每条已无 `rents`。
- 对照 `data/collected/jphouse_23ku_sources.json`（原始，list[23]）：字段 `ward, config, rents, suumo_updated, sale`（含被过滤的 `rents`/`suumo_updated`）。

### 4.3 市区町村码表 `data/municipality_codes.json`
- 来源：`data/source/jis-codes-2024-01-01.xlsx`（JIS 官方码表），由 `scripts/build_municipality_codes.py` 生成（`:15-16`）。
- 结构：**对象**，键为 **5 位码**（取 6 位团体代码前 5 位，`:48`），值 `{"prefecture","city"}`（`:48`）。**实测 1747 条**，示例 `"01100":{"prefecture":"北海道","city":"札幌市"}`。
- 解析规则：跳过表头 `団体コード`、6 位数字校验（`:40-48`）。

### 4.4 来源登记 `data/source_registry.json`
- `registry_version: "source-registry-v1"`，`sources[]`（`:1-3`）。
- 条目字段：`source_id, name, source_type, canonical_url, permission_status, rights_evidence, terms_reviewed_on, permitted_use, owner, update_frequency, parser_version`（`:4-16`）。
- 现有 2 条：`placeholder-authorized-records`（`permission_status:"pending"`、`permitted_use:"none"`，`:5-16`）与 `local-synthetic-fixture`（test-only，`:17-29`）——**无任何已确认授权的真实来源**。

### 4.5 `backend/data/market_snapshots/*.json`
- 3 个家族文件，**与 `data/collected/` 原始聚合同结构（未过滤）**：list[23]，字段含 `rents`、`suumo_updated`。
- **未确认**：该目录与 `data/collected/` 的用途分工（是否 worker 运行时读取）未在代码/文档中确认。

### 4.6 其他
- `data/input/`：`acquisition_cost_rules.json`、`fx_rates.json`、`minato_property_synthetic.csv`、`minato_tower_sample.csv`。
- `configs/jphouse_23ku|osaka_wards|yokohama_wards/<ward>.json`：报告模板（`template_name/slug/title/publish_month/cover/intro/explain/exchange_rate_note/sections.rental|sale.rows[]`，`configs/jphouse_23ku/chiyoda.json:1-41`）；`configs/jphouse_worker/jphouse_auto_*.json`（worker 输入，3 个）。
- 采集原始运行样本 `data/collected/jphouse_runs/`（`jphouse_osaka_wards/higashinari.json`、`jphouse_yokohama_wards/asahi.json`，权限 `-rw-------`）。

---

## 5. 字段冻结红线

- **红线出处**：`docs/superpowers/plans/2026-09-05-b2-v1-business-migrations.md:6`「数据字段已冻结——本组迁移落库后，任何字段变动只允许新增 forward migration。浏览器/前端一律不得写服务端管理字段」；`:20-29` 冻结关键口径（金额 `amount_minor`+`currency(3)`、产品代码与价格、scope、用量 UTC+8 幂等、任务状态机、隐私授权/30 天/3 年、审计字段禁令、RLS 契约）。
- **只允许 forward migration 的约束体现**：
  - `supabase/migrations/README.md:44-47`「已应用 migration 文件不可修改；任何 remote 修复只能新增更晚的 forward migration」。
  - `docs/architecture/schema-ownership.json:86-92` `prohibited_operations`：`edit_applied_migration`、`delete_restore_package`、`apply_live_database_change_without_explicit_approval`、`linked_migration_repair_or_push_without_approval`、`staging_or_production_reset_without_approval`。
  - `supabase/migrations/README.md:90-100` Live gate：禁 migration repair / staging reset / production reset / 未批准 linked push / live SQL；新 schema 只加到本目录，不在应用启动初始化。
  - 仲裁记录零字段改动、0904 migration 保持 forward-only（`docs/superpowers/plans/2026-09-04-divergence-arbitration.md:110-112`）。
  - BOT 编排把「用户已冻结字段」列为红线，禁止反复验证字段（`docs/superpowers/plans/2026-09-04-hermes-bot-orchestration.md:106-107,218`）。
- **已冻结的关键字段**（V1 域）：`product_prices.amount_minor/currency/price_version/product_code`、`subscriptions` 快照字段、`usage_*` 的 `scope_key/period_key/usage_kind/operation`、`service_tasks.status` 状态机、`contact_consents` 授权/30 天窗口、`payment_orders`（含 `subject_id`）、`pricing_*`。
- **浏览器不可写字段**（服务端管理）：`membership_tier`、`daily_query_limit`、`user_profiles.status`、各表 `owner_user_id`、intake 身份字段、退款/价格/订阅状态。

---

## 6. 坑 / 注意事项

1. **审计清单与磁盘一致**：迁移目录与 `docs/architecture/schema-ownership.json:6-30` 均为 **24 个** SQL；已登记 `20260911000100_report_purchase_subject.sql` 与 `20260912000100_pricing_admin.sql`。仍不得据此推断这些 migration 已执行。
2. **迁移编号存在缺口**：`…000700` 直接跳 `20260825000400`；`20260828000100`→`20260829000100`→`20260902000100` 亦不连续。README 明确「三条原有 ledger ID 保持不变，没有伪造或 repair 缺失的历史 ID」（`supabase/migrations/README.md:19-24`）。因此 fresh-install 顺序（README:28-42）与目录数字顺序一致，但**不可假设每个时间戳都有文件**。
3. **同一逻辑被多次重写**（读代码勿只读首个文件）：
   - policy 版本防重叠：`20260824000400:5-17` 触发器 → 被 `20260824000500:129-130` 删除 → 改为 GiST 排除约束 `20260824000500:127-158`（staging 协调再建于 `20260902000100:290-309`）。
   - 指标历史保护：`20260824000400:18-25` `prevent_published_metric_update` → `20260824000500:160-171` `reject_analysis_metric_mutation`。
   - `enforce_published_source_rights()`：`20260824000600:48-80`（跳过 synthetic+user_submitted）→ `20260824000700:53-85` 重写（**只跳过 synthetic**）→ 又出现在 `20260902000100:326-361`。
4. **`auth.uid()` 写法不一致**：`20260827000500:126` 等用裸 `auth.uid()`，`20260829000100:122` 起用 `(select auth.uid())`（性能/语义优化）。RLS 审查时勿混淆。
5. **`user_profiles` UPDATE 权限演进**：表级 `grant select,insert,update`（`20260824000300:69`、`20260827000500:122`、`20260829000100:114`）在 `20260905000600:71-74` 被改为列级 allowlist。文件注释明确：PostgreSQL 17 下裸 `revoke update (status)` 无法移除表级 grant 的能力（`20260905000600:7-16`）。
6. **重复加列**：`owner_user_id` 在 `20260824000300:3-5`、`20260827000500:23-30` 两处加（`if not exists`，幂等）；`sources` provenance 列在 `000500`/`000600`/`20260902000100` 三处加。
7. **触发器无 `drop if exists`**：`20260906000100:58` `create trigger set_collection_sources_updated_at` 未先 drop（靠 `:25-27` 的 `to_regclass` 守卫防重跑）。
8. **`asset_type` 取值不一致**：`analysis_sessions.asset_type` 用 `('apartment','tower','detached_house','other')`（`20260904000100:5`），而 `analysis_metrics.asset_type` 用 `('condo','tower','detached_house','other')`（`20260824000500:72-73`）——`apartment` vs `condo` 差异，跨表聚合需注意。
9. **staging 只应用了 `20260902000100`**（README:19-24）；`20260904000100`（0904 wip）曾保持 pending（`docs/superpowers/plans/2026-09-05-b2-v1-business-migrations.md:32,35`：应用时临时移出 `0904` 再 `db push` V1×5）。**production 从未连接/修改/验证**（`schema-ownership-audit.md:16-17,10`）。
10. **license 现实**：`data/source_registry.json` 无已授权真实来源；SUUMO 审查结论为**不通过**（商业用途需 Recruit 书面许可，`docs/superpowers/plans/2026-09-07-source-authorization-review.md:8-15`）→ 当前**不可 live 采集/展示**。`collection_sources.rights_confirmed` 默认 `false`，作为调度前置闸门（`20260906000100:36,78-80`）。
11. **`backend/sql/`、旧 restore 包、schema dump 不是 migration history**（`supabase/migrations/README.md:97-98`；`schema-ownership-audit.md:53-67`）；`INIT_SCHEMA=true` 只在 local/dev/test 生效，staging 为 `INIT_SCHEMA=false`（`schema-ownership-audit.md:14,80`）。
12. **`20260912000100_pricing_admin` 使用 `SGD` 币种**（`20260912000100:15,31`），而 V1 冻结枚举为 `CNY/HKD/TWD/MOP/JPY/USD`（`20260905000200:53-55`）——两套币种集合不同，跨表校验需注意。
13. **快照清理**：嵌入 `backend/data/market_snapshots/` 已移除 `rents`/`suumo_updated`；测试夹具和采集脚本仍保留兼容/解析证据，不能把它们当作已授权发布数据。

---

## 交付说明
- **只读完成**：仅读取仓库文件与运行只读 `ls/python3` 统计，**未创建或修改任何文件**。
- 覆盖：24 个迁移 SQL、`supabase/migrations/README.md`、`docs/architecture/schema-ownership.{md,json}`、`data/**`、`configs/**`、`backend/data/**`、3 个脚本、B2 冻结计划与来源授权审查。
- 未确认项已在上文标注（§4.5 market_snapshots 用途、§6.1 审计脚本行为、staging 实际列清单未连库核对）。


---


# 第 5 部分 · 采集管道 + 部署运维


# 采集管道 + 部署运维 技术说明(只读复核)

> 范围:ZOUSEEKING/ZOUBEACON(JPPropDIs)。以下每条结论附 `文件:行号`;代码/文档未证实的写「未确认」。

---

## 1. 采集架构

三层分离:**scheduler(feeder,只投料)** → **worker(executor,认领并执行)** → **runner(按 family 真实采集)**。scheduler 明确「从不运行 runner、从不访问活网站」(`backend/app/collection/scheduler.py:6-8`)。

### 1.1 可调度源与族(family)
- 调度源 = 三个 config 目录下的每个 `<stem>.json`:`configs/jphouse_23ku`、`configs/jphouse_osaka_wards`、`configs/jphouse_yokohama_wards`;prefix→目录映射**派生自** runner 注册表的 `FAMILIES`,stem 由目录枚举(不硬编码);`fixture` 前缀不可调度(`scheduler.py:10-18, 114-125`;`jphouse_runners.py:90-110`)。
- 实际文件数:23ku=23、osaka_wards=23、yokohama_wards=18。
- `discover_sources()`:某 family 的 config 目录缺失即抛 `missing_config_dir`(不静默空投);`prefix` 可过滤单族(`scheduler.py:161-195`)。

### 1.2 调度决策(due)与投料
- 常量:周节奏 `FAMILY_CADENCE = 7d`(`scheduler.py:73`);投料 `source_type='aggregate_authorized'`(`scheduler.py:78`);推进窗口的终态 `WINDOW_ADVANCING={succeeded,failed}`(`scheduler.py:83`);在途 `INFLIGHT={queued,running}`(`scheduler.py:86`)。`cancelled` 不算尝试,故仅有取消记录的源仍视为 due(`scheduler.py:80-83`)。
- `decide(source, state, now)` 纯函数,判定顺序:① `has_inflight` → `skipped(in_flight)`;② 无终态历史 → `queued(no_history)`;③ `now-last_terminal_at >= cadence` → `queued(due)`;否则 `due_later(within_cadence)`(`scheduler.py:224-256`)。`now` 为注入的时钟接缝,必须 tz-aware(`scheduler.py:151-158`)。
- `fetch_state()`:单条分组 SELECT,`max(created_at) filter (where status=any(WINDOW_ADVANCING))` + `bool_or(status=any(INFLIGHT))`,按 `source_key` 分组;无行的 key 视为无历史/无在途(`scheduler.py:284-321`)。
- `feed_due()`:**一个事务**内先读状态再插 `queued` 行;顺序幂等——重跑 scheduler 会因为看到刚落库的 `queued` 而在途跳过(`scheduler.py:341-367`)。`plan_due()` 为只读 dry-run(`scheduler.py:324-338`)。
- CLI:`scripts/collection_scheduler.py`,参数 `--dry-run / --family / --now`,输出 JSONL(`scripts/collection_scheduler.py:47-70, 112-127`)。compose 里以 `while true; …; sleep 3600` 常驻(每小时一次投料)。

### 1.3 任务队列 / 认领(claim)
- 队列表 `public.collection_runs`:`id/source_key/source_type/status/rows_collected/snapshot_hash char(64)/error_message/operator_user_id/started_at/completed_at/created_at`;状态约束 5 态 `queued|running|succeeded|failed|cancelled`,source_type 5 值(`supabase/migrations/20260905000601_collection_runs.sql:33-58`);索引 `(status,created_at desc)`、`(source_key,created_at desc)`(`同文件:62-65`);RLS 内部域,`revoke … from anon, authenticated` + `grant … to service_role`(`同文件:67-73`)。
- `claim_next()`:单事务 `select id,source_key,source_type from public.collection_runs where status='queued' order by created_at asc, id asc limit 1 for update skip locked`,随后 `update … set status='running', started_at=now()`(`backend/app/collection/worker.py:208-237`)。**并发 worker 不会双认领**:后到者要么阻塞到前者提交后不再看到 `queued`,要么直接 skip locked 行。
- 注:`claim_next` 的 `for update skip locked` 是行锁语义,不是 `FOR UPDATE SKIP LOCKED` 显式 SQL 文本的独占队列,但行为等价。

### 1.4 worker 执行
- `resolve_runner(source_key, registry)`:按**最长前缀**匹配;无匹配抛 `NoRunnerError(code='no_runner')`,产生显式 failed 而非 worker 崩溃(`worker.py:171-200`)。注册表含内置 `fixture` + 三个真实 jphouse 族(`worker.py:160-168`)。
- `run_once(pool)`:认领 1 行 → 解析 runner → 执行 → `_normalize_outcome` 校验 → 写终态 + 审计(`worker.py:342-435`)。
  - `_normalize_outcome`:必须返回 `CollectionOutcome`;`rows` 强制 int 且 ≥0;`snapshot_hash` 必须 64 位小写 hex,否则按 runner 失败处理(防止非法值卡死 run 行)(`worker.py:245-276`)。
  - `_write_terminal_state`:一个事务内 `update … where id=$1 and status='running'`(带守卫)+ 插 `audit_events`;若行已不是 `running`(被操作员取消),写为 no-op 返回 False(`worker.py:293-335`)。
  - 成功 → `succeeded` + `rows_collected` + `snapshot_hash` + `completed_at`,审计 `admin.collection.run_succeeded`;失败 → `failed` + `error_message`(截断 2000 字)+ `completed_at`,审计 `admin.collection.run_failed`;未捕获异常也转 `failed`(run 永不悬在 `running`)(`worker.py:384-435`)。`ERROR_MESSAGE_LIMIT=2000`(`worker.py:73`);审计 summary 只带 `code`,不含异常栈(`worker.py:418-423`)。取消竞态时报告 `status='cancelled'`(`worker.py:398-400, 425-427`)。
- CLI:`scripts/collection_worker.py`,默认单轮,`--loop N --interval S` 轮询;输出 JSONL(无 PII/异常栈)(`scripts/collection_worker.py:31-49, 52-92`)。compose 以 `--loop 60 --interval 10` 运行。

### 1.5 runner 的输入/输出、快照与 sha256
`backend/app/collection/jphouse_runners.py`:
- 协议:`source_key = "<prefix>/<config-stem>"`;解析 `configs/<family>/<stem>.json`;执行一次**数据读入**;写 per-source 快照到 `data/collected/jphouse_runs/<prefix>/<stem>.json`(原子替换);返回 `rows_collected` + 小写 hex sha256(`jphouse_runners.py:10-22, 331-392`)。
- 默认 collector `collect_local_readin`:从 `data/collected_licensed/<family>_sources.json` 读已授权数值快照,**只从数值字段重建行**(绝不解析展示字符串);可用环境变量 `LICENSED_AGGREGATE_DIR` 覆盖目录(`jphouse_runners.py:26-31, 182-238`)。匹配条目按 `entry.source_key` 或 `config` 文件名(`jphouse_runners.py:215-232`)。
- 行构造 `_rows_from_ward_record`:从 `record.rents["1LDK"/"2LDK"/"3LDK"]` 产出 `metric=rent,unit=man_yen_per_month`;从 `record.sale.layout_price_man_yen[...]` 产出 `metric=sale_price,unit=man_yen`;缺数值的 layout 跳过(呼应脚本「暂无样本」不臆造值)(`jphouse_runners.py:133-170`)。`LAYOUTS=(1LDK,2LDK,3LDK)`(`jphouse_runners.py:74`)。
- 快照结构 `_snapshot_dict`:`source_key/config/slug/publish_month/source_urls/rows/rows_collected/parser_version/snapshot_format/collected_at`,并合并 meta(`sale_updated`)(`jphouse_runners.py:262-287`)。
- 快照原子写:临时文件 + `os.replace`(`jphouse_runners.py:290-308`)。
- **sha256 规范**:`canonical_snapshot_payload` 排除每次运行的 `collected_at`,键排序、紧凑分隔符 → 同样内容得到相同指纹(可重放/幂等)(`jphouse_runners.py:241-254`);hash 在 `make_runner` 内 `hashlib.sha256(_canonical_payload(snapshot)).hexdigest()`(`jphouse_runners.py:389`)。`PARSER_VERSION='jphouse-local-readin-v1'`、`SNAPSHOT_FORMAT='jphouse-run-v1'`(`jphouse_runners.py:70-71`)。
- 真实 live 抓取**未接线**:SUUMO/Tochidai 的 fetch+parse 需先完成授权审查与 stored fixtures(`jphouse_runners.py:33-38`)。

### 1.6 失败码
runner 抛 `worker.CollectionRunError` 带稳定 `code`(`jphouse_runners.py:40-46`):
`bad_source_key`(source_key 非法,`:311-328`)、`config_missing`(`:359-363`)、`config_invalid`(`:364-377`)、`aggregate_missing`(`:200-205`)、`aggregate_invalid`(`:206-213`)、`aggregate_entry_missing`(`:228-232`)。worker 层:`no_runner`(`worker.py:118-121`)、`runner_error`(未捕获异常,`worker.py:381-382`)。源不可达时首现 `aggregate_missing`(该源在本机未生成 `data/collected_licensed/*` 即触发)。

### 1.7 sweeper(质检/看门狗)
`backend/app/collection/sweeper.py`:
- `recover_stale_runs`:把 `running` 且 `started_at<=now-6h` 的僵死行翻 `failed`(error_message 说明被 sweep,非 runner 栈)+ `completed_at` + 审计 `admin.collection.run_swept`,单事务且 `for update skip locked`;`where status='running'` 守卫(`sweeper.py:12-28, 261-357`)。`DEFAULT_STALE_AFTER=6h`(`:76`)、`DEFAULT_SWEEP_LIMIT=50`(`:79`)。
- `verify_snapshot_hashes`:只读,取最近 `DEFAULT_VERIFY_LIMIT=200` 条有 `snapshot_hash` 的 succeeded `jphouse_*` run,重算规范指纹并比对;**排除 `collected_at`**,校验行数;判定码 `hash_ok/hash_mismatch/rows_mismatch/file_missing/file_unreadable`(`sweeper.py:30-38, 93-98, 360-409`)。
- CLI:`scripts/collection_sweep.py`,`--recover-only/--verify-only/--stale-after/--limit/--dry-run/--now/--repo-root`;发现异常(任一僵死行或任一 QA 不通过)退出码 1 供 cron 告警(`scripts/collection_sweep.py:56-101, 129-155`)。

---

## 2. 授权与合规

### 2.1 source_registry 授权状态机
表 `public.collection_sources`(migration `20260906000100_collection_sources.sql`):
- 字段:`source_key PK`、`source_type`、`display_name`、`source_url`、`cadence`(枚举 `daily|weekly|monthly|event`)、**`rights_confirmed boolean default false`**、`robots_policy`、`rate_limit_note`、`retention_policy`、`enabled default true`、`notes`;约束 `source_url is not null or notes is not null`(`:30-56`);`updated_at` 触发器(`:58-60`);RLS 内部域,`revoke from anon, authenticated` + `grant to service_role`(`:67-71`)。注释明确 `rights_confirmed=yes` 是 live 采集前提,URL 本身不等于许可(`:78-80`)。
- 管理 API:`GET /api/admin/collection/sources`(member_ops/data_ops/super_admin)、`POST` upsert(data_ops/super_admin,审计 `admin.collection.source_upserted`);仅登记,**不触发也不授权 live 采集**(`backend/app/admin/routes.py:26-27, 439-469`)。

**重要限制(代码事实)**:当前 scheduler **不读取** `collection_sources.rights_confirmed/enabled` 作为投料门禁——`discover_sources` 纯按 config 目录枚举(`scheduler.py:161-195`)。因此「授权状态机」目前是**登记表 + 人工 flag**,尚未成为调度硬门禁(migration 注释也仅写「a later scheduler unit may read it」,`20260906000100_collection_sources.sql:8-11, 82-84`)。

### 2.2 licensed-only 聚合的生成逻辑
`scripts/build_licensed_aggregate.py`(rules_version `licensed-aggregate-v1`,`:14`):
- 白名单:顶层仅 `{count, failed_count, failed, collected}`(`:20`);记录级仅 `{ward, config, output, sale}`(`:21`);sale 级仅 `{layout_price_man_yen, unit_man_yen_per_sqm, updated}`(`:22`)。
- 其余一切字段被剔除并计入 `_filtered.fields`,reason `unlicensed_source`(`:25-44, 60-86`)。记录中非白名单字段 `suumo_updated` 归一为 `source_update`(`:29`)。
- 输入 `data/collected/<family>_sources.json` → 输出 `data/collected_licensed/<family>_sources.json`(`:89-99`)。CLI 打印 kept/filtered 字段(`:102-112`)。
- **实测过滤结果**(本地文件):`data/collected_licensed/*` 顶层为 `{collected,_filtered,generated_at}`;记录键仅 `ward,config,output,sale`(sale 键 = `layout_price_man_yen,unit_man_yen_per_sqm,updated`);`rents` 与 `suumo_updated` **已被剔除**。
- 即因未授权被过滤的字段:`rents`(租金相场)、`suumo_updated`(→`source_update`)、以及任何 `sale.*` 额外键;保留:ward、config、output(存在时)、sale.layout_price_man_yen、sale.unit_man_yen_per_sqm、sale.updated。

### 2.3 产出中不得出现的来源
- **SUUMO(Recruit)**:授权审查结论 ❌ 不通过——利用規約 Article 3(7) 商业用途需 Recruit 许可、Article 3(2) 版权/知识产权禁令;小象为收费商业产品 → 不可 live 采集/展示(`docs/superpowers/plans/2026-09-07-source-authorization-review.md:8-15`)。
- **tochidai.info**:民间镜像站(非国交省官方),同属需站方许可;建议从 configs `data_sources` 摘除或改官方 URL(`同文件:19-21, 43`)。
- **推荐替代**:国土交通省 土地総合情報システム(政府开放数据,可加工再利用,需出所明記),但 `land.mlit.go.jp` 国内不可达 → 采集执行节点必须在海外/日本(`同文件:22-37`)。AGENTS 红线:`rights_confirmed=yes` 前置、禁止 stealth/CAPTCHA 绕过/代理轮换(`AGENTS.md:64`)。
- **⚠ 未彻底清除的证据**:config 生成脚本仍把 SUUMO/Tochidai URL 写入 `data_sources`(`scripts/build_jphouse_23ku.py:207-218`;osaka/yokohama 同构),而 runner 会把 config 的 `data_sources[].url` 复制进快照 `source_urls`(`jphouse_runners.py:270-279`)。因此**快照仍会内嵌未授权的 SUUMO URL**,仅数值字段被 licensed 聚合过滤。

---

## 3. 脚本清单

| 脚本 | 用途 | 输入 → 输出 | 调用者 |
|---|---|---|---|
| `scripts/build_jphouse_23ku.py` | 抓 SUUMO 租金 + Tochidai 成交,生成东京23区 configs | 活网 SUUMO/Tochidai → `configs/jphouse_23ku/<ward>.json`、`data/collected/jphouse_23ku_sources.json` | 人工;`--publish-month/--limit`(`:222-245`) |
| `scripts/build_jphouse_osaka_wards.py` | 同上,大阪市区(描述称排除中央区) | 活网 → `configs/jphouse_osaka_wards/`、`data/collected/jphouse_osaka_wards_sources.json`、`data/output/jphouse_osaka_wards/…` | 人工(`:168-219`) |
| `scripts/build_jphouse_yokohama_wards.py` | 同上,横滨市区 | 活网 → `configs/jphouse_yokohama_wards/`、`data/collected/jphouse_yokohama_wards_sources.json` | 人工(`:163-214`) |
| `scripts/build_licensed_aggregate.py` | 只保留授权字段生成聚合快照 | `data/collected/*` → `data/collected_licensed/*`,打印 filtered 字段 | 人工(采集前/合规节点) |
| `scripts/collection_scheduler.py` | 投料:把 due 源入队 | DB `collection_runs` → JSONL 决策 | 定时(compose `scheduler` 每小时) |
| `scripts/collection_worker.py` | 认领并执行 1/N 轮 | DB `collection_runs` → JSONL 结果 | 定时(compose `worker` loop 60×10s) |
| `scripts/collection_sweep.py` | 僵死恢复 + 快照 hash QA | DB + 磁盘快照 → JSONL,异常退 1 | 定时/cron 告警(未见于 compose) |
| `scripts/run_jphouse_worker.py` | 旧 Supabase `generation_jobs` 本地生成 worker | Supabase 队列 → `configs/jphouse_worker/`、`data/output/…`、`web/…`、`property_reports` | 人工 **break-glass**:需 `ENABLE_FROZEN_JPHOUSE_WORKER=true`(`:316`) |
| `scripts/generate_xhs_package.py` | 由 JSON 模板生成小红书图包 + 内容库 | config json → `data/output/<slug>/`(封面/租赁/买卖 PNG、`data_detail.md`)、`data/content_library.json`、`web/content-library.json`、`web/library/<slug>/images/` | 被 3 个 build 脚本 + worker 内部 `generate()` 调用;亦可 CLI(`:294-299`) |
| `scripts/render_social_cards.py` | 特定 minato 报告社媒卡(数据硬编码) | 无外部输入 → `data/output/minato_tower_report/images/*.png` | 人工;无 CLI(`:7-12`) |
| `scripts/create_report_sample_pdf.py` | 生成**合成** 11 段报告 PDF 样稿 | 无 → `output/pdf/zoubeacon-property-analysis-sample-v2.pdf` | 人工(`:889-904`) |
| `scripts/seed_pricing_catalog.py` | 幂等 seed 定价目录 | `STRIPE_PRICE_IDS` env → `pricing_products/regions/plans/prices` | 部署后人工(`:35-55`) |
| `scripts/build_municipality_codes.py` | 由官方 XLSX 生成 JIS 市町村字典 | `data/source/jis-codes-2024-01-01.xlsx` → `data/municipality_codes.json` | 人工 |
| `scripts/build_japan_field_options.mjs` | 由 GitHub 公开 gov-code 生成字段选项 | nojimage/local-gov-code-jp JSON → 字段选项 | 人工(Node) |
| `scripts/sync_content_library_to_supabase.py` | 本地内容库同步到 Supabase | `web/content-library.json` → Supabase(需 service_role) | 人工 |
| `scripts/inspect_schema_metadata.py` | 只读导出 staging schema 清单 | 活 DB → CSV(columns/constraints/indexes/rls/policies) | 人工 |
| `scripts/run_sql_file.py` | 单事务执行 SQL 文件(可回滚) | `.sql` + `TEST_DATABASE_URL` | 人工/CI 辅助 |
| `scripts/database_recovery.py` | 本地一次性库校验备份恢复 | 备份 artifact + `LOCAL_RECOVERY_DATABASE_URL` → 报告;**本地 only** | 人工(恢复演练) |
| `scripts/check_post_launch_review.py` | 离线校验上线 SLO 契约 | `docs/operations/*.json` → 报告 | 人工/CI |
| `scripts/check_schema_ownership.py` | 离线校验 migration 所有权契约 | `docs/architecture/schema-ownership.json` vs SQL 布局 | 人工/CI |
| `scripts/staging_capacity_probe.py` | 本地合成容量探测(默认不联网) | 合成负载 → JSON baseline | 人工 |
| `scripts/staging_m1_acceptance.py` | M1 验收(合成 .invalid 用户,自动清理) | staging Supabase → 报告 | 人工 |
| `scripts/ci/release_evidence.py` | 记录/校验发布证据(JSON) | 命令结果 → `ci-results/*.json`、打包 | **CI**(`release-gate.yml`) |
| `scripts/ci/secret_scan.py` | 高置信 secrets 扫描 | git 跟踪文件 → 发现(脱敏) | **CI**(`supply-chain` job) |
| `scripts/ci/check_release_policy.py` | 校验发布策略/工作流标记 | 仓库文件 | **CI**(`policy` job) |
| `scripts/ci/static_test_server.py` | 静态站 fixture 测试服务器 | web root + 内容库 → HTTP | CI/人工 |

CI 仅调用 `scripts/ci/` 三个脚本(`.github/workflows/release-gate.yml` 中出现的 `scripts/…` 仅这 3 个);`check_post_launch_review.py`/`check_schema_ownership.py` 未见被 workflow 调用——「未确认」是否在其他 job 引用。

---

## 4. 部署架构

### 4.1 镜像(Dockerfile.backend)
- `FROM python:3.12-slim`;`WORKDIR /app`;`COPY`: `backend/→/app/backend/`、`scripts/→/app/scripts/`、`configs/→/app/configs/`、`data/input/→/app/data/input/`、`data/municipality_codes.json`、`data/collected_licensed/→/app/data/collected_licensed/`、`web/content-library.json→/app/web/content-library.json`(`deploy/Dockerfile.backend:1-12`)。
- `RUN mkdir -p /app/data/collected`(`:14`);`pip install -r /app/backend/requirements.txt`(`:15`);`ENV PYTHONPATH=/app/backend:/app`(`:17`);`CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`(`:19`)。
- 镜像内路径与 runner 常量一致:`REPO_ROOT = parents[3]`,在容器内即 `/app` → 读 `/app/configs/...`、`/app/data/collected_licensed/...`,写 `/app/data/collected/jphouse_runs/...`(`jphouse_runners.py:61-66`)。`backend/requirements.txt` 含 fastapi/uvicorn[standard]/asyncpg 等(`backend/requirements.txt`)。

### 4.2 compose 服务(`deploy/docker-compose.prod.yml`)
| 服务 | 形态 | 关键点 |
|---|---|---|
| `api` | 由 Dockerfile.build 构建 | `env_file: .env`、`restart: unless-stopped`、volume `../data/collected:/app/data/collected`、`expose 8000`(`:6-15`) |
| `jpsskill` | **profile `ai`**(opt-in) | build `/opt/jppskill`、`env_file: ./jpsskill.env`、`expose 8100`、volume `/opt/jppskill-data:/app/data`;默认不启动(`:17-27`) |
| `worker` | 同镜像 | `command: collection_worker.py --loop 60 --interval 10`、volume `../data/collected`(`:29-37`) |
| `scheduler` | 同镜像 | `command: sh -c "while true; do collection_scheduler.py; sleep 3600; done"`(`:39-45`) |
| `nginx` | `nginx:alpine` | ports `80:80,443:443`;volumes `../web:…/html-site:ro`、`/opt/zoubeacon/web:…/html-corp:ro`、`/opt/zoubeacon/certs:…/certs:ro`、**单文件** `./nginx/default.conf:…/conf.d/default.conf:ro`;`depends_on: api`(`:47-59`) |

注释说明:该 compose 在 runbook 切换步骤后用,替换旧的 `zoubeacon-nginx` 单容器;`data/collected` bind mount 跨重启持久化采集产物(`:1-4`)。worker/scheduler 未映射端口,走内部网络。

### 4.3 nginx 站点与反代(`deploy/nginx/default.conf`)
- `:80` 全域名 301 → https(`:1-7`)。
- `zoubeacon.com/www` → root `html-corp`(公司站),SPA fallback(`:9-24`)。
- `zoubeacon.app/www` → root `html-site`,`location = /` 重写到 `property-analysis.html`(C 端首页)(`:26-44`)。
- `platform.zoubeacon.com` → root `html-site`(B 端/后台为根)(`:46-61`)。→ 第一版两域名同 root、按 `server_name` 重写默认页(`docs/superpowers/plans/2026-09-11-lightsail-deployment-design.md:36`)。
- `api.zoubeacon.com` → 反代到 `api:8000`。**含 resolver 重解析**:`resolver 127.0.0.11 valid=10s ipv6=off;`(**Docker 内嵌 DNS**)+ `set $api_upstream http://api:8000;` + `proxy_pass $api_upstream;`(`:68, 79-80`)。用变量 `proxy_pass` 强制每请求按 resolver 重解析,规避 nginx 启动时缓存上游 IP、api 容器重启后 502 的经典问题。X-Forwarded-* 均透传(`:81-84`)。安全头 `X-Content-Type-Options/X-Frame-Options/Referrer-Policy` 各站统一(`:18-20` 等)。

### 4.4 环境变量清单与来源
`deploy/.env.example`(`:1-24`):`ENVIRONMENT`、`RELEASE_PHASE`、`DATABASE_URL`(staging Supabase transaction pooler)、`SUPABASE_URL/https://<ref>.supabase.co`、`SUPABASE_ANON_KEY`、`SUPABASE_SERVICE_ROLE_KEY`、`ABUSE_HASH_SALT`、`INTERNAL_DIAGNOSTICS_TOKEN`、`INTAKE_BUCKET`、`STRIPE_SECRET_KEY`、`STRIPE_WEBHOOK_SECRET`、`STRIPE_PRICE_IDS`(18 个服务器自有 product/currency 映射)、`BILLING_SUCCESS/CANCEL/PORTAL_RETURN_URL`、`ALLOWED_ORIGINS`、`APP_VERSION=lightsail-2026-09`、`INIT_SCHEMA=false`、`JPPSKILL_BASE_URL=http://jpsskill:8100`、`JPPSKILL_TIMEOUT_SECONDS=30`、`RECOGNITION_AI_ENABLED=false`。
- 来源:从 Render staging Environment 页复制粘贴(不落 Git、不经聊天);`DATABASE_URL`=staging Supabase;supabase 三键同 Render;首版 Stripe 可留空 → `/api/billing/*` 优雅 503(`lightsail-deployment-design.md:60-85`)。`jpsskill.env`(`OPENAI_API_KEY/MODEL/IMAGE_DETAIL`)仅 profile ai 用,且 `deploy/.gitignore` 忽略 `jpsskill.env`。
- 与 code 一致性:`db.py` 读 `DATABASE_URL`、pool `min_size=1,max_size=5`(`backend/app/db.py:10-17`);`main.py` 启动 `connect()`,仅 `INIT_SCHEMA=true` 且 env∈{local,development,test} 才建 schema(`backend/app/main.py:43-50`)——生产 `INIT_SCHEMA=false` 不会建表。`APP_VERSION` 由 `/health/ready` 回读(`backend/app/routes/health.py:31`)。

### 4.5 部署与回滚流程(runbook 要点,`deploy/README.md`)
- 前置:clone 到 `/opt/zouseeking`;`deploy/.env` 由 `.env.example` 填写、`chmod 600`(`:5-15`);沿用 `/opt/zoubeacon` 的 CF Origin 证书,**勿替换证书文件**、勿在本机跑 certbot(`:17-18, 105-107`)。
- 首次部署:填 `.env` → **先跑 `python3 deploy/render-frontend-config.py`** → `docker stop zoubeacon-nginx` → `docker compose -f deploy/docker-compose.prod.yml up -d --build`(`:50-62`)。`render-frontend-config.py` 由 `.env` 生成 `web/config.js`(gitignored,`render-frontend-config.py:41-73`;repo `.gitignore:1-2`)。
- routine 更新:`git pull --ff-only` → 重新渲染 config → `up -d --build`(`:88-95`)。
- **回滚**:`docker compose … down` → `docker start zoubeacon-nginx`(恢复旧单容器;down 不删仓库/Supabase 数据)(`:75-86`)。设计文档补充:Render staging 保持在线,DNS 指回即可(<5min)(`lightsail-deployment-design.md:102-105`)。
- jpsskill(profile ai):clone 到 `/opt/jppskill`、填 `jpsskill.env`、`--profile ai up -d --build jpsskill`;`api` 未配 `depends_on: jpsskill`,启动顺序不保证(`README.md:20-48`)。
- 与旧 Render 对比:`render.yaml` 声明 `zouseeking-api-staging`(web/python/free,`rootDir: backend`,`healthCheckPath: /health/ready`,envVars 含 `INIT_SCHEMA=false`)与 `zouseeking-web-staging`(static,`rootDir: web`);**无 `databases:`**(`render.yaml:1-43`;`docs/render-postgres-deploy.md`)。

### 4.6 已知坑(git 实测)
1. **COPY 源必须入库**:镜像 `COPY data/collected_licensed/` 与 `data/municipality_codes.json`(Dockerfile `:9-10`)。`.gitignore` 忽略 `data/collected/` 但用 `!data/collected_licensed/`、`!data/collected_licensed/*.json` 反例外(`.gitignore:17-19`)。git 实测:两处均 tracked(licensed=3 文件、municipality_codes=1)。**干净 clone 缺这些文件则 build 失败**。`web/config.js` 被 gitignore 且**不在 COPY 列表**,由部署脚本在宿主生成、经 nginx 目录挂载生效。
2. **文件级挂载 inode**:`nginx/default.conf` 作为**单文件** bind mount(`docker-compose.prod.yml:57`)。单文件挂载绑定 inode,宿主用「原子重命名」保存(编辑器常见)会使容器仍持旧 inode,需 recreate 容器才生效;`web/`、`data/collected/`、certs 用目录挂载则无此问题(`:12-13, 53-56`)。(inode 机理为通用 Docker 行为,仓库未显式记录——具体踩坑记录「未确认」。)
3. **nginx upstream 缓存**:已通过 `resolver 127.0.0.11 valid=10s` + 变量 `proxy_pass` 规避(`default.conf:68, 79-80`);若去掉变量直接 `proxy_pass http://api:8000;`,api 容器重启换 IP 会 502。
4. **Cloudflare UA 拦截**:设计文档仅记录 CF 橙云代理 + Full(strict)(`lightsail-deployment-design.md:19, 26`;`README.md:105`)。**UA 拦截在仓库内无证据 → 未确认**。

---

## 5. 运维

- **日志**:`docker compose … logs --tail=200 api worker scheduler nginx`(`README.md:97-103`)。worker/scheduler/sweeper 均输出 JSONL(每行一对象,只含 run 身份/状态/码,无 PII、无异常栈)(`scripts/collection_worker.py:1-7, 52-67`;`scripts/collection_scheduler.py:12-14`;`scripts/collection_sweep.py:13-18`)。AGENTS 要求结构化日志带 correlation ID、无 PII(`AGENTS.md`「Backend and worker rules」)。
- **健康检查**:`GET /health/live` 恒 `{status:ok}`;`GET /health` 兼容别名;`GET /health/ready` 执行 `select 1`,失败回 503 `database unavailable`,成功 `{status:ready,database:ok,version:APP_VERSION}`(`backend/app/routes/health.py:13-34`)。线上探活:`curl -fsS https://api.zoubeacon.com/health/ready`(`README.md:102`)。compose 各服务**未见 healthcheck 段**(「未确认」是否有外部探活)。
- **备份**:Lightsail 每日自动快照 + Supabase 自带备份;`data/collected` 快照随 repo/对象存储备份(`lightsail-deployment-design.md:93`)。`data/collected` 经 bind mount 跨重启持久(`docker-compose.prod.yml:3-4, 13`)。恢复演练工具 `scripts/database_recovery.py`(**仅本地一次性库**,不碰 provider;`:1-6`)。runbook 见 `docs/operations/database-recovery-runbook.md`(未逐行核)。
- **资源约束**:实例 2GB RAM / 2vCPU / 60GB SSD(Ubuntu),新加坡 Zone A(`${...}lightsail-deployment-design.md:16-20`);已配 2GB swap(fstab 持久化、`swappiness=10`)、ufw 只开 22/80/443(设计文档 §11,该 § 在文件末尾)。DB 连接池 `max_size=5`(`db.py:17`)。worker 单轮内最多认领 N 行、间隔 10s;验收目标闲时 <1.2GB、无 OOM(`lightsail-deployment-design.md:112`)。`data/input` 仅 COPY 4 个文件(acquisition_cost_rules.json、fx_rates.json、minato_* csv)。

---

## 6. 坑 / 注意事项(代码事实)

1. **licensed 聚合剔除了 `rents`,但 runner 靠 `rents` 产租金行** → 实测 `data/collected_licensed/*` 无 `rents`,而 `_rows_from_ward_record` 从 `record.rents` 取租金(`jphouse_runners.py:142-154`)。结果:从 licensed 快照读入时,每源只会产出 `sale_price` 行(3 个 layout),**租金行为 0**,`rows_collected` 与快照 `rows` 不含 rent。两处定义(过滤白名单 `build_licensed_aggregate.py:20-22` vs 读入字段 `jphouse_runners.py:133-170`)不一致,需人工确认是否为预期。
2. **快照会内嵌未授权 SUUMO 来源 URL**:config `data_sources` 仍写 suumo.jp/tochidai.info(`build_jphouse_23ku.py:207-218`),runner 原样写入快照 `source_urls`(`jphouse_runners.py:270-279`)。licensed 过滤只去数值字段,不清理 URL,存在合规暴露面。
3. **授权 gate 未接线**:scheduler 不读 `collection_sources.rights_confirmed/enabled`(`scheduler.py:161-195`),当前「授权」靠人工 flag + 人工执行 `build_licensed_aggregate.py` 保证。live 抓取明确未启用(`jphouse_runners.py:33-38`)。
4. **`run_jphouse_worker.py` 是冻结旧路径**:需显式 `ENABLE_FROZEN_JPHOUSE_WORKER=true` 才能跑,且其 `config_from_query` 用**估算模型/硬编码系数**(`base_factor`、`0.0423` 汇率),非采集数据,与 AGENTS「modeled_estimate 不得当市场事实」相关(`run_jphouse_worker.py:316-319, 80-100, 196`)。
5. **`scheduler` 在 compose 里每小时一跑,worker 认领轮询 60×10s**,而 sweeper(`collection_sweep.py`)不在 compose 服务列表内 → 僵死恢复/哈希 QA 需另行 cron 部署(「是否已配 cron」未确认;compose 无对应服务)。
6. **`INIT_SCHEMA` 非生产建表路径**:仅 local/dev/test 生效(`main.py:43-50`);生产建 schema 走 Supabase migration,勿依赖启动。
7. **`.app` 全域 HSTS 预载**:无有效证书=硬失败,证书须先行且 `.com`/`.app` 同步(`lightsail-deployment-design.md:20, 91`)。Cloudflare Full(strict),勿运行 certbot。
8. **两域名同 root**:`.app`(C 端)与 `platform`(B 端)共用 `html-site`,仅根页重写不同,构建产物未拆分(设计 §2 已列为 M6 建议项,`lightsail-deployment-design.md:36`)。

---

### 交付小结
- **做了什么**:只读通读 `backend/app/collection/*`(scheduler/worker/jphouse_runners/sweeper/`__init__`)、`scripts/*` 全部 26 个(22 主 + 4 ci)、`deploy/*`(Dockerfile/compose/nginx/env/README/render-frontend-config)、两份 plan 文档、`render.yaml`、两条相关 migration、admin collection 路由、health/db/main;并用 git、`ls`、JSON 解析做了交叉验证。
- **关键发现**:采集为 scheduler→worker→runner 三层,认领用 `FOR UPDATE SKIP LOCKED`,快照 sha256 规范化排除 `collected_at`;licensed 聚合按字段白名单过滤(`rents`/`suumo_updated` 被剔除);**处置性坑两处已证实**——(a) licensed 快照无 `rents` 而 runner 依赖 `rents` 产租金行;(b) 快照仍内嵌未授权 SUUMO URL;另证实「COPY 源必须入库」(`.gitignore` 反例外)、「nginx upstream 缓存」已用 resolver+变量 `proxy_pass` 规避、「文件级挂载」为 `default.conf` 单文件挂载、「Cloudflare UA 拦截」**未确认**。
- **未改动任何文件**(纯只读),未创建文件。
- **不确定项**:Cloudflare UA 拦截(仓库无证据)、sweeper 是否已配定时、compose healthcheck 是否存在、`run_jphouse_worker` 关联 Edge Function 现状。


---
