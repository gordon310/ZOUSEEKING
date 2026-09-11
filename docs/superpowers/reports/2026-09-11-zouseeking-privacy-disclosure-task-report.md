# [Superseded] ZOUSEEKING 照片识别隐私披露任务报告

> Superseded on 2026-09-11: the product decision changed to EXIF-only location prefill; listing-photo AI recognition is not launched.

日期：2026-09-11

新增长的法律文本均标注“待法务/负责人确认”，不表示已生效。

## 1. 数据留存事实

### `/api/recognition` 与 FastAPI

- `backend/app/recognition/routes.py:31-41` 认证后校验请求，并把 `validated.image` 传给 `service.analyze`；未见落盘、数据库或 Storage 写入。
- `backend/app/recognition/service.py:48-66` 将 data URL 放进发往 JPPGSKILL `/api/analyze` 的 JSON 请求；该文件没有文件、数据库或 Storage 写入。
- `backend/app/recognition/routes.py:42-57` 只把上游结果筛选后返回；识别相关代码中没有记录图片内容或 data URL 的 logger/console 调用。运行环境的网关/服务器访问日志是否记录请求体，未由本仓库确认。

### JPPGSKILL

- `JPPGSKILL/server/api.mjs:165-169` 的 `/api/analyze` 校验请求后直接调用 `analyze`，没有调用 `store`。
- `JPPGSKILL/server/index.mjs:64-75` 将该 `analyze` 实现绑定为 `callOpenAI`；`JPPGSKILL/server/openaiAnalysis.mjs:183-204` 构造视觉请求，并设置 `store: false`。
- JPPGSKILL 的独立项目照片流程确实有 SQLite 持久化：`JPPGSKILL/server/database.mjs:70-95` 建立 `photos.image_data` 与 `projects.analysis_json`，`JPPGSKILL/server/database.mjs:124-150` 写入照片和分析结果。该流程不是当前 FastAPI `/api/recognition` → `/api/analyze` 路径。
- 仓库中未找到该独立 SQLite 照片/分析记录的自动过期策略；OpenAI 服务端实际保存和删除期限也未由本仓库确认。

一句话结论：当前 `/api/recognition` 识别链路的照片不会按核验到的 FastAPI 或 JPPGSKILL `/api/analyze` 代码持久化到本地文件/SQLite，而是临时转发给 OpenAI（请求设置 `store:false`）；OpenAI 侧保存多久未确认，JPPGSKILL 独立项目照片流程会把照片和分析结果写入 `data/jp-property-graphic.sqlite`，其自动过期时间未确认。

## 2. 隐私政策新增文本（待法务/负责人确认）

### `web/privacy.html` 原文

> 拍照识别的第三方处理（待法务/负责人确认）
>
> 使用“拍照识别挂牌”时，你主动上传的照片会通过本站识别接口发送给第三方 AI 服务 OpenAI，用于识别挂牌和房产要素；照片可能跨境传输至你所在国以外、美国的服务器。当前代码核验到的识别路径中，本站 FastAPI 与 JPPGSKILL 的 `/api/analyze` 不把照片或该次分析结果写入本地 SQLite；OpenAI 服务端的实际保存期限和删除执行情况未由本仓库确认。你可以不使用此功能；不使用不会影响其他功能。请勿上传含身份证件等敏感信息的图片。查阅、更正、删除等权利和联系方式沿用下方“保留、删除和权利”及“联系”段落。

### `docs/legal/privacy-policy.md` 原文

> 拍照识别的第三方处理（待法务/负责人确认）
>
> 使用“拍照识别挂牌”时，用户主动上传的照片会通过本站识别接口发送给第三方 AI 服务 OpenAI，用于识别挂牌和房产要素；照片可能跨境传输至用户所在国以外、美国的服务器。当前代码核验到的识别路径中，本站 FastAPI 与 JPPGSKILL 的 `/api/analyze` 不把照片或该次分析结果写入本地 SQLite；OpenAI 服务端的实际保存期限和删除执行情况未由本仓库确认。用户可以不使用此功能；不使用不会影响其他功能。请勿上传含身份证件等敏感信息的图片。查阅、更正、删除等资料主体权利和联系方式沿用第 5、6 节。

`web/privacy.html` 当前为 `zh-CN` 单语言页面，没有语言切换器，因此没有新增英/日隐私政策段落；识别上传处的告知和同意文案已通过 `web/js/i18n.js` 补齐中文、English、日本語。

## 3. 前端告知与同意

- `web/property-analysis.html:196-203` 增加第三方 OpenAI、美国跨境传输、敏感图片警告、必选同意 checkbox，并用 `aria-describedby` 关联告知文本。
- `web/js/recognition.js:18-20,107-108,134-136` 初始禁用识别按钮；勾选后启用；`recognize()` 在任何 `fetch` 前再次校验同意，未同意时不发请求。
- `web/js/i18n.js:151-153,602-604,1053-1055` 增加三语言 disclosure、consent label 和未同意提示。
- 未修改既有图片压缩、`POST /api/recognition` 请求体、候选渲染或预填逻辑。

## 4. 测试与自检

- `backend/.venv/bin/python -m pytest tests/api/test_recognition_routes.py tests/unit/test_privacy_contracts.py -q` → `9 passed`。
- `node --check web/js/recognition.js && node --check web/js/i18n.js` → 通过。
- `PYTHONPYCACHEPREFIX=/tmp/jp-property-pycache python3 -m compileall -q backend scripts src` → 通过。
- `git diff --check` → 通过。
- 静态结构断言 → 8 项全部 `PASS`，覆盖 checkbox、告知文案、三语言 key、初始禁用、fetch 前守卫和两份隐私政策的 OpenAI 文案。
- `npm run test:web -- --project=chromium tests/web/recognition.spec.js --workers=1` → 未能启动测试服务器：Python `http.server` 绑定 `127.0.0.1:8787` 被当前环境拒绝，报 `PermissionError: [Errno 1] Operation not permitted`。因此本轮没有获得真实浏览器网络监听结果；Playwright 用例已加入“未勾选无 POST、勾选后有 POST”的断言。

要求的 grep：

```text
web/privacy.html:34: ... OpenAI ...
docs/legal/privacy-policy.md:24: ... OpenAI ...
web/js/i18n.js:151: ... OpenAI ...
web/js/i18n.js:152: ... OpenAI ...
web/js/i18n.js:602: ... OpenAI ...
web/js/i18n.js:603: ... OpenAI ...
web/js/i18n.js:1053: ... OpenAI ...
web/js/i18n.js:1054: ... OpenAI ...
```

`git status --short`（未执行 commit/push）：

```text
 M backend/app/main.py
 M deploy/.env.example
 M deploy/README.md
 M deploy/docker-compose.prod.yml
 M docs/legal/privacy-policy.md
 M web/app.js
 M web/js/i18n.js
 M web/privacy.html
 M web/property-analysis.css
 M web/property-analysis.html
?? backend/app/recognition/
?? deploy/.gitignore
?? deploy/jpsskill.env.example
?? docs/superpowers/plans/2026-09-11-privacy-disclosure.md
?? docs/superpowers/reports/2026-09-11-zouseeking-privacy-disclosure-task-report.md
?? tests/api/test_recognition_routes.py
?? tests/web/recognition.spec.js
?? web/js/recognition.js
```
