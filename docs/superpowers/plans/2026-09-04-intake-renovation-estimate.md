# 免费预览接入装修成本估算（室内状况观察）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ZOUBEACON C 端匿名 intake 的确认字段步骤加入可选的室内状况观察，生成免费预览时由服务端用现有装修定价规则计算 JPY 概算区间，并将结果随预览快照持久化与展示。

**Architecture:** 扩展 intake 会话域（`asset_type` 列、`renovation_observations` 表、`free_previews.renovation_estimate` 列）；前端确认页收集“房间/项目/状况/处理范围/数量或面积/可选照片证据”，整组 PUT 到 FastAPI；预览接口读取字段+观察后在进程内调用 `backend/app/renovation/pricing.build_estimate()`，再写预览快照。前端不直接调用 `/api/renovation/*`。

**Tech Stack:** Python 3.12、FastAPI 0.116、asyncpg、PostgreSQL/Supabase、vanilla HTML/CSS/ES modules、pytest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-04-intake-renovation-estimate-design.md`

## Global Constraints

- 只提交代码与 forward migration；**不**将 migration 应用到 staging/production。
- 日元是唯一金额口径，不换算币种；价格快照 `jp-renovation-2026-08-31-v1` 与来源保持只读，本计划不修改 `backend/app/renovation/`。
- 观察不进入六维完整度，不产生“当前资料提醒”；只有“更换/表面刷新”进入金额区间。
- 墙纸/地板（`m2` 项目）必须提供 `area_m2`；整体卫浴/厨房/厕所/洗面台按 `quantity`；畳按 `quantity`（张数）。不静默推造面积。
- 同一会话同一房间同一项目只有一行；客户端观察行整组替换服务端数据。
- 观察证据照片只能引用同会话、`input_type='image'` 的 `project_inputs`。
- demo 页面任何估算展示都必须标记 `synthetic_fixture`。
- SQL/RLS 在本机无 PostgreSQL 时记录 `NOT_EXECUTED`，不得记为通过。

---

### Task 1: 数据库 forward migration 与 schema 断言

**Files:**
- Create: `supabase/migrations/20260904000100_intake_renovation_observations.sql`
- Create: `tests/sql/test_renovation_observations_schema.sql`
- Modify: `data/../docs/../supabase/migrations/20260825000400_property_intake.sql`（只读参考，不改）

**Interfaces:**
- Consumes: migration 004 已创建的 `analysis_sessions`、`project_inputs`、`free_previews` 与 trigger 函数 `public.set_intake_updated_at()`。
- Produces: 数据库列 `analysis_sessions.asset_type`、表 `renovation_observations`、列 `free_previews.renovation_estimate`。

- [ ] **Step 1: 编写 migration 文件**

```sql
-- Intake renovation observations: optional user-asserted interior condition
-- rows feeding the free-preview renovation estimate snapshot.
alter table public.analysis_sessions
  add column if not exists asset_type text
  check (asset_type is null or asset_type in ('apartment', 'tower', 'detached_house', 'other'));

create table if not exists public.renovation_observations (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.analysis_sessions(id) on delete cascade,
  room text not null,
  component text not null,
  condition text not null default 'unknown',
  scope text not null default 'unknown',
  quantity numeric not null default 1 check (quantity > 0),
  area_m2 numeric check (area_m2 is null or area_m2 > 0),
  notes text not null default '',
  evidence_input_id uuid references public.project_inputs(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint renovation_observations_room_allowed check (room in (
    'exterior', 'bathroom', 'kitchen', 'living_room', 'bedroom', 'balcony'
  )),
  constraint renovation_observations_component_allowed check (component in (
    'unit_bath', 'wallpaper', 'flooring', 'kitchen', 'toilet', 'washstand', 'tatami'
  )),
  constraint renovation_observations_condition_allowed check (condition in (
    'new', 'good', 'aged', 'worn', 'stained', 'damaged',
    'mold_or_stain', 'water_damage_suspected', 'unknown'
  )),
  constraint renovation_observations_scope_allowed check (scope in (
    'replace', 'surface_refresh', 'repair', 'monitor', 'unknown'
  )),
  constraint renovation_observations_unique_scope unique (session_id, room, component)
);

create index if not exists idx_renovation_observations_session
  on public.renovation_observations(session_id, room);

alter table public.renovation_observations enable row level security;

revoke all on public.renovation_observations from anon, authenticated;

drop trigger if exists set_renovation_observations_updated_at on public.renovation_observations;
create trigger set_renovation_observations_updated_at
before update on public.renovation_observations
for each row execute function public.set_intake_updated_at();

alter table public.free_previews
  add column if not exists renovation_estimate jsonb;
```

- [ ] **Step 2: 编写 schema 断言**

```sql
-- Renovation-observation intake schema assertions.
-- Run against a disposable Supabase/PostgreSQL database only.
do $$
declare
  required_constraint text;
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'analysis_sessions'
      and column_name = 'asset_type'
  ) then
    raise exception 'missing analysis_sessions.asset_type column';
  end if;

  if to_regclass('public.renovation_observations') is null then
    raise exception 'missing renovation_observations table';
  end if;

  if not exists (
    select 1 from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relname = 'renovation_observations'
      and c.relrowsecurity
  ) then
    raise exception 'RLS disabled for renovation_observations';
  end if;

  if exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'renovation_observations'
      and roles::text like '%anon%'
  ) then
    raise exception 'anonymous REST policy exists on renovation_observations';
  end if;

  foreach required_constraint in array array[
    'renovation_observations_room_allowed',
    'renovation_observations_component_allowed',
    'renovation_observations_condition_allowed',
    'renovation_observations_scope_allowed',
    'renovation_observations_unique_scope'
  ] loop
    if not exists (
      select 1 from pg_constraint where conname = required_constraint
    ) then
      raise exception 'missing renovation constraint: %', required_constraint;
    end if;
  end loop;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public'
      and table_name = 'free_previews'
      and column_name = 'renovation_estimate'
  ) then
    raise exception 'missing free_previews.renovation_estimate column';
  end if;
end $$;
```

- [ ] **Step 3: 语法与提交前检查**

```bash
git diff --check
```

- [ ] **Step 4: 尝试本机 SQL 回归（预期 NOT_EXECUTED）**

```bash
backend/.venv/bin/python scripts/run_sql_file.py tests/sql/test_renovation_observations_schema.sql 2>&1 || true
```

若因无本地 PostgreSQL 无法运行，在终端记录 `NOT_EXECUTED`，不伪造通过。

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260904000100_intake_renovation_observations.sql tests/sql/test_renovation_observations_schema.sql
git commit -m "feat: add renovation observation intake migration and schema assertions"
```

---

### Task 2: intake Pydantic 契约（asset_type 与观察请求/响应）

**Files:**
- Modify: `backend/app/intake/models.py`
- Test: `tests/unit/test_intake_models.py`

**Interfaces:**
- Consumes: `backend/app/renovation/models.py` 的 `Component`、`Condition`、`Room`、`Scope` Literal 别名。
- Produces: `CreateSessionRequest.asset_type`、`CreateSessionResponse.asset_type`、`RenovationObservationInput`、`SaveRenovationObservationsRequest`、`RenovationObservationView`、`FreePreviewResponse.renovation_estimate`。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_intake_models.py` 末尾追加：

```python
from backend.app.intake.models import (
    RenovationObservationInput,
    SaveRenovationObservationsRequest,
)


def test_session_accepts_optional_asset_type():
    request = CreateSessionRequest(
        purpose="self_use",
        consent_version="privacy-2026-08",
        asset_type="tower",
    )
    assert request.asset_type == "tower"

    with pytest.raises(ValidationError):
        CreateSessionRequest(
            purpose="self_use",
            consent_version="privacy-2026-08",
            asset_type="mansion",
        )


def test_wallpaper_observation_requires_area():
    valid = RenovationObservationInput(
        room="living_room",
        component="wallpaper",
        condition="stained",
        scope="surface_refresh",
        area_m2=20,
    )
    assert valid.area_m2 == 20

    with pytest.raises(ValidationError):
        RenovationObservationInput(
            room="living_room",
            component="wallpaper",
            condition="stained",
            scope="surface_refresh",
        )


def test_unit_bath_observation_uses_quantity_and_rejects_area():
    valid = RenovationObservationInput(
        room="bathroom",
        component="unit_bath",
        condition="aged",
        scope="replace",
        quantity=1,
    )
    assert valid.quantity == 1

    with pytest.raises(ValidationError):
        RenovationObservationInput(
            room="bathroom",
            component="unit_bath",
            condition="aged",
            scope="replace",
            area_m2=3,
        )


