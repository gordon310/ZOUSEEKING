# 双历史分叉仲裁报告（Divergence Arbitration）

日期：2026-09-04 · 仲裁执行：Hermes Agent（只读分析） · 决策基线：**origin/main = 唯一权威**（用户 09-04 已确认）
配套附件：`2026-09-04-divergence-file-manifest.txt`（全量文件级清单，933 行）
备份：`backup/workspace-20260904-main / -intake / -originmain`（不可动）

---

## 0. 结论速览

| 判定 | 内容 |
|---|---|
| **基线** | origin/main = `503c22a`（root `349e310` 08-24；远端 + Render 构建源 + 完整 migration 链 11 个） |
| **净值重放** | 约 **88 个文件**从本地线搬入新基线：configs 70 + 数据管道脚本 3 + 规划/设计文档 14 + web/theme.css 1 |
| **丢弃** | 本地 main 分支本身、快照提交 c848b09、0058a02/57762f5 等"重复提交"（净值已在 origin 以更新版本存在） |
| **待评审** | 约 10 项存疑（C 类，见 §4），重放执行时逐项 diff 裁决 |
| **风险点** | ① staging migration 历史不完整（24000xx 链缺失）需单独 reconcile；② 本地工作区 3 个未跟踪文件需先落袋 |

---

## 1. 分叉成因与事实链（实测）

- 两条线**无共同祖先**（root `349e310`=08-24 vs `c848b09`=08-27 "Initial project snapshot"）。
- 推论：08-27 主工作区被重新 `git init` 过一次（progress.md 同日记 "Git 仓库初始化完成"），原始历史只存在于远端链（/private/tmp 与 ~/.codex 的 codex worktrees 曾推送到 origin）。
- 之后两条线**并行发育到 09-02**：origin 线 09-02 06:20 停于 `503c22a`（production release integration baseline，+74 commits）；本地线 09-02 15:59 停于 `8e5b961`（snapshot before shanghai，+13 commits）；09-04 本地线新增 3 个 renovation 文档提交（`0fe29fc`/`47d729e`/`4cb0e62`）。
- **origin 线是超集**（逐目录实证）：backend/app 独有 14 个文件（billing/usage/account_controls/privacy/release_scope），tests 独有 35、supabase migrations 独有 8、docs 独有 34（legal/operations/release/architecture 审计）、scripts 独有 9（ci 门禁/恢复/审计）、src/pipeline.py 独有（33.5KB）、web 独有 215（library 内容 + 法务页）。本地线 backend/app、tests、src **零独有文件**。
- **同内容交叉验证**：三个共享 migration（25000400/27000500/28000100）两边 blob 完全一致 ✓；CLAUDE.md、AGENTS.md、playwright.config.js 字节一致 ✓；src/cli.py origin 含 12 处 data_class 契约 vs 本地 7 处 → origin 更新；web/i18n.js origin 69KB > 本地 64KB → origin 更全。
- 远端现状：`origin/backup/pre-staging-20260825` 亦在 origin 链上（历史三重保险）。

---

## 2. 逐目录裁决（完整文件清单见 manifest）

### A 类 · 必须重放（本地独有净值，88+ 文件）
| 组 | 文件 | 理由 |
|---|---|---|
| configs 数据管道配置 | `configs/jphouse_23ku/`、`jphouse_osaka_wards/`、`jphouse_yokohama_wards/`、`xhs_*` 等 **70 个** | 采集/生成流水线的区域与来源配置，origin 完全没有；与本地版 3 个 builder 脚本同源一致，**整组搬移** |
| 配套 builder 脚本 | `scripts/build_jphouse_23ku.py`、`build_jphouse_osaka_wards.py`、`build_jphouse_yokohama_wards.py`（本地版） | 与 configs 配对；执行时需与 origin 版 diff，确认取本地版或合并（两版 schema 若不兼容以**同源配对**为准） |
| 规划/设计文档 | `docs/superpowers/plans/` 8 个（2026-08-25→08-31）+ `specs/` 4 个 + `ui-review/` 1 个 | 产品验收、权威后端决策、photo-location、production launch master plan 等决策记录，origin 缺失 |
| renovation 计划文档 | `docs/superpowers/plans/2026-09-04-intake-renovation-estimate.md`（来自 3 个 doc commit，实际 1 个文件） | B1×B4 联调（P2）的规格与实施计划 |
| 样式 | `web/theme.css`（16.3KB，本地独有） | 若本地 C 端页面引用则必须随行；执行时 grep 引用确认 |
| .gitignore 增量 | `design-system/zouseeking-frontend/`、`CLAUDE-unzipcontext.md`、`AGENTS-OLD.md`、`CLAUDE-old.md` 4 条 | 合并进 origin 版 .gitignore（origin 版本身已覆盖 web/library、supabase/.temp、.env.* 等更多规则） |

