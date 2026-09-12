# ZOUSEEKING 前端 i18n 清理与 `?lang=` 任务报告

日期：2026-09-12

## 1. A：裸中文字面量清单与处理

本轮按任务中列出的真实浏览器缺陷，核查 C 端分析入口、报告页，以及 B 端登录/注册共用文案。C 端分析页原先的裸可见文案集中在 `web/property-analysis.html:43-353`，包括菜单、流程步骤、用途选择、物件类型、照片/文件上传、字段确认、免费预览、保存项目和侧栏摘要；现均改为 `data-i18n`、`data-i18n-placeholder` 或 `data-i18n-aria-label`。

处理清单（同类重复节点合并列出）：

| 文件:行号（当前） | 原文类别/示例 | 处理方式 |
|---|---|---|
| `web/property-analysis.html:43-60` | 打开菜单、快捷导航、回到小象数据、前端流程评审 | 纳入 `intake.*` i18n；品牌名小象数据保留为品牌/既有业务品牌 |
| `web/property-analysis.html:65-91`、`349-353` | 界面评审模式、流程步骤、选择用途、提交资料、确认字段、免费预览、注册保存 | 纳入 i18n；`synthetic_fixture` 保留为技术/数据类标识 |
| `web/property-analysis.html:81-140` | 分析一个日本物件、正文说明、用途、物件类型、链接/说明、输入示例 | 纳入 i18n；日文业务术语“物件”沿用既有术语 |
| `web/property-analysis.html:149-199` | 拍照、照片位置、上传文件、隐私说明、提交按钮 | 纳入 i18n；文件扩展名、20MB、EXIF 等技术标识保留 |
| `web/property-analysis.html:221-269` | 确认字段、状态、位置建议、价格/面积/地址字段、预览按钮 | 纳入 i18n；数值示例通过 placeholder 键本地化 |
| `web/property-analysis.html:276-341` | 免费预览、注册保存、进度侧栏、关键信息、法律与交易资料 | 纳入 i18n；`✓`、百分比和计数属于 UI 符号/动态数值，保留 |
| `web/report.html:13-65` | 报告标题、报告正文占位、语言选择器 | 页面已有 i18n 标记；修复统一初始化优先级，不新增第二套机制 |
| `web/js/i18n.js:59` | “注册很简单，别紧张，不查户口” | 保留语义，修正由繁体转换产生的混用，繁体输出为“註冊很簡單，別緊張，不查戶口” |
| `web/js/i18n.js:2062-2070` | 简繁转换词表 | 补齐简单、别、户口及本轮 C 端文案所需台湾用字 |

品牌名 `小象避坑`、`ZOUBEACON`、`小象数据`、`ZOUSEEKING`、`小象` 未翻译。URL、扩展名、EXIF、`synthetic_fixture`、数值示例和注释未作为可见本地化文案处理。

## 2. B：i18n 改动

- `web/property-analysis.html` 的可见正文、表单标签、placeholder、aria-label 全部接入既有 i18n 属性机制。
- `web/js/i18n.js` 新增 `intake.*` 键，并为 `zh-CN`、`en`、`ja` 提供完整值；`zh-Hant` 继续由同一 `zh-CN` 键集合生成，因此四语言键集合一致。
- 繁体转换补齐台湾用语：設定、資料、登入、註冊、檔案、下載，以及本轮发现的簡單、別、緊張、戶口、綁定、潛在、風險、決策等。

## 3. C：报告页 `?lang=` 根因与修复

根因在 `web/js/i18n.js:2097-2099`：原逻辑先返回合法的 `savedLocale`，之后才读取 `urlLang`。当浏览器已有 `zou_ui_locale=zh-CN` 时，`report.html?lang=zh-Hant` 会被 localStorage 覆盖；报告页 `web/report.html:65` 虽加载了同一 `js/i18n.js`，所以表现为 URL 参数不生效。

修复为显式 URL 参数优先：`urlLang` → `savedLocale` → 浏览器语言/时区。localStorage 记忆机制仍保留，语言切换仍由 `setLocale()` 写回存储。

## 4. D：可复现自检证据

### 裸中文扫描

```bash
node scripts/ci/check_frontend_i18n.mjs
```

结果：

```text
baseline bare Chinese lines: 101
current bare Chinese lines: 0
PASS: scanned C-end analysis and report pages contain no bare visible Chinese lines.
```

脚本扫描 `web/property-analysis.html` 与 `web/report.html`，排除品牌、metadata、语言选项和已有 i18n 属性；基线由 `git show HEAD:<file>` 读取。

### 四语言键集与繁体回归

```bash
node --test tests/unit/i18n.test.js
```

结果：6 tests passed，覆盖 `zh-Hant` 与 `zh-CN`、`en`、`ja` 键集一致，placeholder 一致，浏览器语言映射，URL 参数优先级，以及台湾繁体关键文案。

### JavaScript 语法

```bash
node --check web/js/i18n.js
node --check scripts/ci/check_frontend_i18n.mjs
```

两项均通过。

### 浏览器实跑

本轮未启动真实浏览器/HTTP 预览服务；因此没有把浏览器视觉结果冒充为已验证。已提供静态初始化证据和 Node 回归测试，报告页 URL 参数的真实浏览器补验仍由 Hermes 完成。

### 工作树

未执行 commit 或 push。最终 `git status --short` 应仅包含本任务涉及的测试、i18n、分析页、扫描脚本和本报告文件；任何任务前既有用户改动均未覆盖。
