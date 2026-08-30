# JP Property Graphic Skill

版本：`0.1.1`（location-capture-zoubeacon）

这是可交给其他项目调用的 Skill 包。当前版本用于日本房产现场拍照、用户授权设备定位、反向地址记录和项目持久化；不调用 OpenAI，不需要 `OPENAI_API_KEY`，不执行 GeoCLIP 或图库识别。已包含 ZOUBEACON / JPPropDIs 的 FastAPI 接入适配说明。

## 安装到项目

把整个 `jp-property-graphic` 目录复制到目标项目的 `.agents/skills/` 下：

```bash
cp -R jp-property-graphic /path/to/your-project/.agents/skills/
```

在支持 Skill 的项目中使用：

```text
Use $jp-property-graphic to process a Japanese property photo capture and preserve the user-authorized GPS/address metadata.
```

宿主项目仍需自己实现相机、浏览器权限、定位、API 和数据库。字段、端点、失败状态及手机 HTTPS 要求见 [references/integration.md](references/integration.md)。

## 包内容

- `SKILL.md`：Skill 入口和当前/后续能力边界。
- `agents/openai.yaml`：展示信息、默认调用提示和隐式调用策略。
- `references/integration.md`：v0.1.0 的宿主接入契约。
- `references/zoubeacon.md`：ZOUBEACON / JPPropDIs 的 FastAPI、Supabase 和定位接口映射。
- `references/input-output.md`：后续静态图片分析的结构化输入输出协议。
- `references/property-analysis.md`：后续位置核验规则。
- `references/renovation-estimate.md`：后续装修估算规则。

当前发布验证包括 Skill 元数据、接入端点、字段约束和调用入口检查；宿主 Web 应用的测试与构建仍在项目根目录执行。
