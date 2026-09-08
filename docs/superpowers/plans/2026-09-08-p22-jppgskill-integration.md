# P2-2 JPPGSKILL 联调考古与方案(2026-09-08/09)

## 考古结论(两仓同域已确认)

| 侧 | 域 | 六类枚举 | 分析协议 |
|---|---|---|---|
| JPPropDIs backend `renovation/` | 装修估算(HttpVisionProvider 外呼视觉服务;PhotoRecord{id,room,observations};pricing 规则 → estimate) | `exterior/bathroom/kitchen/living_room/bedroom/balcony` ✓ | POST `{context, photos:[{id,room,filename,media_type,content_base64}]}` → VisionResponse(PhotoRecord 列表) |
| JPPGSKILL server `api.mjs` | `property-identification` / `renovation-estimate` / `combined` 三模式视觉分析 | `PHOTO_ROOMS` = 同六类 ✓ | POST `/api/analyze` `{mode, images:[{dataUrl|url…}], property_url?}` → 分析结果 |

**判定**:同域、同六类枚举、意图一致(renovation-estimate ↔ 装修估算)。联调缺口 = **请求协议形态**(backend 发 base64+context 单请求;JPPGSKILL 收 mode+images(dataUrl))+ **响应契约未对齐**(VisionResponse 字段 vs JPPGSKILL analyze 输出需逐一比对,未在本轮完成)。

## 契约比对(2026-09-09 凌晨)——发现流程分歧,非薄适配

**JPPGSKILL `ANALYSIS_RESULT_SCHEMA.renovation_estimate`(openaiAnalysis.mjs)**:`{currency: JPY, tax_basis, total_range, items:[{name, photo_observations: str[], estimate_assumptions: str[], range, source_refs: str[]}], assumptions[], excluded_items[], confidence}`——**LLM 端到端汇总估算**(整单工程项+区间,观察为文本串)。
**backend `VisionResponse`(renovation/vision.py + models)**:`PhotoRecord{id, room, observations:[{component, condition,…}]}`——**逐照片结构化观察**,再由 `pricing.py` 确定性规则(PriceRule)合并成 EstimateItem(金额区间+basis)。

**分歧本质**:观察粒度(逐照片结构化 vs 整单文本)+ 计价哲学(确定性规则 vs LLM 区间)。方案 A 的"兼容端点映射回 VisionResponse"**不可行**(结构粒度不匹配);强行映射会引入无证据数字或绕过定价规则 → 违反 AGENTS 证据规则。

## 修正选项(待用户/白天决策)

| 方案 | 内容 | 含义 |
|---|---|---|
| A' | JPPGSKILL 增**逐照片观察端点**(复用六类/照片 → 每照片结构化观察,同 backend PhotoRecord schema),backend 零改,走自家 pricing 规则 | JPPGSKILL 变纯"视觉观察服务"层(与 LLM renovation-estimate 模式并存,但只观察不估);双引擎各留一处权威 |
| B' | backend 接受 JPPGSKILL estimate 直入(新落库路径,绕过 pricing 规则) | 双计价路径并存,违反单权威路径(AGENTS),需明确产品分工后才可 |
| C' | P2-2 缩小:仅联调 **property-identification**(房产识别/listing 匹配)给 B1 房产识别;装修估算两侧各自闭环暂不打通 | 最快合规;六类照片装修估算后端侧继续用自家 vision 服务(若有)或标记待定 |
| D' | 产品决策:小象 C 端装修估算是否用 JPPGSKILL 引擎(LLM 区间)替代自家规则引擎 | 架构级选择,需用户 + 影响 P2-3/报告链 |

本轮不改代码;契约分歧已记录,待 09-15 主工期前拍板。

## D9 决策(2026-09-09 用户确认:**C' 缩小联调**)

P2-2 范围 = 仅接 JPPGSKILL **property-identification**(房产识别→listing 匹配)给 B1;装修估算两侧各自闭环(backend 规则引擎 / JPPGSKILL LLM 引擎互不打通),A'/D' 架构决策延后。后续 P2-2 实施按 C':跨仓 = JPPGSKILL git 化 + property-identification 联调端点;六类照片装修估算后端维持现状(自家 vision 服务配置待定)。

## 跨仓前置(需用户决策,涉及另一仓库)

1. **JPPGSKILL git 化**(roadmap B4 一直挂起:当前非 git 仓库)→ `git init` + 首提交 + gordon310/JPPGSKILL 远端?(版本 v0.1.1 已有 release tar)
2. 方案 A 适配端点开发(在 JPPGSKILL 仓)
3. 部署:JPPGSKILL server 上线(当前仅本地 node;需托管供 staging backend 外呼)或 staging 本地化(VPN/内网)
4. backend HttpVisionProvider URL env 指向 JPPGSKILL(部署配置)

## 依赖与验收

- 依赖:跨仓动作 1-3(用户拍板)+ backend vision 响应契约与 JPPGSKILL 输出字段逐项比对(下轮考古:VisionResponse/PhotoObservation vs JPPGSKILL analyze 结果结构)
- 验收(staging):六类照片上传 → 估算返回真实观察(非 synthetic)→ estimate 输出(renovation_observations 落库已备)
- 本轮不改代码(跨仓写操作先确认);后端 vision URL 已可配置(env),接线为配置动作
