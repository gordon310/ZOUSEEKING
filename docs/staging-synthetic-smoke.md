# C13 staging synthetic smoke

本工具是 C13 的离线载体，不是 staging 已验收的声明。C13 的 Done when 是：synthetic smoke 数据和 Storage objects 清理为 0；API、Web、ready 指向同一候选 commit；没有未解释的浏览器 console/network 请求；staging 证据包完整；Go/No-Go 清单只剩 production 授权动作。

## 离线计划与自检

默认命令完全不联网、不创建 socket，读取本地 `HEAD` 和
`deploy/frontend-version.txt` 后打印候选、白名单、每个小型 fixture 的字节数
与 SHA-256、端点清单和清理计划：

```bash
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --plan
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --self-check --evidence-out /tmp/c13-self-check.json
```

`--self-check` 使用内置 fake transport，覆盖全部十个固定 case；它不能替代任何
staging 观察结果。裸运行 `--self-check` 只将证据 JSON 打印到 stdout，不写任何
文件；仅在显式提供 `--evidence-out <path>` 时才会写出。canonical 证据文件
`docs/release/phase-one-staging-evidence.json` 只允许 `--execute` 的真实
`authorized_staging` 运行写入，self-check 或其它非 execute 路径指定该文件会以
exit 2 被拒绝。

## 真实 staging 运行（须另行用户授权）

在得到一次性、明确的 staging 写入授权前，**不得**运行 `--execute`。授权应明确：

- 目标必须是 project ref `fnogxuytbabxmqousifh`，且 API/Web 只能是工具内白名单
  的 HTTPS staging host；production host 会被拒绝。
- 确认 candidate commit、`deploy/frontend-version.txt` 的版本、允许创建的对象和
  清理窗口；最大三份 PDF/JPG/PNG fixture 各不超过 64 KiB，另有 text、`.invalid`
  URL、位置拒绝和 geocoder 失败输入。不会使用真实客户资料、姓名、电话、邮箱、
  文件或真实 URL。
- 允许工具创建一个临时 intake session、相关 synthetic inputs 和最多三个私有
  fixture objects；finally 中会逐一尝试删除 object、session 与相关行，再读回
  计数。若服务不支持所需删除/读回路由，证据会列为 limitation 且 cleanup 不会被
  标记 verified。
- 在受控 shell 中仅提供以下环境变量的值，不要写入命令行、证据或仓库：
  `SMOKE_ANON_KEY`、`SMOKE_OWNER_TOKEN`、`SMOKE_OTHER_TOKEN`。

授权后才可运行：

```bash
backend/.venv/bin/python scripts/staging_synthetic_smoke.py --execute --allow-staging --authorized-writes
```

该命令会先抓取 staging `index.html` 的 `?v=` 值，与候选 frontend version 比对；
不一致时证据 `frontend_version_match=false` 且最终为 fail，但仍进入 finally 清理。
十个 case 固定为 `text_input`、`url_input`、`pdf_upload`、`jpg_upload`、
`png_upload`、`location_denied`、`geocoder_failure`、`expiry_cleanup`、
`cross_user_denied`、`idempotent_preview`。免费 preview 会记录可诊断的判定口径：

- 资料不足信号满足任一即可：`completeness` 任一维度的 `status` 为
  `insufficient_data`、`partial` 或 `empty`，`acquisition_costs.status` 为
  `insufficient_input`，或顶层存在 `insufficient_data_status` 或
  `data_sufficiency_status`。
- 递归查找响应中全部 `data_class` 并在 evidence 记录路径。若不存在，只可在
  `comparable.reference` 是空数组且响应没有 `tax_total` 时通过，原因记录为
  `preview carries no market reference rows`。
- 必须存在 `comparable_status`，且仅可为 `not_checked`、`insufficient` 或
  `sufficient`；其实际值会记录在 evidence。若为 `sufficient`，
  `comparable.reference` 的每行都必须带 `data_class`。工具始终拒绝
  `tax_total`、`full_report` 或 `report_conclusion`。

## 浏览器审计

脚本不导入 Playwright，也不执行浏览器自动化。对已部署 candidate 在用户授权的
审计环境运行并将脱敏后的结果传入 `--browser-evidence`：

```bash
npx playwright test tests/web/release-scope.spec.js
npx playwright test tests/web/property-intake.spec.js
npx playwright test tests/web/pwa-shell.spec.js
```

审计应逐项记录 desktop、390x844、键盘操作、200% 与 400% zoom、reduced-motion，
以及 console error/warning 和所有 network 请求。未传 `--browser-evidence` 时，
evidence 的 `browser_audit.status` 为 `not_executed`，并列出以上待跑命令。

## 已知限制与未执行项

本仓库交付的是离线运行载体和 `NOT_EXECUTED` 骨架；尚未取得 staging 写入、浏览器
审计或真实 cleanup/readback 的授权与证据。不能把 self-check、local tests 或本文件
当作 staging 通过，更不能当作 production 证据。