### B 类 · 丢弃（本地线重复内容，净值已在 origin 以更新形态存在）
- 本地 `main` 分支历史整体（快照 c848b09 起的 13 commits **不作 cherry-pick**——无共同祖先，只搬净值文件）。
- `0058a02`（three-role frontend，08-29）≈ origin `056a263`（同日 integrate role surfaces for staging）→ 取 origin（已部署 staging）。
- `57762f5` backend/SQL 提交 → 其目标文件在 origin 均为更新版本（main.py 16.9KB>16.3KB、cli/pipeline 超集、billing/usage 独有）。
- `6a9755b`（ignore web 生成物）→ 规则已含于 origin .gitignore。
- `src/` 本地差异（cli.py 6.4KB 旧版）→ origin 超集，整目录取 origin。
- 后端 20 个 changed 文件 → 全取 origin（本地无独有文件）。

### C 类 · 存疑（执行时逐项裁决，需 Codex + 用户）
1. **本地 web 页面微差**：property-analysis.html / admin.html / project.html / projects.html / ui-review.html 本地比 origin 大几十~200 字节（08-29 本地并行 polish）。规则：diff 审阅，仅当本地版本含 origin 缺失的功能块才取本地，否则取 origin。business-pages.js/css、admin.js 两线**字节相同**，无需处理。
2. **origin 根目录遗留静态副本**：`index.html/app.js/config.js/analysis.html/mypage.html/profile.html/styles.css/content-library.json/field-options.json/library/` 等 13 项在 origin **根目录**残留（web/ 下另有新版，且 .gitignore 已忽略生成物）→ 属陈旧冗余，建议上线前清理（单独 commit，不在重放内）。
3. **`src/pyproject.toml`**（本地独有）：publisher 打包元数据；origin 用 PYTHONPATH 运行。建议保留（无害），或并入 docs 决策。
4. **`Product Ideas.md`、`call_082r1h3YOflkxaSqyzu4MS3.png`、`logoELE.png`**：两张 png 字节数相同（疑似同一文件重复拷贝）。默认**不搬**；如需留档放 docs/ 外。
5. **`scripts/generate_xhs_package.py`、`run_jphouse_worker.py`、`create_report_sample_pdf.py`、`render_social_cards.py`**：两线都有且内容不同（origin 版总体更新）；create_report_sample_pdf/render_social_cards 本地独有 5 脚本之二 → 单独核对是否与 origin 侧 workflow 冲突，能跑通即搬。
6. **origin 侧数据质量/门禁脚本依赖**：`configs/data_quality_policy.json`(origin 独有) 与本地 70 configs 共存无冲突，直接同目录合并。

---

## 3. Migration 专项（含 staging 现状）

| 事实 | 证据 |
|---|---|
| origin 链 11 个 migration 完整（24000100 基线 → 24000700 → 25000400 → 27000500 → 28000100 → 29000100） | ls-tree origin/main |
| 本地树仅 4 个（25000400/27000500/28000100/README），缺 24000xx 链与 29000100 | ls-tree main |
| 三个共享 migration **两边字节一致** | rev-parse blob 对比 = True |
| staging 数据库当前 history：25000400 / 27000500 / 28000100（progress 08-28 记录已应用）；24000100-24000700 与 29000100 在 09-01 dry-run 中显示"待处理" | progress.md + 09-01 release-candidate 记录 |
| 本地未跟踪新 migration：`20260904000100_intake_renovation_observations.sql` + `tests/sql/test_renovation_observations_schema.sql`（装修估算） | git status |