def test_save_request_rejects_duplicate_room_component_pairs():
    with pytest.raises(ValidationError):
        SaveRenovationObservationsRequest(
            observations=[
                RenovationObservationInput(
                    room="bathroom",
                    component="unit_bath",
                    condition="aged",
                    scope="replace",
                ),
                RenovationObservationInput(
                    room="bathroom",
                    component="unit_bath",
                    condition="damaged",
                    scope="replace",
                ),
            ]
        )


def test_save_request_accepts_empty_clear():
    request = SaveRenovationObservationsRequest(observations=[])
    assert request.observations == []
```

- [ ] **Step 2: 运行并确认失败**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_intake_models.py -q
```

预期：`ImportError` 或 `AttributeError`（新类不存在）。

- [ ] **Step 3: 实现模型**

在 `backend/app/intake/models.py` 顶部 import 区加入类型别名：

```python
from ..renovation.models import Component, Condition, Room, Scope
```

在 `Purpose` 定义后加入：

```python
AssetType = Literal["apartment", "tower", "detached_house", "other"]
```

`CreateSessionRequest` 增加：

```python
    asset_type: Optional[AssetType] = None
```

`CreateSessionResponse` 增加：

```python
    asset_type: Optional[AssetType] = None
```

在 `ConfirmFieldRequest` 前加入观察契约：

```python
class RenovationObservationInput(IntakeModel):
    room: Room
    component: Component
    condition: Condition = "unknown"
    scope: Scope = "unknown"
    quantity: float = Field(default=1, gt=0, le=1000)
    area_m2: Optional[float] = Field(default=None, gt=0, le=10000)
    notes: str = Field(default="", max_length=500)
    evidence_input_id: Optional[UUID] = None

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_notes(cls, value: Any) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_measurement_for_component(self) -> "RenovationObservationInput":
        if self.component in ("wallpaper", "flooring"):
            if self.area_m2 is None:
                raise ValueError("wallpaper and flooring require area_m2")
        elif self.area_m2 is not None:
            raise ValueError("only wallpaper and flooring accept area_m2")
        return self


class SaveRenovationObservationsRequest(IntakeModel):
    observations: List[RenovationObservationInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_unique_room_component(self) -> "SaveRenovationObservationsRequest":
        keys = [(item.room, item.component) for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("room and component pairs must be unique")
        return self


class RenovationObservationView(RenovationObservationInput):
    id: UUID
    evidence_original_name: Optional[str] = Field(default=None, max_length=255)
```

确认 `List` 已在文件顶部导入（当前已导入 `Dict, Literal, Optional`，需要把 `List` 加进同一行 `from typing import ...`）。

`FreePreviewResponse` 增加：

```python
    renovation_estimate: dict[str, Any]
```

- [ ] **Step 4: 运行并确认通过**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_intake_models.py -q
```

预期：全部通过。

- [ ] **Step 5: 回归后端单测**

```bash
PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit tests/api -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/intake/models.py tests/unit/test_intake_models.py
git commit -m "feat: add intake renovation observation pydantic contracts"
```

---

### Task 3: intake→装修估算编排模块

**Files:**
- Create: `backend/app/intake/renovation_estimate.py`
- Test: `tests/unit/test_intake_renovation_estimate.py`

**Interfaces:**
- Consumes: `backend/app/intake/completeness.FieldValue`、`backend/app/renovation/models.py`、`backend/app/renovation/pricing.build_estimate()`。
- Produces: `build_intake_renovation_estimate(fields, asset_type, purpose, observations) -> dict[str, Any]`。返回值三种形态：`{"status": "not_provided"}`、`{"status": "estimated", **estimate}`、`{"status": "no_priced_items", **estimate}`。

- [ ] **Step 1: 写失败测试**

```python
from backend.app.intake.completeness import FieldValue
from backend.app.intake.renovation_estimate import build_intake_renovation_estimate


def _field(value):
    return FieldValue(value, "confirmed", "high", True)


def test_no_observations_returns_not_provided():
    result = build_intake_renovation_estimate({}, "tower", "self_use", [])
    assert result == {"status": "not_provided"}


def test_estimated_rows_map_context_and_price():
    fields = {
        "area_sqm": _field(45.2),
        "building_year": _field(1980),
        "address": _field("大阪市大正区"),
    }
    rows = [
        {
            "room": "bathroom",
            "component": "unit_bath",
            "condition": "aged",
            "scope": "replace",
            "quantity": 1,
            "area_m2": None,
            "notes": "浴槽有明显使用年限感",
        }
    ]

    result = build_intake_renovation_estimate(fields, "apartment", "rental_investment", rows)

    assert result["status"] == "estimated"
    assert result["data_class"] == "modeled_estimate"
    assert result["currency"] == "JPY"
    assert result["total_range"]["low"] == 600000
    assert result["total_range"]["high"] == 1500000
    assert result["items"][0]["room"] == "bathroom"


def test_repair_only_rows_return_no_priced_items():
    rows = [
        {
            "room": "kitchen",
            "component": "kitchen",
            "condition": "aged",
            "scope": "monitor",
            "quantity": 1,
            "area_m2": None,
            "notes": "",
        }
    ]

    result = build_intake_renovation_estimate({}, None, "self_use", rows)

    assert result["status"] == "no_priced_items"
    assert any("暂未计价" in limitation for limitation in result["limitations"])


def test_wallpaper_without_area_is_not_priced():
    rows = [
        {
            "room": "living_room",
            "component": "wallpaper",
            "condition": "stained",
            "scope": "surface_refresh",
            "quantity": 1,
            "area_m2": None,
            "notes": "",
        }
    ]

    result = build_intake_renovation_estimate({}, "tower", "self_use", rows)

    assert result["status"] == "no_priced_items"
    assert result["items"] == []
```

- [ ] **Step 2: 运行并确认失败**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_intake_renovation_estimate.py -q
```

预期：`ModuleNotFoundError`。

- [ ] **Step 3: 实现模块**

```python
"""Mapping from intake session data to the renovation rough-estimate service."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from ..renovation.models import (
    PhotoObservation,
    PhotoRecord,
    RenovationContext,
    RenovationEstimateRequest,
)
from ..renovation.pricing import build_estimate
from .completeness import FieldValue


CONFIRMED_STATUSES = frozenset({"confirmed", "corrected"})
STRUCTURE_BY_ASSET_TYPE = {
    "apartment": "condo",
    "tower": "condo",
    "detached_house": "detached",
}


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


def _confirmed_value(fields: Mapping[str, FieldValue], key: str) -> Any:
    field = fields.get(key)
    if field is None or field.value is None:
        return None
    if field.confirmation_status not in CONFIRMED_STATUSES:
        return None
    return field.value


def _number(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip()) if "." in str(value) else int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _observation_photo(row: Any) -> PhotoRecord:
    room = str(_row_value(row, "room", "unknown"))
    component = str(_row_value(row, "component"))
    area_m2 = _number(_row_value(row, "area_m2"))
    return PhotoRecord(
        id=f"{room}-{component}",
        room=room,
        observations=[
            PhotoObservation(
                component=component,
                condition=str(_row_value(row, "condition", "unknown")),
                scope=str(_row_value(row, "scope", "unknown")),
                confidence="medium",
                quantity=float(_number(_row_value(row, "quantity", 1)) or 1),
                area_m2=area_m2,
                notes=str(_row_value(row, "notes", "") or ""),
            )
        ],
    )


def build_intake_renovation_estimate(
    fields: Mapping[str, FieldValue],
    asset_type: Any,
    purpose: Any,
    observations: List[Any],
) -> Dict[str, Any]:
    if not observations:
        return {"status": "not_provided"}

    # renovation_goal is fixed to purchase screening in the C-end flow; the
    # session purpose argument stays in the signature for future provenance use.
    location_hint = _text(_confirmed_value(fields, "address"))
    structure = STRUCTURE_BY_ASSET_TYPE.get(asset_type, "unknown") if asset_type else "unknown"
    context = RenovationContext(
        location_hint=location_hint or None,
        floor_area_m2=_number(_confirmed_value(fields, "area_sqm")),
        built_year=_number(_confirmed_value(fields, "building_year")),
        structure=structure,
        renovation_goal="purchase_screening",
    )
    request = RenovationEstimateRequest(
        context=context,
        photos=[_observation_photo(row) for row in observations],
    )
    estimate = build_estimate(request, analysis_source="caller_structured_observations")
    if not estimate.get("items"):
        estimate["status"] = "no_priced_items"
    else:
        estimate["status"] = "estimated"
    return estimate
```

