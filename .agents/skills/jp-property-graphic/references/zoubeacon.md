# ZOUBEACON / JPPropDIs 接入适配器

本适配器把 `jp-property-graphic` 的 v0.1.1 现场采集语义映射到 ZOUBEACON 当前的 FastAPI → Supabase Auth/PostgreSQL/私有 Storage 路径。它只负责照片、设备位置和地址候选的记录；不调用 OpenAI，不执行 GeoCLIP，不把照片送到外部 AI 服务。

## 调用边界

ZOUBEACON 的 Web 页面是宿主，浏览器负责相机和地理位置权限，FastAPI 负责认证会话、限流、私有文件存储、反向地址解析和数据库写入。Skill 运行在项目的 AI/开发代理上下文中，不能替代这些运行时组件。

不要调用本包通用接入文档中的 `/api/projects`、`/api/projects/:projectId/photos/:photoId` Node 示例端点。ZOUBEACON 使用本节的 `/api/intake/...` 端点。

## ZOUBEACON 调用顺序

1. 用户选择用途 `self_use` 或 `rental_investment`，宿主调用 `POST /api/intake/sessions` 创建匿名临时会话。
2. 用户在 `property-analysis.html` 选择或拍摄照片。当前 Web 端通过原生 `<input type="file" capture="environment">` 打开手机相机；照片先上传到私有 Storage，再请求定位。
3. 宿主对每张照片调用 `POST /api/intake/sessions/:sessionId/files`，使用 `X-Analysis-Session` 传递一次性会话 token，body 为 multipart `file`。只接受 PDF/JPG/PNG，单文件上限 20 MiB。
4. 用户明确点击位置操作后，宿主调用 `navigator.geolocation.getCurrentPosition`，只把用户授权返回的数值位置提交给 `PUT /api/intake/sessions/:sessionId/location`。
5. 用户检查 `address_candidate`，可手工修正完整地址。确认地址时调用 `PUT /api/intake/sessions/:sessionId/fields/address`。
6. 宿主按现有产品流程调用 `POST /api/intake/sessions/:sessionId/preview`；登录用户需要保存时，再调用 `POST /api/intake/sessions/:sessionId/convert`。

## 端点契约

创建会话：

```http
POST /api/intake/sessions
Content-Type: application/json
```

```json
{
  "purpose": "self_use",
  "consent_version": "privacy-2026-08"
}
```

返回的 `session_token` 只在创建响应中出现。宿主可在当前浏览器会话中保存它，但不得把它写入 URL、日志或 Skill 输出。

上传文件：

```http
POST /api/intake/sessions/:sessionId/files
X-Analysis-Session: <session_token>
Content-Type: multipart/form-data
```

位置请求的 JSON body：

```json
{
  "latitude": 34.7025,
  "longitude": 135.4959,
  "accuracy_m": 18.5,
  "captured_at": "2026-08-30T09:00:00+09:00",
  "consent_version": "location-2026-08",
  "source": "device_geolocation"
}
```

位置端点：

```http
PUT /api/intake/sessions/:sessionId/location
X-Analysis-Session: <session_token>
Content-Type: application/json
```

成功响应包含：

```json
{
  "latitude": 34.7025,
  "longitude": 135.4959,
  "accuracy_m": 18.5,
  "captured_at": "2026-08-30T00:00:00Z",
  "location_source": "device_geolocation",
  "address_candidate": "大阪府大阪市北区梅田",
  "address_source": "gsi_reverse_geocoder",
  "address_precision": "town"
}
```

地址确认、预览和保存：

- `PUT /api/intake/sessions/:sessionId/fields/address`：body 至少包含 `field_name: "address"`、`value`、`confirmation_status`；最终地址由用户确认/修正。
- `POST /api/intake/sessions/:sessionId/preview`：生成免费预览；使用 `X-Analysis-Session`。
- `POST /api/intake/sessions/:sessionId/convert`：需要 Supabase Auth 的 `Authorization: Bearer <access_token>` 和 `X-Analysis-Session`；可选 body `{ "project_name": "..." }`。

## 固定照片类别与当前存储限制

Skill 的固定类别仍为 `exterior`、`bathroom`、`kitchen`、`living_room`、`bedroom` 和 `balcony`。当前 ZOUBEACON FastAPI 文件接口尚未提供 `room` 数据库字段；宿主可以先在页面状态和文件命名中保留类别，但不能声称类别已经持久化到服务器。若要正式保存 `room`，必须另行设计 forward migration、RLS、API 模型、对象元数据和回归测试，不能把未知字段直接塞进请求体。

当前定位记录保存于 `analysis_sessions`，登录用户转正后复制到 `properties`。位置精度是设备报告值，不是地址准确率；GSI 地址是街区/町名级候选，不自动生成楼栋或房号。反向地址失败时仍保留坐标，并允许用户手工填写地址。

## 生产安全要求

- 生产前端必须使用可信 HTTPS；手机浏览器的相机和地理位置权限不能依赖普通 HTTP 局域网地址。
- `property-intake` Storage bucket 必须保持 private；浏览器不直接使用 service-role key，也不绕过 FastAPI 写私有表。
- 精确经纬度属于敏感现场数据，只向必要的受信任后端发送；页面、日志、分析结果和公开报告不得默认暴露。
- 用户拒绝定位、设备不支持、定位超时或 GSI 不可用时，不丢弃照片；记录失败状态并保留手工地址回退。
- 生产发布前需要真实账号、真实设备和最小化测试照片的闭环验证；不要在测试报告中使用或公开用户真实房产资料。
