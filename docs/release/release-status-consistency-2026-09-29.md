# 发布状态判定一致性门禁 —— 交付与实测证据(2026-09-29 夜班,D-8 离线面)

> 本班为 **D-8(09-29)** 夜班。当日唯一验收口径 `C04 = provider 物理备份/PITR + 私有 Storage 隔离恢复演练` 需 provider 级授权与停机窗(`production-go-live-approval.json` 的 `provider_changes_allowed=false`)→ **不可自主执行**。按倒排规则顺延:D-9/D-7/D-6 的剩余部分同样卡在 staging/生产授权,上一班(09-29 早班)已交付 D-5 的「公告 ↔ 站内 ↔ 法务文本」离线面。故本班取**同一根因的第二个自主面**——过去两个班都在修「**同一份发布状态文档自相矛盾/与机器状态不符**」这一类问题(`352b8d4`、`7241aa2`),本班把它**变成机检门禁**,不再靠人肉发现。
> 开工前实测:工作树干净(`git status --porcelain` 空),HEAD = `acf69a2`,main == origin/main。

## 1. 交付物(4 个新增文件 + 1 处文档更正)

| 文件 | 内容 |
|---|---|
| `docs/architecture/release-status-consistency-contract.json` | 机器可读契约:C 项状态格里/表注册(历史 vs 当前)/ 状态类归一(✅ 已闭合、🟡 部分、❌ 未开始)/ **机器状态绑定**(approval·release-evidence·staging-smoke JSON 的值 → 允许的文档状态类)/ 状态引用声明(当前 section 必须引用机器真值、不得残留旧值)/ 总判定来源 / 倒排行 ↔ 清单项的比对面 / 已登记开口项(owner+target+blocking) |
| `scripts/check_release_status_consistency.py` | 纯标准库离线门禁,C0–C7 八条判据;**零网络、零 socket、零凭据、零环境变量、不依赖行号**;退出码 `0` 一致 / `2` 已登记开口项 / `1` **未登记漂移**;支持 `--json`;契约自身有问题时以 `contract error` 退出(不静默通过) |
| `tests/unit/test_release_status_consistency.py` | 28 例:真实仓库零未登记漂移 + 已登记项必须仍在复现 + **21 条变异测试**(回退 C14 行、把授权打回 BLOCK、把证据打回 NOT_EXECUTED、把 staging 证据改成 EXECUTED、删历史声明、改当前 section 标题、**新增未登记的判定表**、删行/重复行/抹掉状态符、把 No-Go 写回 verdict、把 D-9/C13 行标成已完成、已登记项不再复现必须报 `resolved`)+ 6 条契约自身变异(owner 写成 TBD、同一符号归两类、绑定越界项、声明引用不存在的 section、缺键、非法正则)+ CLI 退出码 |
| `docs/release/release-status-consistency-2026-09-29.md` | 本文件:判据表 + 查出的漂移 + 原始输出 + 未覆盖面 + 待批清单 |
| `docs/release/go-no-go-checklist-2026-10-07.md`(更正 1 行) | §B 的 C14 行由「🟡 待用户逐项授权」改为「✅ 已完成(09-27)」,并引用机器状态 `AUTHORIZED` / `PRODUCTION_EVIDENCE_RECORDED` |

## 2. 查出的真实漂移(1 处,已按机器状态更正;1 处保留待批)

| # | 漂移 | 证据 | 处置 |
|---|---|---|---|
| D1 | **同一份清单里 C14 自相矛盾**:文件头(03 行)、§C-2(123 行)与机器状态都说已完成/已授权,而 §B 判定表(91 行)仍写「🟡 待用户逐项授权」 | `production-go-live-approval.json` = `AUTHORIZED`(owner: Gordon,`authorized_at` 2026-09-27);`production-release-evidence.json` = `PRODUCTION_EVIDENCE_RECORDED` | **本班更正 §B C14 行**(只改状态与依据,不改任何人的批准事实),并把它钉进机检:回退该行 → 门禁 exit 1 并点名两条坐标 |
| D2 | **倒排行 ↔ 清单项口径冲突(保留)**:倒排 D-8 行仍把 `C04` 的 provider 物理备份/PITR + Storage 隔离恢复列为当日待办,清单 §B 则判 C04 已闭合、把剩余 provider 演练列为**上线后加固项、不阻塞 10-07** | `plan:D-8:C04:plan-open-checklist-closed` | 属**范围口径决策**,两读法都成立;已登记为开口项(owner 用户,target D-2 10-05,blocking=true),**不擅自改任何一份文档** |

> 为什么 D1 可以自主修、D2 不能:前者是**机器状态已唯一确定**的文字未同步(改的是"哪一行写着什么",不产生新事实);后者是**两份文档谁说了算**的范围判断,涉及 10-07 的 Go/No-Go 口径,必须用户拍板。

## 3. 判据表(门禁实际在查什么)