- [ ] **Step 4: 运行并确认通过**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_intake_renovation_estimate.py -q
```

预期：4 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/intake/renovation_estimate.py tests/unit/test_intake_renovation_estimate.py
git commit -m "feat: orchestrate renovation estimate from intake observations"
```

---

### Task 4: 免费预览携带 renovation_estimate

**Files:**
- Modify: `backend/app/intake/completeness.py`
- Test: `tests/unit/test_completeness.py`

**Interfaces:**
- Consumes: Task 3 返回的形态字典（或 `None`）。
- Produces: `build_free_preview(fields, renovation_estimate=None)`；返回字典始终含 `renovation_estimate` 与 `calculation_version: "free-preview-v2"`。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_completeness.py` 末尾追加：

```python
def test_preview_includes_not_provided_renovation_by_default():
    preview = build_free_preview({})
    assert preview["renovation_estimate"] == {"status": "not_provided"}
    assert preview["calculation_version"] == "free-preview-v2"


def test_preview_persists_supplied_renovation_estimate():
    estimate = {"status": "estimated", "total_range": {"low": 1, "high": 2}}
    preview = build_free_preview({}, estimate)
    assert preview["renovation_estimate"] is estimate
```

- [ ] **Step 2: 运行并确认失败**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_completeness.py -q
```

预期：`KeyError` 或版本断言失败。

- [ ] **Step 3: 修改 `build_free_preview`**

把函数签名与返回体改为：

```python
def build_free_preview(
    fields: Mapping[str, FieldValue],
    renovation_estimate: Any = None,
) -> Dict[str, object]:
    completeness = calculate_completeness(fields)
    return {
        "completeness": completeness,
        "acquisition_costs": {
            "status": "rules_not_loaded",
            "estimated_total_jpy": None,
            "items": list(ACQUISITION_COST_ITEMS),
        },
        "risk_summary": _risk_summary(completeness),
        "renovation_estimate": (
            renovation_estimate
            if renovation_estimate is not None
            else {"status": "not_provided"}
        ),
        "comparable_status": "not_checked",
        "calculation_version": "free-preview-v2",
    }
```

- [ ] **Step 4: 运行并确认通过**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_completeness.py -q
PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit tests/api -q
```

预期：全绿（旧调用不传第二参数仍返回默认 `not_provided`）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/intake/completeness.py tests/unit/test_completeness.py
git commit -m "feat: include renovation estimate in free preview payload"
```

---

### Task 5: repository 持久化与测试替身

**Files:**
- Modify: `backend/app/intake/repository.py`
- Modify: `tests/api/conftest.py`
- Test: `tests/unit/test_intake_repository.py`

**Interfaces:**
- Consumes: `RenovationObservationInput`（Task 2）。
- Produces:
  - `IntakeRepository.create_session(purpose, consent_version, token_hash, expires_at, asset_type=None)`
  - `IntakeRepository.get_observations(session_id) -> List[dict]`
  - `IntakeRepository.replace_observations(session_id, observations) -> List[dict]`
  - `IntakeRepository.save_preview(...)` 写入 `renovation_estimate`
  - `EvidenceNotInSession` 异常
  - FakeRepository 同名方法（供 API 测试）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_intake_repository.py` 追加：

```python
from uuid import UUID

from backend.app.intake.models import RenovationObservationInput
from backend.app.intake.repository import EvidenceNotInSession


class RenovationConnection(RecordingConnection):
    def __init__(self, session, evidence_rows=None):
        super().__init__(session)
        self.evidence_rows = evidence_rows or []
        self.observation_rows = []

    async def fetchval(self, query, *args):
        self._record(query, args)
        return len(self.evidence_rows)

    async def fetch(self, query, *args):
        self._record(query, args)
        lowered = query.lower()
        if "select count(*)" in lowered:
            return None
        return self.observation_rows

    async def executemany(self, query, records):
        self._record(query, records)
        for record in records:
            self.observation_rows.append(
                {
                    "id": UUID("00000000-0000-0000-0000-000000000050"),
                    "session_id": record[0],
                    "room": record[1],
                    "component": record[2],
                    "condition": record[3],
                    "scope": record[4],
                    "quantity": record[5],
                    "area_m2": record[6],
                    "notes": record[7],
                    "evidence_input_id": record[8],
                }
            )


@pytest.mark.asyncio
async def test_replace_observations_uses_one_transaction_and_returns_rows():
    connection = RenovationConnection(session={}, evidence_rows=[{"id": "x"}])
    repository = IntakeRepository(FakePool(connection))
    observation = RenovationObservationInput(
        room="bathroom",
        component="unit_bath",
        condition="aged",
        scope="replace",
        quantity=1,
    )

    rows = await repository.replace_observations(SESSION_ID, [observation])

    assert rows
    assert connection.transaction_committed
    assert any("delete from public.renovation_observations" in q.lower() for q in connection.queries)
    assert any("insert into public.renovation_observations" in q.lower() for q in connection.queries)


@pytest.mark.asyncio
async def test_replace_observations_rejects_evidence_from_other_sessions():
    connection = RenovationConnection(session={}, evidence_rows=[])
    repository = IntakeRepository(FakePool(connection))
    observation = RenovationObservationInput(
        room="bathroom",
        component="unit_bath",
        condition="aged",
        scope="replace",
        quantity=1,
        evidence_input_id=UUID("00000000-0000-0000-0000-000000000099"),
    )

    with pytest.raises(EvidenceNotInSession):
        await repository.replace_observations(SESSION_ID, [observation])
```

- [ ] **Step 2: 运行并确认失败**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_intake_repository.py -q
```

预期：`ImportError`（异常/方法不存在）。

- [ ] **Step 3: 实现 repository**

在 `repository.py` 顶部 import 增加：

```python
from .models import ConfirmFieldRequest, CreateInputRequest, LocationRequest, RenovationObservationInput
```

在 `ProjectNameTaken` 后新增：

```python
class EvidenceNotInSession(Exception):
    """Raised when an observation references a file that does not belong to the session."""
```

修改 `create_session` 签名与 SQL：

```python
    async def create_session(
        self,
        purpose: str,
        consent_version: str,
        token_hash: str,
        expires_at: datetime,
        asset_type: Optional[str] = None,
    ) -> Any:
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(
                """
                insert into public.analysis_sessions
                  (purpose, consent_version, token_hash, expires_at, asset_type)
                values ($1, $2, $3, $4, $5)
                returning *
                """,
                purpose,
                consent_version,
                token_hash,
                expires_at,
                asset_type,
            )
```

在 `upsert_field` 后新增两个方法：

```python
    async def get_observations(self, session_id: UUID) -> List[Any]:
        async with self.pool.acquire() as connection:
            return await connection.fetch(
                """
                select ro.*, pi.original_name as evidence_original_name
                from public.renovation_observations ro
                left join public.project_inputs pi on pi.id = ro.evidence_input_id
                where ro.session_id=$1
                order by ro.room, ro.component
                """,
                session_id,
            )

    async def replace_observations(
        self,
        session_id: UUID,
        observations: List[RenovationObservationInput],
    ) -> List[Any]:
        evidence_ids = [
            observation.evidence_input_id
            for observation in observations
            if observation.evidence_input_id is not None
        ]
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if evidence_ids:
                    found = await connection.fetchval(
                        """
                        select count(*)
                        from public.project_inputs
                        where id = any($1::uuid[])
                          and session_id=$2
                          and input_type='image'
                        """,
                        evidence_ids,
                        session_id,
                    )
                    if not found or int(found) != len(evidence_ids):
                        raise EvidenceNotInSession()
                await connection.execute(
                    """
                    delete from public.renovation_observations
                    where session_id=$1
                    """,
                    session_id,
                )
                if observations:
                    await connection.executemany(
                        """
                        insert into public.renovation_observations
                          (session_id, room, component, condition, scope,
                           quantity, area_m2, notes, evidence_input_id)
                        values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        """,
                        [
                            (
                                session_id,
                                observation.room,
                                observation.component,
                                observation.condition,
                                observation.scope,
                                observation.quantity,
                                observation.area_m2,
                                observation.notes,
                                observation.evidence_input_id,
                            )
                            for observation in observations
                        ],
                    )
                return await connection.fetch(
                    """
                    select ro.*, pi.original_name as evidence_original_name
                    from public.renovation_observations ro
                    left join public.project_inputs pi on pi.id = ro.evidence_input_id
                    where ro.session_id=$1
                    order by ro.room, ro.component
                    """,
                    session_id,
                )
```

