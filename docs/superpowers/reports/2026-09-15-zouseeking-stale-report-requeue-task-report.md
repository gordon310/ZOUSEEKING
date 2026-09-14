# ZOU SEEKING 僵尸报告重入队任务报告

## 改动清单

- `backend/app/main.py`
  - `cached_report_action` 增加 `insufficient_data + completed/succeeded -> cache`。
  - 终态任务 `completed/succeeded` 且报告不是已发布终态时返回 `requeue`。
  - 原有重入队更新允许 `failed/completed/succeeded`，继续清空错误、置 `pending`，并沿用 advisory lock 与调度路径。
- `tests/unit/test_report_generation_contract.py`
  - 覆盖已发布、合法数据不足、pending、running、failed 和 `completed + generating` 分支。

未修改 source_id 解析、slug 命名空间或 migration。工作树中的其它既有改动均保留。

## 分支判定表

| report_status | job_status | action |
|---|---|---|
| `full_report` | 任意 | `cache` |
| `insufficient_data` | `completed` / `succeeded` | `cache` |
| 任意 | `pending` / `running` | `wait` |
| 任意 | `failed` | `requeue` |
| 未发布态（包括 `generating`） | `completed` / `succeeded` | `requeue` |

## 验证证据

### 修复前离线回归

新增测试真实失败，证明旧实现将两个关键分支判错：

```text
8 passed, 2 failed
E       AssertionError: assert 'wait' == 'cache'
E       AssertionError: assert 'wait' == 'requeue'
```

其中失败分支分别是 `completed + insufficient_data`（实际 `wait`）和 `completed + generating`（实际 `wait`）。

### 修复后

```text
PYTHONPATH=. backend/.venv/bin/pytest tests/unit/test_report_generation_contract.py -q
..........                                                               [100%]
10 passed in 0.32s
```

仓库既有全量 Python 测试命令：

```text
PYTHONPATH=. backend/.venv/bin/pytest -q
518 passed, 86 skipped in 5.35s
```

其它离线检查：

```text
compileall: passed
node --check web/app.js: passed
git diff --check: passed (no output)
pip check: failed
wheel 0.47.0 requires packaging, which is not installed.
```

## 线上端到端与清理

未执行。当前 shell 没有 staging 数据库/API/Supabase 凭据或连接地址，无法真实造出临时用户数据、调用 staging 的 `create_or_get_query_job`、观察 `requeue -> full_report`，也没有可清理的本轮线上数据。

因此没有伪造以下要求的线上输出：

```text
修复前: 返回 wait / 报告 generating
修复后: requeue / 报告 full_report
```

清理计数：`0`（本轮未创建线上数据）。任务书指定的 4 行僵尸报告未读取、未修改、未删除。

## NOT_EXECUTED

- staging 临时用户造数、真实 `create_or_get_query_job` 端到端重入队与最终 `full_report` 断言。
- staging 临时数据清理与线上清理计数（因未造数，计数为 0）。

## 工作树状态

`git diff --check` 干净。`git status --porcelain` 仍包含任务开始前已存在的改动，按要求未触碰：

```text
 M backend/app/intake/market_engine.py
 M backend/app/main.py
 M docs/architecture/schema-ownership.json
 M tests/architecture/test_schema_ownership_audit.py
 M tests/unit/test_report_generation_contract.py
?? supabase/migrations/20260915000200_owner_scoped_report_slugs.sql
```

本轮新增/修改的任务文件为 `backend/app/main.py`、`tests/unit/test_report_generation_contract.py` 和本报告；未执行 commit、push、部署或 SSH。
