# PWA 候选本地验收（2026-10-05）

本批承接 UX 审计改动与上线闭环 L01/L03/L04。候选分支为 `codex/ux-simplification`，统一前端版本 `20261005-r68`。未部署、未修改生产 DB/Auth/Storage/支付或 provider 配置；本地通过不代表最终 Go。

## 已交付

- nginx 三静态站点对 `/sw.js` 采用精确 location 再验证，manifest 同样再验证；普通带版本静态资源仍保留原 immutable 策略。
- PWA 捕捉表单 input/change，已变更表单不自动刷新；清洁页面和会话内至多一次自动刷新逻辑保留。
- 使用既有 `version-frontend-assets.py` 统一部署版本、所有 HTML、模块引用和 SW 版本，再从可读源生成资产。
- 将回跳安全与 PWA 输入保护 Node 单测加入既有 CI node-syntax 检查。
- 已审定代表姓名「姜爽」同步至三基础语言/繁中派生和隐私页回退文字，O3 已移除开口声明；O1/O2 保持 OPEN。

## 实测结果

| 验证 | 结果 |
|---|---|
| 全套 Chromium：`npx playwright test --project=chromium --workers=2` | **139 passed** |
| 发布/资产/缓存/法务门禁聚焦 pytest | **31 passed** |
| `node tests/unit/pwa-reload.test.cjs` | PASS：失焦后未保存表单不刷新，清洁页及离线行为 |
| `node tests/unit/auth-return.test.cjs` | PASS |
| `npm run check:web-assets` | PASS |
| `python3 deploy/version-frontend-assets.py --check` | PASS，0 file drift |
| release policy / secret scan / git diff --check | PASS |
| 临时 nginx 容器：3 host × sw/manifest/普通JS | **9 HTTP 检查 PASS**；SW/manifest no-cache，manifest MIME正确，普通JS immutable；容器与测试证书清理 |
| 法务一致性门禁 | OPEN：只剩 O1/O2，未伪报 PASS |

pytest 聚焦命令：

```bash
python -m pytest tests/unit/test_launch_surface_consistency.py tests/unit/test_frontend_version_script.py tests/architecture/test_frontend_asset_version_contract.py tests/architecture/test_pwa_cache_contract.py tests/architecture/test_release_gate_contract.py -q
```

## PWA 验收边界

真实 Chrome Service Worker 实测了：当前脚本在 worker 升/降版本时不丢失已更改表单；断网消费者壳可见，恢复联网后可用；私有 API fixture 不入 Cache Storage，离线读取失败；保存的真实 r67 页面脚本和 worker 首次升级至候选时，清洁页面只刷新一次。

当前 dirty guard 无法追溯保护仍在运行的旧 r67 页面脚本。已有用户应先保存资料，再刷新/重新打开以加载新版。尚未验证实际设备后台唤醒、真实 r67 全站旧缓存资产、真实 nginx/CDN 线上头或完整线上回滚。临时 nginx 测试使用本地自签测试证书，仅证明配置运行时行为。

## 未关闭

L01：日本政策正文/生效日/同意版本与退会/主动删除对应决定，详见 `legal-site-sync-review-2026-10-05.md`。
L02：独立 staging 标识与恢复范围；未运行共享项目上的写入 smoke。
L03：本地候选已统一，尚需整合至权威 main、候选远程完整 CI及产物证据。
L04：代码与本地验收完成，尚需实际发布环境/真机更新和回滚证据。
L05–L09：真机、真实交易权限、值守/恢复、最终放行及上线观察依台账执行。

独立只读审查未发现本轮新增 Important/Critical，明确了当前脚本与历史脚本的迁移覆盖差异；已补历史 r67 测试。未将旧版生产 release_ready 状态重写为新候选通过。