修改 `save_preview`：INSERT 增加第 7 列、VALUES 增加 `$7::jsonb`，并把 `on conflict` 更新列表加上 `renovation_estimate=excluded.renovation_estimate`：

```python
    async def save_preview(self, session_id: UUID, preview: Mapping[str, Any]) -> Any:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    insert into public.free_previews
                      (session_id, completeness, acquisition_costs, risk_summary,
                       comparable_status, calculation_version, renovation_estimate)
                    values ($1, $2::jsonb, $3::jsonb, $4::jsonb, $5, $6, $7::jsonb)
                    on conflict (session_id) do update set
                      completeness=excluded.completeness,
                      acquisition_costs=excluded.acquisition_costs,
                      risk_summary=excluded.risk_summary,
                      comparable_status=excluded.comparable_status,
                      calculation_version=excluded.calculation_version,
                      renovation_estimate=excluded.renovation_estimate
                    returning *
                    """,
                    session_id,
                    _json_text(preview["completeness"]),
                    _json_text(preview["acquisition_costs"]),
                    _json_text(preview["risk_summary"]),
                    preview["comparable_status"],
                    preview["calculation_version"],
                    _json_text(
                        preview.get("renovation_estimate") or {"status": "not_provided"}
                    ),
                )
                # 后续 session status 更新逻辑保持不变
```

- [ ] **Step 4: 同步 FakeRepository（tests/api/conftest.py）**

`create_session` 签名改为：

```python
    async def create_session(self, purpose, consent_version, token_hash, expires_at, asset_type=None):
        session_id = uuid4()
        session = {
            "id": session_id,
            "purpose": purpose,
            "consent_version": consent_version,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "owner_user_id": None,
            "property_id": None,
            "status": "draft",
            "asset_type": asset_type,
        }
        self.sessions[session_id] = session
        self.fields[session_id] = {}
        self.observations[session_id] = []
        return session
```

`__init__` 增加：

```python
        self.observations: Dict[UUID, List[dict]] = {}
```

追加：

```python
    async def get_observations(self, session_id):
        return list(self.observations.get(session_id, []))

    async def replace_observations(self, session_id, observations):
        for observation in observations:
            evidence_id = observation.evidence_input_id
            if evidence_id and not any(
                item["id"] == evidence_id
                and item["session_id"] == session_id
                and item["input_type"] == "image"
                for item in self.inputs
            ):
                raise EvidenceNotInSession()
        self.observations[session_id] = [
            {
                "id": uuid4(),
                "session_id": session_id,
                "room": observation.room,
                "component": observation.component,
                "condition": observation.condition,
                "scope": observation.scope,
                "quantity": observation.quantity,
                "area_m2": observation.area_m2,
                "notes": observation.notes,
                "evidence_input_id": observation.evidence_input_id,
                "evidence_original_name": next(
                    (item["original_name"] for item in self.inputs if item["id"] == observation.evidence_input_id),
                    None,
                ),
            }
            for observation in observations
        ]
        return list(self.observations[session_id])
```

更新 conftest import：

```python
from backend.app.intake.repository import (
    ConvertedProject,
    DuplicateAddress,
    EvidenceNotInSession,
    ProjectNameTaken,
    SessionNotFound,
)
```

- [ ] **Step 5: 运行 repository 与既有单测**

```bash
backend/.venv/bin/python -m pytest tests/unit/test_intake_repository.py -q
PYTHONPATH=. backend/.venv/bin/python -m pytest tests/unit tests/api -q
```

预期：全绿。

- [ ] **Step 6: Commit**

```bash
git add backend/app/intake/repository.py tests/unit/test_intake_repository.py tests/api/conftest.py
git commit -m "feat: persist and replace intake renovation observations"
```

---

### Task 6: intake 路由（会话 asset_type、观察保存、预览集成）

**Files:**
- Modify: `backend/app/routes/intake.py`
- Test: `tests/api/test_intake_routes.py`

**Interfaces:**
- Consumes: Task 2 模型、Task 3 `build_intake_renovation_estimate`、Task 5 repository/Fake。
- Produces: `PUT /api/intake/sessions/{session_id}/renovation/observations`；`POST /preview` 响应含 `renovation_estimate`；`POST /sessions` 响应含 `asset_type`。

- [ ] **Step 1: 写失败测试**

在 `tests/api/test_intake_routes.py` 末尾追加：

```python
from uuid import UUID


IMAGE_UUID = UUID("00000000-0000-0000-0000-000000000045")
OTHER_IMAGE_UUID = UUID("00000000-0000-0000-0000-000000000099")


def _put_observations(client, session, observations):
    return client.put(
        f"/api/intake/sessions/{session['session_id']}/renovation/observations",
        headers={"X-Analysis-Session": session["session_token"]},
        json={"observations": observations},
    )


def test_create_session_persists_optional_asset_type(client, fake_repository):
    response = client.post(
        "/api/intake/sessions",
        json={
            "purpose": "self_use",
            "consent_version": "privacy-2026-08",
            "asset_type": "tower",
        },
    )

    assert response.status_code == 201
    assert response.json()["asset_type"] == "tower"
    saved = next(iter(fake_repository.sessions.values()))
    assert saved["asset_type"] == "tower"


def test_observation_wallpaper_without_area_is_rejected(client, session):
    response = _put_observations(
        client,
        session,
        [
            {
                "room": "living_room",
                "component": "wallpaper",
                "condition": "stained",
                "scope": "surface_refresh",
            }
        ],
    )

    assert response.status_code == 422


def test_observation_evidence_must_be_session_image(client, session, fake_repository):
    fake_repository.inputs.append(
        {
            "id": IMAGE_UUID,
            "session_id": UUID(session["session_id"]),
            "input_type": "image",
            "original_name": "bathroom.jpg",
            "processing_status": "pending",
        }
    )

    ok = _put_observations(
        client,
        session,
        [
            {
                "room": "bathroom",
                "component": "unit_bath",
                "condition": "aged",
                "scope": "replace",
                "quantity": 1,
                "evidence_input_id": str(IMAGE_UUID),
            }
        ],
    )
    assert ok.status_code == 200
    assert ok.json()[0]["evidence_original_name"] == "bathroom.jpg"

    bad = _put_observations(
        client,
        session,
        [
            {
                "room": "bathroom",
                "component": "unit_bath",
                "condition": "aged",
                "scope": "replace",
                "quantity": 1,
                "evidence_input_id": str(OTHER_IMAGE_UUID),
            }
        ],
    )
    assert bad.status_code == 422


def test_observations_replace_whole_set(client, session):
    first = _put_observations(
        client,
        session,
        [
            {
                "room": "bathroom",
                "component": "unit_bath",
                "condition": "aged",
                "scope": "replace",
                "quantity": 1,
            }
        ],
    )
    assert first.status_code == 200

    cleared = _put_observations(client, session, [])
    assert cleared.status_code == 200
    assert cleared.json() == []


def test_preview_includes_renovation_estimate_statuses(client, session, fake_repository):
    preview = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    assert preview.status_code == 200
    assert preview.json()["renovation_estimate"] == {"status": "not_provided"}
    assert preview.json()["calculation_version"] == "free-preview-v2"

    put = _put_observations(
        client,
        session,
        [
            {
                "room": "bathroom",
                "component": "unit_bath",
                "condition": "aged",
                "scope": "replace",
                "quantity": 1,
            }
        ],
    )
    assert put.status_code == 200

    preview2 = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    assert preview2.status_code == 200
    estimate = preview2.json()["renovation_estimate"]
    assert estimate["status"] == "estimated"
    assert estimate["data_class"] == "modeled_estimate"
    assert estimate["items"][0]["component"] == "unit_bath"


def test_converted_session_cannot_replace_observations(client, session, auth_header):
    client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    client.post(
        f"/api/intake/sessions/{session['session_id']}/convert",
        headers={**auth_header, "X-Analysis-Session": session["session_token"]},
    )

    response = _put_observations(
        client,
        session,
        [
            {
                "room": "bathroom",
                "component": "unit_bath",
                "condition": "aged",
                "scope": "replace",
                "quantity": 1,
            }
        ],
    )
    assert response.status_code == 404
```

注意：`IMAGE_UUID` 需要在 `fake_repository.inputs` 元素里带 `"original_name"` 键；若与现有 fake 结构不一致，在 Task 5 conftest 的 `add_file_input` 中已保证该键存在。

- [ ] **Step 2: 运行并确认失败**

```bash
backend/.venv/bin/python -m pytest tests/api/test_intake_routes.py -q
```

预期：新用例失败（404 route / 422 / 缺字段）。

- [ ] **Step 3: 实现路由**

在 `backend/app/routes/intake.py` import 增加：

