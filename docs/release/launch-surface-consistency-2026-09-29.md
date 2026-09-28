# 上线面板一致性抽检(公告 ↔ 站内 ↔ 法务文本)· 2026-09-29

> 交付自倒排 **D-5 的离线自主面**(倒排表 D-5 = 「法务(日本口径)定稿 + 商店提审材料包」,其中「公告与站内页一致性抽检」属自主班可离线完成的部分)。
> 当日为 **D-8(09-29)**:其唯一验收口径是 provider 物理备份/PITR + 私有 Storage 隔离恢复演练,`provider_changes_allowed=false`(需 provider 级授权与停机窗)→ **不可自主执行**,按倒排规则顺延。
> 本班**未连生产、未连 staging、未用任何凭据、未做 DB 写/对象变更/部署**。

## 1. 这一班为什么做这件事

倒排表上 D-9(缺 `SMOKE_*`)、D-8(缺 provider 授权)、D-7 剩余部分(缺 staging/生产授权)全部卡在同一件事上;上一班已把 D-6 / D-7 的离线维度交付完毕。**10-07 上线时,公告会让用户去读站内 `privacy.html` / `terms.html` / `tokushoho.html` / `support.html`** —— 公告与站内页之间没有任何机器检查,这正是 D-1「公告发布 + 冻结」前最容易出的事故面。本班把它变成可执行门禁,并顺带查出 3 处真实缺口(§4)。

## 2. 交付物(4 个新文件,零既有文件改动)

| 文件 | 内容 |
|---|---|
| `docs/architecture/launch-surface-consistency-contract.json` | 契约(**机器可读**):公告路径、站内被引用页集合、`zh-Hant` 由 `zh-CN` 派生(运行时 `DICTIONARY_ZH_HANT` + `toTraditional`)、试运行标注键与落点页、官方数据来源 token、免费预览免责 token、法人事实(法人番号/代表者/禁值)、法域口径(token 黑名单)、占位 token、用词纪律例外、**已登记开口项**(owner / target / 是否阻断) |
| `scripts/check_launch_surface_consistency.py` | 纯标准库离线门禁:**零网络 / 零 socket / 零凭据 / 零环境变量 / 不依赖行号**;9 条判据 C0–C8;退出码 `0` 一致 / `2` 已登记开口项 / `1` **未登记漂移** |
| `tests/unit/test_launch_surface_consistency.py` | 21 例:真实仓库零未登记漂移 + 全部登记项必须**仍在复现**(防契约僵化)+ 16 条变异测试(逐条证明判据有拦截力:删页面 / 公告漏引 / 删试运行键 / 删来源 token / 删免责 / 改法人番号 / 注入错误代表人名 / 往被引用页注入新占位 / 注入越界法域 token / 注入违禁用词 / 例外失效 / 派生标记消失 / 修好草案声明后坐标消失 / 声明失效报 `resolved` / 契约缺 owner 或未知判据必须报错)+ CLI 退出码 |
| 本文件 | 判定、证据、**没覆盖什么**、待批清单 |

## 3. 判据与实跑判定(9 条)

| 判据 | 内容 | 判定 |
|---|---|---|
| C0 | i18n 字典可解析,且 `zh-Hant` 派生标记存在 | ✅ PASS |
| C1 | 公告引用的站内页存在、且被站内页链接(引用集合与契约**互查**) | ✅ PASS(`privacy/terms/tokushoho/support.html`,4/4 存在且可达) |
| C2 | 公告承诺的「页面明确标注试运行」在站内成立:`trial.badge` / `trial.provenance` 四语言非空,且 `index/analysis/data-query/report` 真的渲染该标注 | ✅ PASS |
| C3 | 公告承诺的「官方公开数据」归属在站内四语言齐备(zh-CN/ja:国土交通省 + e-Stat;en:MLIT + e-Stat) | ✅ PASS |
| C4 | 「免费预览不替代专业交易核查」四语言齐备 | ✅ PASS |
| C5 | 法人事实(法人番号/代表者)在 i18n、`tokushoho.html`、`docs/legal/01`、`docs/legal/03` 之间一致 | ❌ **FAIL(已登记 O3)** |
| C6 | 公告引用的站内页**不出现未填占位/草案残留**(含该页用到的每个 i18n 键 × 全部语言) | ❌ **FAIL(已登记 O1)** |
| C7 | 站内 `legal.*` 与已记录的**法域口径**(2026-09-24 决策:地区=日本)不冲突 | ❌ **FAIL(已登记 O2)** |
| C8 | C 端用词纪律(「物件」,禁「房源/房子」)+ 已复核例外必须仍在复现 | ✅ PASS(1 处例外已登记) |

