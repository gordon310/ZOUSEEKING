# P2-2 JPPGSKILL 联调考古与方案(2026-09-08/09)

## 考古结论(两仓同域已确认)

| 侧 | 域 | 六类枚举 | 分析协议 |
|---|---|---|---|
| JPPropDIs backend `renovation/` | 装修估算(HttpVisionProvider 外呼视觉服务;PhotoRecord{id,room,observations};pricing 规则 → estimate) | `exterior/bathroom/kitchen/living_room/bedroom/balcony` ✓ | POST `{context, photos:[{id,room,filename,media_type,content_base64}]}` → VisionResponse(PhotoRecord 列表) |
| JPPGSKILL server `api.mjs` | `property-identification` / `renovation-estimate` / `combined` 三模式视觉分析 | `PHOTO_ROOMS` = 同六类 ✓ | POST `/api/analyze` `{mode, images:[{dataUrl|url…}], property_url?}` → 分析结果 |

**判定**:同域、同六类枚举、意图一致(renovation-estimate ↔ 装修估算)。联调缺口 = **请求协议形态**(backend 发 base64+context 单请求;JPPGSKILL 收 mode+images(dataUrl))+ **响应契约未对齐**(VisionResponse 字段 vs JPPGSKILL analyze 输出需逐一比对,未在本轮完成)。

## 适配方案

| 方案 | 内容 | 代价/风险 |
|---|---|---|
| A(推荐) | JPPGSKILL server 增 `/api/v1/renovation-photos` 兼容端点:接收 backend HttpVisionProvider 现有 payload,内部映射到 analyze(renovation-estimate),响应映射回 backend VisionResponse | 跨仓改 JPPGSKILL(~1 天);backend 零改(URL env 指向即可) |
| B | backend HttpVisionProvider 改发 JPPGSKILL 原生协议 | 改 backend(测试同步);JPPGSKILL 零改 |
| C | 双向薄适配层(独立小服务) | 多一跳,不推荐 |

## 跨仓前置(需用户决策,涉及另一仓库)

1. **JPPGSKILL git 化**(roadmap B4 一直挂起:当前非 git 仓库)→ `git init` + 首提交 + gordon310/JPPGSKILL 远端?(版本 v0.1.1 已有 release tar)
2. 方案 A 适配端点开发(在 JPPGSKILL 仓)
3. 部署:JPPGSKILL server 上线(当前仅本地 node;需托管供 staging backend 外呼)或 staging 本地化(VPN/内网)
4. backend HttpVisionProvider URL env 指向 JPPGSKILL(部署配置)

## 依赖与验收

- 依赖:跨仓动作 1-3(用户拍板)+ backend vision 响应契约与 JPPGSKILL 输出字段逐项比对(下轮考古:VisionResponse/PhotoObservation vs JPPGSKILL analyze 结果结构)
- 验收(staging):六类照片上传 → 估算返回真实观察(非 synthetic)→ estimate 输出(renovation_observations 落库已备)
- 本轮不改代码(跨仓写操作先确认);后端 vision URL 已可配置(env),接线为配置动作