```python
from ..intake.models import (
    ConfirmFieldRequest,
    ConvertSessionRequest,
    CreateInputRequest,
    CreateInputResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    FieldView,
    FreePreviewResponse,
    LocationRequest,
    LocationResponse,
    RenovationObservationInput,
    RenovationObservationView,
    SaveRenovationObservationsRequest,
)
from ..intake.renovation_estimate import build_intake_renovation_estimate
from ..intake.repository import (
    DuplicateAddress,
    EvidenceNotInSession,
    IntakeRepository,
    ProjectNameRequired,
    ProjectNameTaken,
    SessionNotFound,
)
```

`create_session` 中 repository 调用改为：

```python
    row = await repository.create_session(
        payload.purpose,
        payload.consent_version,
        token.digest,
        expires_at,
        payload.asset_type,
    )
```

并在 `CreateSessionResponse(...)` 增加：

```python
        asset_type=_row_value(row, "asset_type", payload.asset_type),
```

在 `save_location` 后新增观察端点：

```python
def _observation_view(row: Any) -> RenovationObservationView:
    return RenovationObservationView(
        id=_uuid_value(row, "id"),
        room=str(_row_value(row, "room")),
        component=str(_row_value(row, "component")),
        condition=str(_row_value(row, "condition", "unknown")),
        scope=str(_row_value(row, "scope", "unknown")),
        quantity=float(_row_value(row, "quantity", 1)),
        area_m2=(
            float(_row_value(row, "area_m2"))
            if _row_value(row, "area_m2") is not None
            else None
        ),
        notes=str(_row_value(row, "notes", "") or ""),
        evidence_input_id=_row_value(row, "evidence_input_id"),
        evidence_original_name=_row_value(row, "evidence_original_name"),
    )


@router.put(
    "/sessions/{session_id}/renovation/observations",
    response_model=List[RenovationObservationView],
)
async def replace_renovation_observations(
    session_id: UUID,
    payload: SaveRenovationObservationsRequest,
    request: Request,
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> List[RenovationObservationView]:
    await _require_editable_session(repository, session_id, x_analysis_session)
    await _enforce_rate_limit(
        repository,
        request,
        "renovation_observations",
        10,
        scope=f"session:{session_id}",
    )
    try:
        rows = await repository.replace_observations(session_id, payload.observations)
    except EvidenceNotInSession as exc:
        raise HTTPException(
            status_code=422,
            detail="照片证据不属于该会话，或不是图片。",
        ) from exc
    if not rows and payload.observations:
        raise HTTPException(status_code=503, detail=SAVE_FAILURE_MESSAGE)
    return [_observation_view(row) for row in rows]
```

确认文件顶部已导入 `List`（当前 `from typing import Any, Dict, Optional`，需改为 `from typing import Any, Dict, List, Optional`）。

`create_preview` 改为：

```python
@router.post("/sessions/{session_id}/preview", response_model=FreePreviewResponse)
async def create_preview(
    session_id: UUID,
    request: Request,
    x_analysis_session: Optional[str] = Header(default=None, alias="X-Analysis-Session"),
    repository: IntakeRepository = Depends(get_intake_repository),
) -> FreePreviewResponse:
    session = await _require_editable_session(repository, session_id, x_analysis_session)
    await _enforce_rate_limit(repository, request, "preview_create", 20, scope=f"session:{session_id}")
    fields = await repository.get_fields(session_id)
    observations = await repository.get_observations(session_id)
    renovation_estimate = build_intake_renovation_estimate(
        fields,
        _row_value(session, "asset_type"),
        _row_value(session, "purpose", "self_use"),
        observations,
    )
    preview = build_free_preview(fields, renovation_estimate)
    await repository.save_preview(session_id, preview)
    return FreePreviewResponse(session_id=session_id, **preview)
```

- [ ] **Step 4: 运行 API 测试**

```bash
backend/.venv/bin/python -m pytest tests/api/test_intake_routes.py -q
```

若 `List`/`Any` import 报错先修正。

- [ ] **Step 5: 全量后端回归**

```bash
PYTHONPATH=. backend/.venv/bin/python -m pytest tests -q
```

预期：全绿（本机无法执行 SQL 的用例除外，它们不在 pytest 目录）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/intake.py tests/api/test_intake_routes.py
git commit -m "feat: add intake renovation observation routes and preview integration"
```

---

### Task 7: 前端 API client 与确认页静态结构

**Files:**
- Modify: `web/js/api-client.js`
- Modify: `web/property-analysis.html`
- Modify: `web/property-analysis.css`

**Interfaces:**
- Consumes: Task 6 端点。
- Produces: `createSession(purpose, consentVersion, assetType)`、`saveRenovationObservations(sessionId, sessionToken, observations)`；确认页出现 `#renovationEditor` 与静态观察模板。

- [ ] **Step 1: 扩展 API client**

`createSession` 改为：

```javascript
export function createSession(purpose, consentVersion = "privacy-2026-08", assetType = "") {
  const body = { purpose, consent_version: consentVersion };
  if (assetType) body.asset_type = assetType;
  return request("/api/intake/sessions", { method: "POST", body });
}
```

在 `saveLocation` 后新增：

```javascript
export function saveRenovationObservations(sessionId, sessionToken, observations) {
  return request(`/api/intake/sessions/${encodeURIComponent(sessionId)}/renovation/observations`, {
    method: "PUT",
    sessionToken,
    body: { observations },
  });
}
```

- [ ] **Step 2: 增加确认字段“建筑年份（可选）”**

在 `web/property-analysis.html` 的 `.field-grid` 内、`landRight` 输入后追加：

```html
<label class="field-label" for="buildingYear">建筑年份（可选）</label>
<input id="buildingYear" data-field="building_year" type="number" min="1800" max="2100" inputmode="numeric" placeholder="例如 1985" />
```

- [ ] **Step 3: 增加“室内状况观察（可选）”卡片**

在 `</section>`（location-card 结束）与 `<form id="confirmForm"...>` 之间插入：

```html
<section class="renovation-card" aria-labelledby="renovationHeading">
  <div class="section-heading section-heading-with-status">
    <div>
      <p class="section-number">+</p>
      <h3 id="renovationHeading">室内状况观察（可选）</h3>
    </div>
    <span class="status-chip">可选</span>
  </div>
  <p class="section-description">
    选择你看到的、需要计入翻新成本的项目。没有把握的项目可以跳过；面积类项目请填写施工面积，系统不会从照片推造。
  </p>
  <div id="renovationEditor">
    <p id="renovationEmpty" class="renovation-empty">尚未添加观察。点击下方按钮添加一个房间/项目。</p>
    <ul id="renovationRows" class="renovation-rows" aria-live="polite"></ul>
    <button id="addRenovationRow" class="secondary-button" type="button">添加观察</button>
  </div>
  <p id="renovationStatus" class="renovation-status" role="alert" aria-live="assertive"></p>
</section>
```

- [ ] **Step 4: 追加样式**

在 `web/property-analysis.css` 末尾追加：

```css
.renovation-card {
  margin: 1.25rem 0;
  padding: 1rem;
  border: 1px solid var(--line, #dfe3ec);
  border-radius: 12px;
  background: #fff;
}
.renovation-card .section-description {
  margin: 0 0 0.85rem;
  color: #55617a;
  font-size: 0.95rem;
}
.renovation-rows {
  list-style: none;
  margin: 0 0 0.75rem;
  padding: 0;
  display: grid;
  gap: 0.75rem;
}
.renovation-row {
  display: grid;
  gap: 0.6rem;
  padding: 0.8rem;
  border: 1px solid #e6e9f1;
  border-radius: 10px;
  background: #f8f9fc;
}
.renovation-row label {
  display: grid;
  gap: 0.3rem;
  font-size: 0.9rem;
  color: #55617a;
}
.renovation-row select,
.renovation-row input {
  width: 100%;
  min-height: 2.6rem;
  padding: 0.45rem 0.6rem;
  border: 1px solid #cfd5e2;
  border-radius: 8px;
  font: inherit;
  background: #fff;
}
.renovation-row .remove-row {
  justify-self: start;
}
.renovation-empty,
.renovation-status.is-empty {
  color: #7a849a;
  font-size: 0.9rem;
}
.renovation-status[data-tone="error"] {
  color: #b42318;
}
.renovation-status[data-tone="success"] {
  color: #067647;
}
.renovation-range {
  font-size: 1.4rem;
  color: #10284d;
}
.renovation-estimate-section .plain-list {
  margin: 0.4rem 0;
}
@media (max-width: 480px) {
  .renovation-card {
    padding: 0.75rem;
  }
  .renovation-row {
    padding: 0.65rem;
  }
}
```

