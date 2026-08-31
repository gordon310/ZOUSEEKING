# C16 会员与账户控制离线契约

状态：offline candidate（不构成 staging 或 production 上线批准）

日期：2026-09-01

## 目标

为后续唯一 FastAPI 私有产品边界建立可测试的账户控制契约。当前只提供纯函数和静态页面行为，不写入真实会员、机构、支付、任务、联系信息或数据库迁移。

## 已落地的边界

- `backend/app/account_controls.py` 只接受用户可编辑资料字段：`display_name`、`city`、`favorite_area`、`favorite_asset_type`、`bio`。
- `user_id`、邮箱、用户名、会员等级、额度、机构归属、机构角色、合作方状态和后台角色等字段均视为服务端管理字段，浏览器资料 patch 不得提交。
- 密码基线为 12–128 个字符，拒绝控制字符；密码哈希和会话签发仍由 Supabase Auth 负责。
- 凭据错误、账户不可用等认证失败使用统一的非枚举响应；前端不再创建或读取 `localStorage` 本地密码凭据。
- 账户资料读取/编辑只在已有 Supabase Auth 会话且非 demo-only 页面下走现有兼容路径；第一阶段 demo-only 页面不访问私有 profile 表，缺少权威账户接口时不提交资料。
- 敏感设置变更需要 15 分钟内的时区明确的近期认证。
- B 端机构最多 5 个活跃成员；只有 `owner` 管理账单并邀请成员，`member` 只有被指定为任务负责成员时才能查看匹配联系信息。
- 内部角色按最小权限拆分；套餐不会授予后台角色，`super_admin` 才能分配后台角色。

## 未执行与发布闸门

- 未新增或应用 `supabase/migrations/` 业务迁移，未执行 live reconciliation、RLS/Auth/Storage 写入、provider backup/clone、部署、DNS 或计费操作。
- 真实组织表、成员席位、会员权益、配额扣减、账户删除/恢复、近期认证证明和后台审计日志仍需在基线 reconciliation 完成后另立 forward migration 与 UAT。
- `localStorage` 中历史 `zou_house_session` 仅可作为既有演示/会话线索；没有 Supabase Auth access token 时不得访问私有 API 或资料表。
- 因此 C14 Go/No-Go 仍为 `BLOCK / NOT AUTHORIZED`，本契约不能把项目标记为 production-ready。

## 验证

```bash
env PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit/test_account_controls.py -q
./node_modules/.bin/playwright test tests/web/account-controls.spec.js --project=chromium
```

两组测试均只使用本地 fixtures；浏览器测试验证未配置 Supabase 时注册/登录不会创建或消费本地密码凭据。