```
python3 scripts/check_launch_surface_consistency.py        -> status: open | undeclared violations: 0   (exit 2)
9 条判据;3 项已登记开口项共 41 个坐标(O1=12 / O2=28 / O3=1)
```

**退出码 2 不是通过**:它表示「站内面板今天与公告/法务文本不一致,但每一处不一致都已登记且有人负责」。任何**未登记**的新漂移会以 exit 1 + 精确坐标报出。

## 4. 查出的 3 处真实缺口(必须在 D-1 冻结前收口,均已登记为阻断项)

**O3 · 代表人姓名不一致(1 处坐标,最容易被忽略)**
站内字典 `legal.s1Body`(zh-CN 与 ja)写「代表取締役为**姜興**」;而 `docs/legal/01`、`docs/legal/03`、`web/tokushoho.html` 三处均为「**姜爽**」。即**已通过律师复核的法务文本与站点对外页不同名**,疑似形近字笔误。处置:用户确认姓名 → Codex 改 1 处 + `npm run build:web-assets` 重建(生成物 `web/js/i18n.js` 由 `web-assets-fresh` 门禁校验)。

**O1 · 站内隐私页仍是「上线前草稿 + 未填生效日」(12 处坐标)**
`legal.draftNotice` 三语仍渲染「本文件为上线前草稿,待法务／负责人确认。生效日:**〔生效日:待确认〕**」(en/ja 同句),`web/privacy.html` 的 HTML 回退文本同句(`legal.draftNotice` 在页面上被 i18n 覆盖,回退文本仍可见于源);`legal.pdpa2` / `legal.s6Body` 亦保留「待法务确认」表述。
**与 `docs/release/go-no-go-checklist-2026-10-07.md` 的 C10 判定直接冲突**(该行写「`docs/legal/01-04` 按用户决策定稿并**上线**……**占位清零**」)。按 AGENTS「文档与代码冲突必须显式暴露」,此处如实列出,不代为改写:两个口径必须由用户拍板哪一个为准。

**O2 · 站内 `legal.*` 仍是台湾 PDPA 口径(28 处坐标)**
`s2Title` = 「2. 台湾 PDPA 第 8 条:六项告知」(en: "Taiwan PDPA Article 8";ja:「台湾PDPA第8条」),`s2Intro` / `s5Body` / `s6Body` / `s7Body` 同样按台湾/香港/新加坡多法域展开。而 2026-09-24 决策 4 = **法务地区定位日本(個人情報保護法 / 特定商取引法)、允许地区 = 日本、不做多地区适配**,`docs/legal/01` 已是 APPI 口径且**律师复核已通过**(`docs/legal/00-INDEX.md`)。即:**已定稿的法务文本没有同步到站点字典**,站点仍在展示旧口径。

## 5. 需人工判断(本门禁**不**机检,如实列出)