若该 CSS 使用别的 CSS 变量命名，保留既有变量名并保持可读性；以上仅提供缺省回退，不影响现有变量。

- [ ] **Step 5: 语法与回归**

```bash
node --check web/js/api-client.js
npm run test:web
```

预期：现有用例全部通过（新增卡片不影响旧交互）。

- [ ] **Step 6: Commit**

```bash
git add web/js/api-client.js web/property-analysis.html web/property-analysis.css
git commit -m "feat: add renovation observation editor shell to intake confirm step"
```

---

### Task 8: property-intake.js 观察采集、提交与三态渲染

**Files:**
- Modify: `web/js/property-intake.js`
- Modify: `tests/web/property-intake.spec.js`

**Interfaces:**
- Consumes: Task 7 DOM/API；`state.session`、`DEMO_MODE`、`createElement()`、`setStatus()`、`setBusy()`。
- Produces: `state.observations`、`collectRenovationObservations()`、`renderRenovationEstimate()`；demo 模式在添加观察后渲染 `synthetic_fixture` 估算。

- [ ] **Step 1: 更新 import**

```javascript
import {
  addTextOrUrlInput,
  confirmField,
  convertSession,
  createSession,
  generatePreview,
  getExistingAccessToken,
  saveLocation,
  saveRenovationObservations,
  uploadFiles,
} from "./api-client.js";
```

- [ ] **Step 2: 增加常量与状态**

在 `DIMENSION_LABELS` 附近加入：

```javascript
const ROOM_OPTIONS = [
  ["exterior", "外立面/屋顶外观"],
  ["bathroom", "卫生间/浴室"],
  ["kitchen", "厨房"],
  ["living_room", "客厅/餐厅"],
  ["bedroom", "卧室"],
  ["balcony", "阳台"],
];
const COMPONENT_OPTIONS = [
  ["unit_bath", "整体卫浴更换"],
  ["wallpaper", "墙纸/墙布"],
  ["flooring", "复合地板"],
  ["kitchen", "系统厨房"],
  ["toilet", "厕所设备"],
  ["washstand", "洗面化妆台"],
  ["tatami", "畳表替え"],
];
const CONDITION_OPTIONS = [
  ["new", "较新"],
  ["good", "良好"],
  ["aged", "老化"],
  ["worn", "磨损"],
  ["stained", "污渍"],
  ["damaged", "破损"],
  ["mold_or_stain", "霉斑"],
  ["water_damage_suspected", "疑似水损"],
  ["unknown", "不确定"],
];
const SCOPE_OPTIONS = [
  ["replace", "更换"],
  ["surface_refresh", "表面刷新"],
  ["repair", "待维修"],
  ["monitor", "仅观察/暂不处理"],
  ["unknown", "不确定"],
];
const AREA_COMPONENTS = new Set(["wallpaper", "flooring"]);
```

`state` 增加：

```javascript
  observations: [],
  photoEvidence: [],
```

`elements` 增加：

```javascript
  renovationEditor: document.querySelector("#renovationEditor"),
  renovationRows: document.querySelector("#renovationRows"),
  renovationEmpty: document.querySelector("#renovationEmpty"),
  renovationStatus: document.querySelector("#renovationStatus"),
  addRenovationRow: document.querySelector("#addRenovationRow"),
```

`CONFIRM_FIELDS` 增加 `"building_year"`。

- [ ] **Step 3: 增加渲染/收集函数**

在 `renderInputSummary` 附近加入：

```javascript
function optionItems(options, selected = "") {
  return options
    .map(([value, label]) => `<option value="${value}"${value === selected ? " selected" : ""}>${label}</option>`)
    .join("");
}

function makeSelect(labelText, name, options, selected = "") {
  const label = createElement("label", undefined, "row-field");
  label.append(createElement("span", labelText));
  const select = document.createElement("select");
  select.name = name;
  select.innerHTML = optionItems(options, selected);
  select.setAttribute("aria-label", labelText);
  label.append(select);
  return label;
}

function evidenceField() {
  const label = createElement("label", undefined, "row-field");
  label.append(createElement("span", "证据照片（可选）"));
  const select = document.createElement("select");
  select.name = "evidence";
  const options = [["", "不关联照片"]];
  state.photoEvidence.forEach((item) => options.push([item.inputId, item.name]));
  select.innerHTML = optionItems(options);
  select.setAttribute("aria-label", "证据照片");
  label.append(select);
  return label;
}

function measurementField(component) {
  const label = createElement("label", undefined, "row-field");
  const isArea = AREA_COMPONENTS.has(component);
  const span = createElement("span", isArea ? "施工面积（m²，必填）" : "数量");
  const input = document.createElement("input");
  input.type = "number";
  input.min = "0";
  input.step = isArea ? "0.01" : "1";
  input.value = isArea ? "" : "1";
  input.name = isArea ? "area" : "quantity";
  input.setAttribute("aria-label", isArea ? "施工面积（平方米）" : "数量");
  label.append(span, input);
  return label;
}

function updateRowMeasurement(row) {
  const component = row.querySelector('select[name="component"]')?.value || "unit_bath";
  const current = row.querySelector(".row-measurement");
  const fresh = measurementField(component);
  fresh.classList.add("row-measurement");
  current.replaceWith(fresh);
  updateMeasurementLabel(row);
}

function updateMeasurementLabel(row) {
  const component = row.querySelector('select[name="component"]')?.value || "";
  const note = row.querySelector(".row-unit-note");
  const unitHint = AREA_COMPONENTS.has(component)
    ? "请填写需要施工的面积，而不是整套面积"
    : component === "tatami"
      ? "请填写需要更换的畳数"
      : "整体卫浴/厨房/厕所/洗面台通常按 1 处计";
  if (note) note.textContent = unitHint;
}

function createObservationRow() {
  const row = document.createElement("li");
  row.className = "renovation-row";
  const room = makeSelect("房间", "room", ROOM_OPTIONS, "bathroom");
  const component = makeSelect("项目", "component", COMPONENT_OPTIONS);
  const condition = makeSelect("状况", "condition", CONDITION_OPTIONS);
  const scope = makeSelect("处理范围", "scope", SCOPE_OPTIONS);
  const measurement = measurementField(component.value);
  measurement.classList.add("row-measurement");
  const evidence = evidenceField();
  const noteLabel = createElement("label", undefined, "row-field");
  noteLabel.append(createElement("span", "备注（可选）"));
  const note = document.createElement("input");
  note.type = "text";
  note.maxLength = 200;
  note.name = "notes";
  note.setAttribute("aria-label", "备注");
  noteLabel.append(note);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-row outline-button";
  remove.textContent = "删除此行";
  remove.setAttribute("aria-label", "删除此行");

  row.append(room, component, condition, scope, measurement, evidence, noteLabel, remove);
  const unitHint = document.createElement("p");
  unitHint.className = "row-unit-note";
  row.append(unitHint);
  updateMeasurementLabel(row);

  room.querySelector("select").addEventListener("change", () => clearRenovationStatus());
  component.querySelector("select").addEventListener("change", () => {
    updateRowMeasurement(row);
    clearRenovationStatus();
  });
  condition.querySelector("select").addEventListener("change", clearRenovationStatus);
  scope.querySelector("select").addEventListener("change", clearRenovationStatus);
  evidence.querySelector("select").addEventListener("change", clearRenovationStatus);
  note.addEventListener("input", clearRenovationStatus);
  remove.addEventListener("click", () => {
    row.remove();
    syncRenovationEmptyState();
    clearRenovationStatus();
  });
  return row;
}

function addObservationRow() {
  const row = createObservationRow();
  state.observations.push(row);
  elements.renovationRows.append(row);
  syncRenovationEmptyState();
  clearRenovationStatus();
}

function syncRenovationEmptyState() {
  const hasRows = elements.renovationRows.children.length > 0;
  elements.renovationEmpty.hidden = hasRows;
  elements.addRenovationRow.textContent = hasRows ? "继续添加观察" : "添加观察";
}

function clearRenovationStatus() {
  elements.renovationStatus.textContent = "";
  elements.renovationStatus.dataset.tone = "";
}

function setRenovationStatus(message, tone = "error") {
  elements.renovationStatus.textContent = message;
  elements.renovationStatus.dataset.tone = tone;
  elements.renovationStatus.focus();
}

function collectRenovationObservations() {
  const rows = Array.from(elements.renovationRows.children);
  if (!rows.length) return { observations: [], error: "" };
  const seen = new Set();
  const observations = [];
  for (const row of rows) {
    const values = {
      room: row.querySelector('select[name="room"]')?.value,
      component: row.querySelector('select[name="component"]')?.value,
      condition: row.querySelector('select[name="condition"]')?.value,
      scope: row.querySelector('select[name="scope"]')?.value,
      notes: row.querySelector('input[name="notes"]')?.value.trim() || "",
    };
    const evidenceId = row.querySelector('select[name="evidence"]')?.value;
    if (evidenceId) values.evidence_input_id = evidenceId;
    const isArea = AREA_COMPONENTS.has(values.component);
    const measurement = row.querySelector(".row-measurement input");
    const rawMeasurement = measurement?.value.trim();
    if (isArea) {
      if (!rawMeasurement || Number(rawMeasurement) <= 0) {
        return { observations: [], error: "请为墙纸/地板填写施工面积（m²）。" };
      }
      values.area_m2 = Number(rawMeasurement);
    } else {
      values.quantity = rawMeasurement && Number(rawMeasurement) > 0 ? Number(rawMeasurement) : 1;
    }
    const key = `${values.room}:${values.component}`;
    if (seen.has(key)) {
      return { observations: [], error: "同一房间的同一项目只能保留一行，请合并或删除重复行。" };
    }
    seen.add(key);
    observations.push(values);
  }
  return { observations, error: "" };
}
```

