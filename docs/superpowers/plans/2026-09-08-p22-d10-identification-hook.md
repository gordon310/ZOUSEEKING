# P2-2 C' 实施挂点设计 · D10(2026-09-08 晚,供 09-15 主工期)

## 背景与状态

- D9 已定 C':P2-2 只接 JPPGSKILL **property-identification**(照片/网页 → listing_candidates/matched_listing),装修估算两侧闭环不打通。
- JPPGSKILL **git 化已完成**(main==origin==3d380d8,gordon310/JPPGSKILL)——roadmap B4 记录过时,无 git 待办。
- 真正待定义:property-identification **挂在小象哪条产品链**(backend 现有分析链无此入口)。

## B1 拍照流现状(挂点候选)

小象 C 端(web/mypage 工作台)查询流 = 表单(prefecture/city/ward/asset/年月)→ query → 报告。**无照片输入入口**;backend 有 renovation 上传(六类房间照,装修侧,延后)。property-identification 识别对象 = **房产外观/挂牌截图**(非装修房间照)→ 是"识别我在看哪套房/哪个挂牌"的入口。

## D10 挂点选项(09-15 拍板)

| 方案 | 形态 | 依赖/代价 |
|---|---|---|
| a. 查询预填(推荐) | C 端查询页加"拍照识别挂牌":上传挂牌截图/房产外观照 → backend `/api/recognition` → 调 JPPGSKILL property-identification → 返回 listing 链接与识别要素(结构/区域置信)→ 用户确认 → **预填 query 表单**(不做内容抓取,只跳转/预填) | JPPGSKILL server 托管可调;backend 加识别端点+前端小入口;listing 站仅外链(不采内容,AGENTS) |
| b. 独立识别工具页 | analysis 侧独立"识别挂牌"工具(非表单流) | 多一个页面/入口,产品价值待证 |
| c. 本轮关闭 P2-2 | 记录"待 C 端主流程(评估/报告/支付)上线稳定后接入",P2-2 标 blocked-product | 无跨仓开发;property-identification 能力闲置 |

## 技术要点(方案 a 前提)

1. backend `recognition` 模块:POST 图片(base64,≤2MB,白名单 JPEG/PNG/WEBP)→ 转发 JPPGSKILL `/api/analyze`(mode=property-identification,images=[{dataUrl}])→ 返回 {matched_listing? listing_candidates[]} → 前端展示(外链 listing url)。
2. 证据规则:识别结果为 **modeled/uncertain** —— 展示必须标"AI 识别,请核对";listing 链接跳转外部站(不抓取/不缓存内容);错误/低置信 → 诚实提示,不硬匹配。
3. 部署:JPPGSKILL server 需公开 HTTPS(或 backend 同区可调);API key 鉴权(backend env)。
4. 测试:backend 端点(provider mock);前端(表单预填 spec);JPPGSKILL 侧 property-identification 已有 api 测试(其仓)。

## 依赖与验收

- 依赖:JPPGSKILL server 托管(部署动作)+ D10 方案 + backend recognition 端点开发(~0.5 天)+ 前端入口(~0.5 天)。
- 验收(staging):传挂牌截图 → 识别候选列出(外链)→ 确认预填 query → 正常报告流;低置信不硬匹配。
- 本轮未写代码(跨仓/新端点=主工期动作);本文档为 09-15 开工即用的实施基线。