**结论与顺序**：
1. migration 文件本体以 **origin 链为准**（重放后新 main = 11 个 + 搬入 0904 号，共 12 个 + README）。
2. **24000100-24000700 是否要在 staging 补应用**是开放决策：这些是 08-24 基线迁移，staging 库结构可能已由旧 setup 脚本建成 → 直接 push 可能重复建对象失败。必须用 Supabase CLI `migration list` + dry-run 先对账，再由人确认（属 P0.4 的 codex 会话，需要 psql/CLI 权限，Hermes 只读范围外）。
3. 0904 装修估算 migration 在重放落库后、随 B1（P2）联调按 forward-only 应用，**不在仲裁重放中 push 到任何远端 DB**。
4. 规则：已应用的 migration 一律不改写；任何补齐走 forward migration。

---

## 4. 重放执行计划（评审通过后由 Codex 执行）

```
0. 保护（已做）: backup/workspace-20260904-* 三引用 = 今日全部状态
1. 落袋: 在当前分支把 3 个未跟踪文件 commit 到新分支 codex/replay-carryover
   （docs/superpowers/plans/2026-09-04-hermes-bot-orchestration.md
    supabase/migrations/20260904000100_intake_renovation_observations.sql
    tests/sql/test_renovation_observations_schema.sql）
2. git fetch origin（确保 origin/main 最新）
3. git branch codex/divergence-replay origin/main        # 新基线工作分支
4. 净值搬移（文件复制，非 cherry-pick，无共同祖先）:
   a. configs/jphouse_23ku|jphouse_osaka_wards|jphouse_yokohama_wards|xhs_* → 70 文件
   b. scripts/build_jphouse_23ku.py / _osaka_wards / _yokohama_wards（先与 origin 版 diff 裁决 C5）
   c. docs/superpowers/plans+specs+ui-review 本地 13 个 + renovation 计划文档 1 个
   d. web/theme.css（先 grep 引用）
   e. .gitignore 补 4 条；pyproject.toml（C3 默认搬）
5. 分 3 个逻辑 commit: (1) docs 决策文档 (2) configs+builders 数据管道 (3) web/theme.css+gitignore+pyproject
6. 验证（每个 commit 后）: git diff --check / compileall backend scripts src /
   node --check 涉改 web js / 不跑全量 pytest（环境依赖另立步骤）
7. 合并门禁: codex/divergence-replay → 用户评审 diff → merge 进 main（main 先 reset 到 origin/main）
8. 收尾: 推 main 到 origin；本地工作区切 main（未跟踪文件已由 carryover 分支保留）；codex/intake-renovation-estimate 与旧 main 归档为 backup/*（已有），可删
9. 后续独立任务（P0.4/P0.5，另派会话）:
   a. Supabase CLI: migration history 对账 + 24000xx/29000100 决策 + dry-run（不自动 push）
   b. C01-C14 门禁 + 57762f5 净值内容以新 commit 部署 staging（Render 从 main 构建）
```

**明确不做（No-Go）**：不 merge 双线；不对本地 13 commits 逐个 cherry-pick（快照提交无意义）；不 force-push 改写 origin/main；不在重放中触碰任何远端数据库/部署；不动 backup/workspace-20260904-*；不删除用户工作区现有文件（3 个未跟踪文件先落袋再搬）。

---

## 5. 红线复核

- 数据字段冻结：本次仲裁**零字段改动**，只搬文件与文档；0904 migration 保持 forward-only 待 B1 联调应用。
- 生产（production Supabase / Render prod）自始至终未触碰。
- 本报告与 manifest 均为只读分析产物（新文件，未改任何既有文件）。

---

## 6. 待用户/Codex 决策清单（C 类汇总）

1. 本地 web 6 页微差 → 执行时 diff 裁决（默认取 origin，除非本地含独有功能块）
2. origin 根目录 13 个陈旧静态副本 → 是否清理（建议：上线前清理 commit）
3. Product Ideas.md / 两张重复 logo → 默认不搬
4. staging 是否补应用 24000100-24000700 基线链 → Supabase CLI 对账后人工确认
5. pyproject.toml / create_report_sample_pdf / render_social_cards → 默认搬，diff 后确认