- [ ] **Step 4: 修改 `startIntake` 记录上传证据与 asset_type**

`startIntake` 中 `createSession(purpose)` 改为：

```javascript
      const session = await createSession(purpose, "privacy-2026-08", assetType);
```

上传部分改为：

```javascript
      if (files.length || photos.length) {
    const uploaded = await uploadFiles(state.session.sessionId, state.session.rawToken, [...files, ...photos]);
    state.photoEvidence = uploaded.map((item, index) => ({
      name: [...files, ...photos][index]?.name || "",
      inputId: item.input_id ? String(item.input_id) : "",
    }));
  }
```

进入 `confirm` 前，演示模式用本地文件名填充证据源（真实模式已由上传响应提供 `input_id`）：

```javascript
    if (DEMO_MODE) {
      state.photoEvidence = Array.from(elements.photos.files || []).map((file) => ({
        name: file.name,
        inputId: "",
      }));
    }
```

证据下拉在每次“添加观察”时由 `evidenceField()` 从 `state.photoEvidence` 生成：真实模式值为后端 `input_id`，demo 模式下值为空（不发后端，只做界面占位）。

- [ ] **Step 5: 修改 `createFreePreview` 先保存观察再生成预览**

在 `createFreePreview` 中、`if (DEMO_MODE)` 分支之前加入：

```javascript
  const renovation = collectRenovationObservations();
  if (renovation.error) {
    setRenovationStatus(renovation.error);
    return setStatus(renovation.error, "error");
  }
```

并在 demo 分支中：

```javascript
    if (DEMO_MODE) {
      const withRenovation = renovation.observations.length > 0;
      state.preview = {
        ...DEMO_PREVIEW,
        renovation_estimate: withRenovation ? DEMO_RENOVATION_ESTIMATE : { status: "not_provided" },
      };
      renderPreview(state.preview);
      updateProjectNameDefault();
      setStage("preview");
      setStatus("演示预览已生成。当前内容只用于确认界面和流程。", "success");
      return;
    }
```

在真实分支、字段确认循环前加入：

```javascript
    await saveRenovationObservations(
      state.session.sessionId,
      state.session.rawToken,
      renovation.observations,
    );
```

`DEMO_PREVIEW` 增加：

```javascript
  renovation_estimate: { status: "not_provided" },
```

新增 demo 估算常量：

```javascript
const DEMO_RENOVATION_ESTIMATE = {
  status: "estimated",
  data_class: "synthetic_fixture",
  currency: "JPY",
  tax_basis: "approximate",
  price_snapshot_version: "jp-renovation-2026-08-31-v1",
  total_range: { low: 800000, high: 1500000 },
  items: [
    {
      room: "bathroom",
      component: "unit_bath",
      name: "整体卫浴（ユニットバス）更换",
      unit: "job",
      quantity: 1,
      condition: "aged",
      confidence: "medium",
      photo_refs: [],
      photo_observations: ["演示：浴槽有明显使用年限感"],
      estimate_assumptions: ["演示行，不引用真实施工报价。"],
      range: { low: 600000, high: 1500000 },
      source_refs: [],
    },
  ],
  photo_analysis: { status: "structured_observations", provider: "caller_structured_observations", photos: [] },
  assumptions: ["演示数据：只用于界面评审。"],
  excluded_items: ["管线、承重结构、地基、石棉、防水层、隐藏漏水"],
  sources: [],
  limitations: ["界面演示，不代表真实结论。", "真实预览会在服务端按用户申报的可见状态计算。"],
  confidence: "low",
};
```

- [ ] **Step 6: 渲染“翻新成本参考（可选）”**

`renderPreview` 中、`costs.append(costList)` 之后追加：

```javascript
  const renovation = renderRenovationEstimate(preview.renovation_estimate);
  if (renovation) elements.previewContent.append(renovation);
```

新增：

```javascript
function formatJpy(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `¥${number.toLocaleString("ja-JP")}` : "";
}

function listSection(title, values) {
  const section = createElement("div", undefined, "renovation-list-section");
  section.append(createElement("h4", title));
  const list = createElement("ul", undefined, "plain-list");
  (values || []).forEach((item) => list.append(createElement("li", String(item))));
  section.append(list);
  return section;
}

function renderRenovationEstimate(estimate) {
  const section = createElement("section", undefined, "preview-section renovation-estimate-section");
  const heading = createElement("div", undefined, "section-heading-row");
  heading.append(
    createElement("h3", "翻新成本参考（可选）"),
    createElement("span", estimate?.status === "estimated" ? "modeled_estimate" : "未估算", "status-chip"),
  );
  section.append(heading);

  if (!estimate || estimate.status === "not_provided") {
    section.append(
      createElement("p", "未提供室内状况观察，此项不估算、不计入完整度。", "preview-note"),
    );
    return section;
  }
  if (estimate.status === "no_priced_items") {
    section.append(
      createElement(
        "p",
        "已记录室内状况，但暂无可直接计价项目；需要现场确认工程范围。",
        "preview-note",
      ),
    );
    (estimate.limitations || []).forEach((item) => section.append(createElement("p", item, "risk-item")));
    return section;
  }

  section.append(
    createElement("p", `概算区间（含税口径 approximate）：`, "preview-note"),
    createElement("strong", `${formatJpy(estimate.total_range?.low)} – ${formatJpy(estimate.total_range?.high)}`, "renovation-range"),
  );
  const items = createElement("div", undefined, "renovation-list-section");
  items.append(createElement("h4", "分项明细"));
  const itemList = createElement("ul", undefined, "plain-list");
  (estimate.items || []).forEach((item) => {
    const range = `${formatJpy(item.range?.low)} – ${formatJpy(item.range?.high)}`;
    const unit = item.unit === "m2" ? ` · ${item.quantity} m²` : item.unit === "mat" ? ` · ${item.quantity} 畳` : "";
    itemList.append(createElement("li", `${item.name}（${item.room}）${unit}：${range}`));
  });
  items.append(itemList);
  section.append(
    items,
    listSection("估算假设", estimate.assumptions),
    listSection("排除项", estimate.excluded_items),
    listSection("公开来源", (estimate.sources || []).map((source) => `${source.title}（${source.url}）`)),
    listSection("限制", estimate.limitations),
    createElement("p", `价格快照：${estimate.price_snapshot_version} · 数据类别 ${estimate.data_class}`, "preview-note"),
    createElement("p", "初筛概算，不是施工报价、贷款评估或结构安全鉴定。", "risk-item"),
  );
  return section;
}
```

- [ ] **Step 7: 初始化绑定**

`initialize()` 增加：

```javascript
  elements.addRenovationRow.addEventListener("click", addObservationRow);
  elements.renovationStatus.classList.add("is-empty");
  syncRenovationEmptyState();
```

并在 `elements` 中补 `renovationStatus` 引用，确保它存在。

- [ ] **Step 8: Playwright mock 与断言**

在 `tests/web/property-intake.spec.js` 的 route 处理器里、`/location` 分支前增加：

```javascript
    if (path.endsWith("/renovation/observations") && request.method() === "PUT") {
      renovationActive = Array.isArray(body.observations) && body.observations.length > 0;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
      return;
    }
```

在文件顶部、`const SESSION_ID` 附近声明 `let renovationActive = false;`（放在 `beforeEach` 外的顶层变量区，route 闭包共享同一变量）。

