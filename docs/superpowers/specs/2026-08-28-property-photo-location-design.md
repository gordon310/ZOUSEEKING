# 房屋拍照定位与调查记录命名设计

**状态：** 已确认，按 A 方案实施（2026-08-28）

## 目标

在现有“分析一个日本房产” intake 流程中，允许用户用手机拍摄房屋照片，主动授权设备定位后生成地址建议；用户确认或修正地址后，用地址创建调查记录名称，并在同一用户已有相同地址时要求手工修改名称。

## 范围

- 增加独立的房屋照片入口，使用浏览器原生相机能力；现有 PDF/JPG/PNG 资料上传继续保留。
- 用户明确点击定位操作后，浏览器请求 `navigator.geolocation` 权限。
- FastAPI 保存数值型经纬度、定位精度、获取时间和来源，并通过服务端反向地址适配器请求日本国土地理院接口。
- 地址解析结果只作为“待确认地址建议”；定位失败、权限拒绝或结果不完整时，用户可以手工填写地址。
- 转正保存时，服务端使用确认地址作为默认 `project_name`，按用户身份检查重复地址；重复时返回稳定的业务错误，前端要求用户手工输入项目名称后重试。
- 精确位置只保存在受信任的服务端项目数据中，前端和报告不得把它当作公开市场事实。

## 不在本次范围内

- 从照片 EXIF 读取 GPS。
- OCR、图像识别、房号识别或自动补全精确楼栋/房号。
- 在线数据库、认证、RLS、部署或 Storage bucket 的实际变更；本次只提交 forward migration 和代码，应用迁移前需单独确认备份、权限和回滚方案。
- 扩展 Edge Function 或旧区域查询链路；功能只接入现有 FastAPI intake 路径。

## 用户流程

1. 用户在提交资料区域点击“拍摄房屋照片”，手机打开后置相机；可选择多张照片。
2. 用户点击“获取照片位置并生成地址”，明确同意位置用途后浏览器请求定位权限。
3. 服务端保存坐标并返回地址候选。候选在确认字段区域以“系统建议地址（待确认）”显示，用户可编辑。
4. 用户生成免费预览时，地址按普通确认字段保存，并记录地址建议来源。
5. 用户登录后保存项目。若有已确认地址，默认项目名称等于地址；如果同一用户已有相同标准化地址，服务端返回 `duplicate_address`，前端聚焦“调查记录名称”输入框，用户修改后再次保存。
6. 没有照片、没有定位权限或地址解析不可用不阻断流程；用户可直接手工填写地址。没有地址时，保存项目必须手工填写调查记录名称。

## 服务端契约

### `PUT /api/intake/sessions/{session_id}/location`

请求头仍使用 `X-Analysis-Session`。请求体严格限制为：

```json
{
  "latitude": 34.7025,
  "longitude": 135.4959,
  "accuracy_m": 18.5,
  "captured_at": "2026-08-28T03:30:00Z",
  "consent_version": "location-2026-08",
  "source": "device_geolocation"
}
```

服务端验证经纬度范围、正数定位精度、带时区时间和固定来源；每个匿名会话限制定位请求次数。反向地址服务失败时仍保存坐标，并返回 `address_source=unavailable`，不得向用户暴露第三方异常原文。

成功候选响应包括 `address_candidate`、`address_source` 和 `address_precision`。国土地理院结果可能只有街区级名称，因此 UI 必须要求用户确认或补全。

### `POST /api/intake/sessions/{session_id}/convert`

请求体允许为空，或允许一个经过清理的 `project_name` 字符串；不得接受客户端提供的 `owner_user_id`。响应错误使用：

- `422 project_name_required`：没有确认地址且没有手工项目名称。
- `409 duplicate_address`：当前用户已有同一标准化地址的调查记录，要求手工修改项目名称。
- `409 project_name_taken`：手工名称在当前用户下已存在。

服务端从认证用户取得所有权，从会话取得位置元数据，并在一个事务中完成重复检查、属性插入、住宅详情插入和会话转正。

## 存储字段

`analysis_sessions` 与转正后的 `properties` 增加：

- `project_name text`
- `latitude numeric(9,6)`、`longitude numeric(10,6)`
- `location_accuracy_m numeric(10,2)`
- `location_source text`
- `location_captured_at timestamptz`
- `address_source text`

会话额外保存 `address_candidate text` 和 `address_precision text`，便于在用户确认前区分建议地址与最终地址。`properties.address_normalized` 继续保存最终确认地址的标准化值；`data_class` 为 `user_submitted`。

## 隐私与安全

- 未经用户点击和浏览器授权，不调用定位 API，也不上传坐标。
- 页面明确说明精确坐标用于地址建议和调查记录命名，并由服务端查询地址。
- 坐标只通过持有匿名会话 token 或已认证的 FastAPI 路径处理；不使用客户端邮箱作为所有权边界。
- 地址与项目名称使用 DOM `textContent` 渲染，服务端和数据库使用长度/范围约束。
- 不应用线上 migration，不连接真实第三方地址服务进行测试。
