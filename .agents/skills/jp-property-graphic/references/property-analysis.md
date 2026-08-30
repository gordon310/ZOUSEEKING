# 位置识别与公开核验

本 reference 用于 `property-identification` 和 `combined` 模式。遵循 [input-output.md](input-output.md) 的请求、响应与中文报告规则；输出时始终分开图片观察、网页直接事实、推断和未知项。

## 图片观察

逐张检查并记录建筑结构、外墙、屋顶、窗户、阳台、道路、地形、植被、远景、标识和可读文字。每项标明是：

- 可见事实：照片直接可见的内容；
- 推断：由可见事实得出的有限判断，并说明依据；
- 未知项：被遮挡、模糊或照片未覆盖的内容。

## 后续 GeoCLIP 候选与参考图库（当前不执行）

当前阶段位置优先使用拍照时用户授权提供的设备定位记录；不要在拍照流程中调用以下图像定位或参考图库逻辑。只有用户明确恢复图像定位功能时，才执行本节规则。

位置识别可选地调用本项目的本地 GeoCLIP 适配器（`scripts/geoclip_predict.py` 或 `/api/geolocate`）。它输出 Top-K 经纬度候选，用于缩小检索范围；它不是地址识别器，也不构成挂牌或私人住址确认。报告中应说明“全球模型候选，未使用日本本地房产图库”等限制，并把候选与原始图片 ID 关联。

若项目已有合法取得的日本参考图片及元数据，可按 `data/japan-reference-gallery/manifest.json` 的协议把查询图和参考图转换为视觉向量，返回候选建筑。当前本地适配器复用 GeoCLIP 图像特征作基线，CosPlace/VPR 可替换同一向量检索层。候选必须再通过外观布局、道路关系、可读标识或公开页面事实进行独立复核；只有向量相似度不能填写 `matched_listing`。参考图库为空、覆盖不足或许可证不明确时，跳过检索并保留 `unknown`。

manifest 的每个 `entries` 项至少包含 `id`、图库目录内的相对 `image`、`latitude`、`longitude`、`source_name` 和 `license`；可选 `area`、`title`、`source_url`。图片不得通过 `..` 跳出图库目录，`source_url` 只能是公开 HTTP(S) URL。匹配结果保留区域、来源和相似度，但不返回本地文件路径。

重复或近似图片只计一次，不得把同一视角重复作为独立证据。无法读取的图片写入 `limitations`。

## 公开资料核验

优先核验用户提供的 `property_url`；仅在需要补充或交叉核验时，查阅地图、开发商页面或其他公开资料。只访问当前核验直接相关的公开页面，不登录、不填写或提交表单，也不泄露上传图片或用户上下文。用户提供但未访问的 URL 不是 `sources`。每一条实际使用的外部事实都写入 `sources`，并保留：

- `url`
- `title`（页面标题或来源名）
- `purpose`（该资料用于核对什么）
- `retrieved_on`（检索日期，`YYYY-MM-DD`）

登录、付费、失效或无法访问的页面不得产生网页事实或伪造来源；在 `limitations` 中说明，并退化为仅基于图片的分析。

## 候选匹配与证据

`property_assessment.matched_listing` 仅在公开页面事实与图片至少有两类独立证据吻合时填写；未达到该门槛时必须为 `null`。独立类别可包括清晰的建筑外观、窗户/阳台配置、道路或地形、可读标识、公开页面图片或其他可核验房产事实；同一图片的重复描述不构成多类证据。非空对象必须采用 `input-output.md` 的 `{ url, title, source_name, confidence, evidence, source_refs }` 形状：每个证据包含不同的 `category`、具体 `description`、相关 `input_refs` 和可审计 `source_refs`。

单一相似点只能形成宽泛位置候选，并使用 `confidence: "low"`，不得确认 `matched_listing`。未确认挂牌只放 `property_assessment.listing_candidates`，采用协议定义的可审计候选形状；`location_assessment.candidates` 只放地理位置候选。用户提供但尚未访问的 URL 可以作为低置信度挂牌候选，`source_refs` 为空且不是网页事实或 `sources`。来源或图片证据冲突时，在 `limitations` 中列出冲突内容，保留相互矛盾的来源，并降低相关候选和匹配结论的 `confidence`。

## 位置层级与隐私

按证据从宽到窄填写 `location_assessment`：都道府县（`prefecture`）、市区町村（`municipality`）、更小区域；证据不足时 `level` 为 `unknown`。每个 `candidates` 项均提供 `name`、`confidence` 和 `evidence`。`confidence` 只能为 `low`、`medium` 或 `high`，并与独立、清晰和一致的证据数量相称。

普通住宅照片不得推断精确私人住址。公开页面出现的地址只能作为网页直接事实标记为“来源提供”，不等同于通过图片识别出的地址。不识别或推断住户、人脸、车牌或任何敏感属性。

## 固定输出字段与审计映射

- `property_assessment.observed_facts`：每项必须标为“图片观察”或“网页事实”。网页事实必须附 `来源：<sources[].url>`；图片观察不得伪装为网页事实。
- `location_assessment.candidates`：每项的 `evidence` 必须标明“图片观察”“网页事实”或“推断”。网页事实和引用网页事实的推断必须附 `来源：<sources[].url>`；推断还要写明所依据的图片观察或网页事实。
- `property_assessment.unknowns`：仅放未由图片或可访问公开资料确认的未知项。
- `property_assessment.listing_candidates`：仅放未确认挂牌，绝不混入地理位置候选；用户提供但未访问的 URL 没有 `sources` 引用。
- `property_assessment.matched_listing`：只有满足两类独立证据门槛时才填写，并保留 URL、标题/来源名、置信度、两项不同类别的独立证据和 `source_refs`；否则必须为 `null`。
- `location_assessment`：位置层级、候选、`confidence` 和上述可审计证据。
- `sources`：实际使用的公开资料及其 URL、来源名、用途和检索日期。
- `limitations`：不可读取图片、不可访问页面、证据不足、冲突和隐私边界。

固定中文报告中，“位置判断”呈现 `location_assessment.candidates` 及其证据标签；“房产信息”呈现 `observed_facts`、`unknowns` 和 `matched_listing`；“依据与风险”呈现推断及冲突；“来源和限制”呈现 `sources` 和 `limitations`。这些章节保留上述标签和来源 URL，以区分图片观察、网页事实、推断和未知项。