preview mock 返回体增加顶层字段：

```javascript
          renovation_estimate: renovationActive
            ? {
                status: "estimated",
                data_class: "modeled_estimate",
                currency: "JPY",
                tax_basis: "approximate",
                price_snapshot_version: "jp-renovation-2026-08-31-v1",
                total_range: { low: 600000, high: 1500000 },
                items: [
                  {
                    room: "bathroom",
                    component: "unit_bath",
                    name: "整体卫浴（ユニットバス）更换",
                    unit: "job",
                    quantity: 1,
                    condition: "aged",
                    confidence: "medium",
                    photo_refs: [],
                    photo_observations: [],
                    estimate_assumptions: [],
                    range: { low: 600000, high: 1500000 },
                    source_refs: [],
                  },
                ],
                photo_analysis: {},
                assumptions: [],
                excluded_items: [],
                sources: [],
                limitations: [],
                confidence: "low",
              }
            : { status: "not_provided" },
```

（route 处理器内 `body` 变量在同一作用域重复声明会报错；把 PUT 分支放到 `const body` 声明之后并复用。）

新增用例：

```javascript
test("no observations preview states renovation not provided", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元，45.2平方米");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.locator("#previewStep")).toContainText("翻新成本参考（可选）");
  await expect(page.locator("#previewStep")).toContainText("未提供室内状况观察，此项不估算、不计入完整度");
});

test("wallpaper observation without area blocks preview on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("apartment");
  await page.getByLabel("物件链接或说明").fill("大阪市北区");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "添加观察" }).click();
  const row = page.locator(".renovation-row").last();
  await row.getByLabel("房间").selectOption("living_room");
  await row.getByLabel("项目").selectOption("wallpaper");
  await row.getByLabel("状况").selectOption("stained");
  await row.getByLabel("处理范围").selectOption("surface_refresh");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.getByRole("alert").last()).toContainText("请为墙纸/地板填写施工面积");
  await expect(page.locator("#confirmStep")).toBeVisible();
});

test("bathroom replacement observation drives modeled preview", async ({ page }) => {
  await page.goto("/property-analysis.html");
  await page.getByLabel("物件类型 / 房型").selectOption("tower");
  await page.getByLabel("物件链接或说明").fill("大阪市北区，售价3500万日元");
  await page.getByRole("button", { name: "开始整理资料" }).click();
  await page.getByLabel("售价（日元）").fill("35000000");
  await page.getByRole("button", { name: "添加观察" }).click();
  const row = page.locator(".renovation-row").last();
  await row.getByLabel("房间").selectOption("bathroom");
  await row.getByLabel("项目").selectOption("unit_bath");
  await row.getByLabel("状况").selectOption("aged");
  await row.getByLabel("处理范围").selectOption("replace");
  await page.getByRole("button", { name: "生成免费预览" }).click();
  await expect(page.locator("#previewStep")).toContainText("翻新成本参考（可选）");
  await expect(page.locator("#previewStep")).toContainText("¥600,000 – ¥1,500,000");
  await expect(page.locator("#previewStep")).toContainText("modeled_estimate");
});
```

- [ ] **Step 9: 运行前端测试**

```bash
node --check web/js/property-intake.js
npm run test:web
```

逐个修复定位/文本错误直到全部通过。

- [ ] **Step 10: Commit**

```bash
git add web/js/property-intake.js tests/web/property-intake.spec.js
git commit -m "feat: capture intake renovation observations and render preview estimate"
```

---

### Task 9: `project.html` 演示占位与回归测试

**Files:**
- Modify: `web/project.html`
- Modify: `tests/web/project-workspace.spec.js`

**Interfaces:**
- Produces: 免费预览 V1 中可见的“翻新成本参考（可选）· synthetic_fixture”占位，不接入真实估算。

- [ ] **Step 1: 修改免费预览占位**

在 `web/project.html` 的“购入费用项目”section（`freeCostHeading` 结束的 `</section>`）后插入：

```html
<section class="report-section" aria-labelledby="freeRenovationHeading">
  <div class="section-heading-row">
    <div>
      <p class="eyebrow">02B · RENOVATION PREVIEW</p>
      <h3 id="freeRenovationHeading">翻新成本参考（可选）</h3>
    </div>
    <span class="section-index">界面演示</span>
  </div>
  <div class="insufficient-block">
    <strong>演示：装修成本估算将随真实免费预览生成</strong>
    <p>用户勾选室内状况后，系统会返回 JPY 概算区间、价格快照、假设与排除项。此处为 synthetic_fixture，不代表真实报价。</p>
  </div>
  <p class="section-note">数据类别 synthetic_fixture · 不替代现场施工报价。</p>
</section>
```

- [ ] **Step 2: 更新断言**

`tests/web/project-workspace.spec.js` 第一个用例在 `freeReport.getByText("synthetic_fixture")` 断言附近增加：

```javascript
  await expect(freeReport.getByRole("heading", { name: "翻新成本参考（可选）" })).toBeVisible();
  await expect(freeReport).toContainText("装修成本估算将随真实免费预览生成");
```

- [ ] **Step 3: 运行**

```bash
npm run test:web
node --check web/js/project-workspace.js
```

预期：全绿（paid 11 章计数不变）。

- [ ] **Step 4: Commit**

```bash
git add web/project.html tests/web/project-workspace.spec.js
git commit -m "feat: add free preview renovation placeholder to workspace demo"
```

---

### Task 10: 全量回归、progress 记录与收尾

**Files:**
- Modify: `progress.md`
- 只读：全仓

- [ ] **Step 1: 全量验证并如实记录**

```bash
PYTHONPATH=. backend/.venv/bin/python -m pytest tests -q
node --test tests/edge/jphouse-run-authority.test.mjs
npm run test:web
PYTHONPYCACHEPREFIX=/tmp/jppropdis-renovation-pycache backend/.venv/bin/python -m compileall -q backend scripts src
find web/js -type f -name '*.js' -print0 | xargs -0 -n1 node --check
node --check web/app.js
backend/.venv/bin/python -m pip check
git diff --check
```

SQL schema/RLS 文件若本机无 PostgreSQL，记录 `NOT_EXECUTED`；npm advisory / pip-audit 若需联网而受限，记录原因，不伪造通过。

- [ ] **Step 2: 桌面与移动浏览器验收**

对 `property-analysis.html`（demo 与普通模式）与 `project.html?demo=1&state=preview` 分别跑一次 `1440x900`、`390x844` 截图检查：无横向溢出、无 console error/warning。

- [ ] **Step 3: 更新 `progress.md`**

追加本节：

```markdown
## Free-preview renovation estimate integration (2026-09-04)

- 已将日本装修成本估算接入 C 端免费预览：确认字段步骤新增可选“室内状况观察”，观察整组保存到 intake 会话并作为证据（可选用同会话图片），预览快照新增 `renovation_estimate`。
- 新增 migration `20260904000100_intake_renovation_observations.sql`：`analysis_sessions.asset_type`、`renovation_observations` 表、`free_previews.renovation_estimate`；仅提交未应用。
- 三种展示状态：未提供 / 估算区间（`modeled_estimate`）/ 暂无计价项目；只有更换与表面刷新进入金额，面积项目必须有 `area_m2`。
- `project.html` 免费预览 V1 已加 `synthetic_fixture` 占位；真实完整版报告接入仍属 C18。
- Spec：`docs/superpowers/specs/2026-09-04-intake-renovation-estimate-design.md`；Plan：`docs/superpowers/plans/2026-09-04-intake-renovation-estimate.md`。
```

并把 `## Last updated` 改为 `2026-09-04`。

- [ ] **Step 4: Commit**

```bash
git add progress.md
git commit -m "docs: record free-preview renovation estimate integration"
```

- [ ] **Step 5: 自审 spec 覆盖**

逐条核对：spec 第 4 节数据模型（Task 1）、第 5 节契约（Task 2/3/5/6）、第 6 节前端（Task 7/8/9）、第 8 节测试（全部 Task）、Out of scope 未越界。若有遗漏先补任务再收尾。

---

## Self-Review Notes

- 计划没有遗留 “TBD/TODO” 占位；每个 Task 有明确失败测试 → 实现 → 通过 → commit 闭环。
- Task 8 的照片证据下拉由 `evidenceField()` 统一生成；demo 模式使用文件名占位且 `evidence_input_id` 为空，真实模式透传上传响应的 `input_id`。
- 类型/方法名跨 Task 一致：`build_intake_renovation_estimate`、`replace_observations`、`saveRenovationObservations`、`renovation_estimate` 字段名从后端贯穿前端。