1. 公告写「特商法 ★ 项已在站内 `tokushoho.html` 以日本法允许的『**請求時開示**』方式表述」,但 `tokushoho.html` 实际**逐项公开**(販売業者/法人番号/運営統括責任者/所在地/連絡先/価格/引渡時期/返品特約…)→ 公告这句话与实际不符(方向是「公布得更多」,但措辞需改或需说明 ★ 项另有所指)。
2. 地址表述不一:`web/privacy.html` 用「大阪府大阪市生野区林寺**２丁目５番２２号**」(全角),`tokushoho.html` 用「〒544-0023 大阪府大阪市生野区林寺**2-5-22**」→ 机检只核对法人番号与代表人,地址格式差异待法务统一。
3. `docs/legal/00-INDEX.md` 记「日本律师复核**已通过**,待补留痕(复核人/事务所、日期、存档位置)」——留痕仍缺,不代填(倒排 D-5 已列为用户项)。

## 6. 没覆盖什么(不粉饰)

- 只证**静态结构**:不证页面在浏览器里的真实渲染、不证 JS 运行时语言切换、不证线上部署产物。
- `zh-Hant` 由 `zh-CN` 经 `toTraditional` 派生,本门禁**按其派生**评估,不重写转换器;`web-source` ↔ 生成物 `web/js/i18n.js` 的一致性由既有 `web-assets-fresh` 门禁负责,不在此重复。
- 不判**法务文本本身是否正确**(只判「站内是否与已记录的决策/已定稿文本一致」);文案该如何改由用户/法务定。
- 不取代 C13/C14 的 staging/生产证据,也不构成任何「已上线可用」的结论。
- 未把本门禁挂进 CI(`.github/workflows/release-gate.yml` 三处挂载未动):它是冻结前的抽检工具,新增单测已被既有 `python-pytest` 覆盖。是否升格为发布门禁由用户决定。

## 7. 验收(本 BOT 独立实跑)

```
python3 scripts/check_launch_surface_consistency.py            -> exit 2, undeclared violations: 0
python3 scripts/check_launch_surface_consistency.py --json     -> {"status":"open","production_contacted":false,"network_used":false,...}
PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit/test_launch_surface_consistency.py -q   -> 21 passed
PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit tests/architecture -q                   -> 618 passed / 91 skipped(基线 597,+21 零回归)
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src           -> OK
node --check web/app.js                                                                            -> OK
python3 scripts/ci/check_release_policy.py                                                         -> release policy: PASS
python3 scripts/check_schema_ownership.py                                                          -> schema_ownership_status=pass
git status / git diff --check                                                                      -> 仅 4 个新增文件,无空白问题
```

## 8. 待批清单(本班不执行,仅列处置方案)

| # | 事项 | 建议处置 | 谁 |
|---|---|---|---|
| 1 | **O3 代表人姓名**:`legal.s1Body` 的「姜興」 | 确认姓名后改 1 处 + 重建前端资源 + 复跑本门禁(应只剩 O1/O2) | 用户确认 + Codex 执行 |
| 2 | **O1 站内隐私页草案声明 + 未填生效日** | 依已定稿 `docs/legal/01` 重写站点 `legal.*` 文案(含生效日),同步清 `web/privacy.html` 回退文本 | 用户口径 + Codex |
| 3 | **O2 台湾 PDPA 口径未同步**(与 O1 同源) | 同批把 `docs/legal/01` 的 APPI 口径落到站点字典;完成后再定 C10 的「占位清零」结论 | 用户口径 + Codex |
| 4 | 公告「請求時開示」措辞与实际不符(§5.1) | 改公告措辞或在公告中说明 ★ 项口径 | 用户 + Hermes 起草 |
| 5 | 是否把本门禁挂进 Release Gate | 冻结前作为 D-1 前置抽检即可;升格为 CI 门禁需同步三处挂载口径 | 用户决定 |
| 6 | D-8 本体(provider 物理备份/PITR + 私有 Storage 隔离恢复演练) | 需 provider 级授权 + 停机窗;`docs/operations/database-recovery-runbook.md` 与 `scripts/database_recovery.py` 已就绪 | 用户授权 + Codex |