| 判据 | 内容 | 防的是哪类事故 |
|---|---|---|
| C0 | 契约结构:键完整、glyph 不跨类、section/state_file/binding/claim 的 id 唯一、owner/target 不得 TBD、正则合法 | 契约本身烂掉,门禁变成摆设 |
| C1 | **section 注册**:登记的标题必须仍在;**任何携带 C 项状态行的表都必须登记** | 新加一张判定表逃逸在门禁之外 |
| C2 | **历史段必须保留历史声明**(「旧判定不再作为当前结论,勿引用」) | 旧的 No-Go 判定被当成当前结论引用 |
| C3 | **当前表必须对 C01–C14 逐项判定一次**,不允许漏项、重复行、无状态符 | 合并/改写表格时某项悄悄消失 |
| C4 | **机器状态绑定**:approval JSON / release-evidence JSON / staging-smoke JSON 的值 → 允许的文档状态类;出现**契约未覆盖的新值**直接报错 | 文档状态与机器真值反向(本班 D1 即此类) |
| C5 | **当前 section 必须引用机器真值**,且不得残留已作废的旧值(旧值扫描仅限当前判定表;§C-2 允许叙述"由 X 更新为 Y") | 文件头/判定表继续写着 `BLOCK / NOT AUTHORIZED` 这类过期口径 |
| C6 | **全文档只能有一个「工程侧」判定**,且必须等于机器状态推出的判定;§C-2 必须写出该判定 | 头部 Go、正文 No-Go(或反之) |
| C7 | **倒排行引用 C 项时必须与清单状态同向**:倒排标已完成而清单未闭合、或倒排仍在待办而清单已闭合 → 报错 | 倒排表还在排已闭合的活,或倒排表已勾掉清单说没闭的活 |

## 4. 验收(本 BOT 独立实跑)

```
python3 scripts/check_release_status_consistency.py                  -> status: open,未登记漂移 0 (exit 2)
                                                                        C0-C6 PASS;C7 OPEN(仅已登记项 RS1)
                                                                        坐标:plan:D-8:C04:plan-open-checklist-closed
python3 scripts/check_release_status_consistency.py --json           -> {"status":"open","production_contacted":false,"network_used":false}
pytest tests/unit/test_release_status_consistency.py -q              -> 28 passed
pytest tests/unit tests/architecture -q                              -> 649 passed / 91 skipped(同 checkout 基线 621,+28 零回归)
   (基线取法:pytest tests/unit tests/architecture -q --ignore=<本班新测试文件> -> 621 passed / 91 skipped)
PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src -> OK
node --check web/app.js                                              -> OK
scripts/ci/check_release_policy.py                                   -> release policy: PASS
scripts/check_schema_ownership.py                                    -> pass
git status / git diff --check                                        -> 仅 4 新增文件 + 1 处文档更正;无空白问题
```

**仓库外独立变异探针**(副本在 `/tmp/rs-consistency-probe`,工作树零改动,由本 BOT 手写,不走测试代码):

```
未变异副本                             -> exit 2(与仓库内一致)
变异1 回退 C14 行为「待用户逐项授权」     -> exit 1: binding:B1_c14_go_live_approval:C14:partial:vs:AUTHORIZED
                                                    binding:B2_c14_release_evidence:C14:partial:vs:PRODUCTION_EVIDENCE_RECORDED
变异2 把授权打回 BLOCK / NOT AUTHORIZED  -> exit 1: binding:B1…C14:closed:vs:BLOCK / NOT AUTHORIZED
                                                    state-claim:SC1…missing:BLOCK / NOT AUTHORIZED
                                                    verdict:Go:vs:BLOCK / NOT AUTHORIZED + verdict:No-Go:missing-in-final-verdict
变异3 删掉历史声明                       -> exit 1: section:legacy_audit_2026_09_12(+:caveat)
变异4 把 D-9/C13 行标成已完成            -> exit 1: plan:D-9:C13:plan-closed-checklist-partial
```

## 5. 未覆盖(不粉饰)

- **只证文档与已存档状态之间不自相矛盾**,不证这些状态**当前仍然真实**:approval/evidence JSON 是 2026-09-27 的存档记录,本门禁不连生产、不重新采集。
- 不判**文字描述的对错**(例如 C04 那段"剩余属上线后加固"是否成立),只判状态类与引用是否同向;语义判断留人工(D2 即此类)。
- **未挂进 CI**(`release-gate.yml` 三处挂载未动);新单测已被既有 `python-pytest` job 的 `python -m pytest -q` 覆盖。
- 不覆盖 `progress.md`、`launch-readiness-log.md`、公告文本之间的叙述一致性(公告 ↔ 站内已由 `check_launch_surface_consistency.py` 负责)。
- 本班**未连生产/staging、未用凭据、未做 DB 写/对象变更/部署、未改任何法务文案**。

## 6. 待批清单(需用户)

| # | 事项 | 决定什么 | 建议 |
|---|---|---|---|
| 1 | **D2:C04 范围口径** —— 倒排 D-8 的 provider 物理备份/PITR + Storage 隔离恢复,是 10-07 前必做,还是上线后加固 | D-2 终检的阻断口径;决定要么改倒排行、要么改清单行 | A 维持清单口径(列为上线后加固,倒排该行改标注)**推荐** / B 维持倒排口径(则该 drill 成为 D-1 前阻断,且需 provider 授权) |
| 2 | **C13 staging 一次性写入授权 + `SMOKE_*` 三凭据**(可选) | D-9/D-6/D-7 剩余实测能否执行 | 给授权即可连续收口四项 |
| 3 | **C11 预算/SLO 数值** | D-2 容量口径 | 给北极星数值 |
| 4 | **首周观察窗投递与告警到人**(是否批准新增定时采集 + 值班责任人/SLA) | D-1 冻结前确认 | 需批准后接线 |
| 5 | **法务留痕**(复核人/事务所、日期、书面结论存档位置) | D-5 存档完整性 | 不代填 |
| 6 | **账号枚举口径**(A 维持 409 + 记录例外 / B 改统一响应) | 与 AGENTS「uniform responses」冲突的处置 | A **推荐** |

> 另:上一班(09-29 早班)登记的 **O1/O2/O3 站内 ↔ 法务文本漂移**仍未收口(O1 隐私页仍是"上线前草稿"、O2 站内 `legal.*` 仍是台湾 PDPA 口径、O3 代表人姓名「姜興」与已复核文本「姜爽」不一致),同为 D-1 冻结前阻断项,处置建议见 `docs/release/launch-surface-consistency-2026-09-29.md`。
