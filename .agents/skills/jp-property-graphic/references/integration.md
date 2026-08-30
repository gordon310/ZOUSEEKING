# v0.1.0 宿主项目接入契约

本 Skill 包是提示词、字段约束和参考文档，不会直接控制摄像头、申请手机权限或打开数据库。宿主 Web/App 必须实现这些运行时能力，并把结果交给自己的 API 或本项目提供的 API。当前版本只覆盖现场照片、用户授权设备位置和地址持久化；不调用 OpenAI，也不执行 GeoCLIP。

## 调用顺序

1. 用户选择一个固定照片类别：`exterior`（外立面）、`bathroom`（卫生间）、`kitchen`（厨房）、`living_room`（客厅）、`bedroom`（卧室）或 `balcony`（阳台）。
2. 用户点击拍照后，宿主请求后置摄像头并拍摄 JPEG/PNG。相机和定位权限必须由用户明确触发。
3. 宿主调用 `navigator.geolocation.getCurrentPosition`。建议使用高精度、明确超时，并把浏览器返回的结果原样归一化为 `location`。不要把 `accuracy_m` 误写成地址准确率。
4. 宿主先创建或取得项目，再保存照片记录。定位失败不能丢弃照片。
5. 服务端在 `location.status === "granted"` 且经纬度有效时执行反向地理编码；失败时仍保存照片和原始位置状态，并把地址标记为不可用。
6. 宿主从项目接口重新读取记录，用于刷新页面、换设备继续工作或导出。

## 当前 API 形状

如果宿主直接复用本项目的本地服务，可使用以下接口：

- `POST /api/projects`：创建项目，body 为 `{ "title": "现场勘查" }`，返回 `{ "project": ... }`。
- `PUT /api/projects/:projectId/photos/:photoId`：创建或更新一张照片记录。
- `GET /api/projects/:projectId`：读取项目、照片、位置和地址记录。
- `DELETE /api/projects/:projectId/photos/:photoId`：删除一张照片记录。

保存照片的 body 最小形状如下：

```json
{
  "name": "exterior-01.jpg",
  "source": "camera",
  "room": "exterior",
  "imageData": "data:image/jpeg;base64,...",
  "note": "正面外观",
  "capturedAt": "2026-08-30T09:00:00.000Z",
  "location": {
    "status": "granted",
    "latitude": 34.651,
    "longitude": 135.471,
    "accuracy_m": 8.4,
    "altitude_m": null,
    "heading_deg": null,
    "speed_mps": null,
    "timestamp": "2026-08-30T09:00:01.000Z"
  }
}
```

字段约束：

- `source` 只能是 `camera` 或 `attachment`。现场拍照使用 `camera`；上传已有照片使用 `attachment`。
- `room` 只能是 `exterior`、`bathroom`、`kitchen`、`living_room`、`bedroom`、`balcony` 或 `null`。
- `imageData` 使用 JPEG、PNG、WEBP 或 GIF data URL，当前本地 API 单张最大约 12 MB。生产宿主可以改用对象存储 URL，但必须保留相同的记录语义。
- `capturedAt` 使用 ISO 8601 时间；上传旧照片没有时间时为 `null`。
- `location` 可以为 `null`。如果请求过定位，必须保留 `status`；不能获取坐标时，数值字段为 `null`。
- `location.status` 只能是 `granted`、`denied`、`unavailable`、`timeout` 或 `error`。

保存成功的照片记录包含 `location` 和 `address`。有效坐标的地址由宿主配置的反向地理编码服务返回；如果没有请求位置，地址通常是 `{ "status": "not_requested" }`，没有有效坐标时通常是 `{ "status": "no_coordinates" }`，服务失败时为 `{ "status": "unavailable" }`。`address` 是辅助结果，不能覆盖用户确认的原始坐标，也不能被解释为图片识别出的精确私人住址。

## 浏览器与手机要求

摄像头和 `navigator.geolocation` 在手机浏览器上需要安全上下文：正式环境使用可信域名的 HTTPS；本地测试可使用 `localhost`，或让手机访问电脑局域网地址并先信任开发证书。HTTP 普通局域网地址通常只能测试上传，不能可靠测试相机和定位权限。

## 当前明确不做的事情

- 不向 OpenAI 或其他 AI 服务上传照片，不需要 `OPENAI_API_KEY`。
- 不调用 GeoCLIP，不做图库相似度检索，不根据图片猜测地址。
- 不把用户设备位置默认公开；生产环境应增加登录、授权、传输加密、数据保留期限和删除机制。
- 不把上传照片的 `room` 标签当作视觉模型结论；它只是用户选择的组织标签。

如果项目明确进入后续图片分析阶段，再读取 [input-output.md](input-output.md)、[property-analysis.md](property-analysis.md) 或 [renovation-estimate.md](renovation-estimate.md)，并在调用方显式打开对应模式。
