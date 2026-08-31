"""Dated public-price snapshot and deterministic rough-estimate rules."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .models import (
    Component,
    Condition,
    Confidence,
    EstimateItem,
    MoneyRange,
    PhotoAnalysis,
    PhotoObservation,
    PhotoRecord,
    PriceSource,
    RenovationEstimateRequest,
    Room,
    Scope,
)


PRICE_SNAPSHOT_VERSION = "jp-renovation-2026-08-31-v1"


@dataclass(frozen=True)
class PriceRule:
    component: Component
    name: str
    unit: str
    low: int
    high: int
    source_refs: Tuple[str, ...]
    assumptions: Tuple[str, ...]


SOURCES: Dict[str, PriceSource] = {
    "unit-bath-reform-guide": PriceSource(
        url="https://www.reform-guide.jp/topics/unitbath-koukan/",
        title="ユニットバスの交換費用を徹底解説！予算別の事例や費用を抑える方法も紹介",
        purpose="ユニットバス一式交换的商品、施工、撤去等综合概算",
        retrieved_on="2026-08-31",
        tax_basis="approximate",
        notes="页面标示整体更换费用为60万～150万日元；税费口径和个案条件需现场确认。",
    ),
    "unit-bath-toto": PriceSource(
        url="https://jp.toto.com/reform/library/cost/bathreformhouse/",
        title="一戸建て浴室リフォームの参考価格 | TOTO",
        purpose="独栋住宅浴室一式更换的商品+工事参考价格交叉核验",
        retrieved_on="2026-08-31",
        tax_basis="tax_included",
        notes="TOTO页面基于其加盟店调查；サザナ一式86万～150万日元（含税），条件为1616尺寸等特定规格。",
    ),
    "wallpaper-homepro": PriceSource(
        url="https://www.homepro.jp/kabegami/kabegami-basic/2270la",
        title="クロス張り替えの単価はいくら？平米単価とメートル単価の違いも解説",
        purpose="标准和高档墙纸（クロス）材料+施工的每平方米参考价格",
        retrieved_on="2026-08-31",
        tax_basis="approximate",
        notes="页面2026-01-16更新；标准クロス约1100～1550日元/m²，高档约1300～1800日元/m²，未含下地调整。",
    ),
    "kitchen-toto": PriceSource(
        url="https://jp.toto.com/reform/library/cost/kitchenreform/",
        title="キッチンリフォームの参考価格 | TOTO",
        purpose="I型2550mm厨房更换并含墙、地、天花内装的参考总价",
        retrieved_on="2026-08-31",
        tax_basis="tax_included",
        notes="TOTO页面标示ミッテ方案76万～133万日元（含税），基于2026年调查与特定规格。",
    ),
    "flooring-homepro": PriceSource(
        url="https://www.homepro.jp/renovation/renovation-point/13461-wg/",
        title="アパートをリフォーム・リノベーションして人気物件に！費用相場や事例も紹介",
        purpose="复合地板更换的施工面积单价换算",
        retrieved_on="2026-08-31",
        tax_basis="approximate",
        notes="页面给出复合地板每10m²约15万～20万日元；地板下地、防音和搬运条件会改变价格。",
    ),
    "toilet-andreform": PriceSource(
        url="https://andreform.jp/article/toilet-cost",
        title="トイレリフォームの費用相場はいくら？種類別価格・工期・補助金を解説",
        purpose="普通洋式便器更换及内装合并的参考区间",
        retrieved_on="2026-08-31",
        tax_basis="approximate",
        notes="页面2026-08-26更新；普通洋式更换约8万～35万日元，含墙纸和地板约15万～50万日元。",
    ),
    "washstand-ishome": PriceSource(
        url="https://ishome.ltd/mizu/reform-guide/washroom/",
        title="2026年最新版 洗面化粧台リフォームの費用相場",
        purpose="洗面化妆台同尺寸更换的地区性参考区间",
        retrieved_on="2026-08-31",
        tax_basis="approximate",
        notes="大阪、兵库、和歌山施工数据；洗面化妆台交换のみ约15万～30万日元，不应直接视为全国报价。",
    ),
    "tatami-meetsmore": PriceSource(
        url="https://meetsmore.com/services/tatami-exchange",
        title="畳張り替え・交換｜業者を費用や口コミで比較",
        purpose="标准畳表替え每畳价格",
        retrieved_on="2026-08-31",
        tax_basis="approximate",
        notes="页面标示基于近两年报价数据；标准类型约8000～10500日元/畳，实际随地区和业者变化。",
    ),
}


RULES: Dict[Component, PriceRule] = {
    "unit_bath": PriceRule(
        "unit_bath",
        "整体卫浴（ユニットバス）更换",
        "job",
        600000,
        1500000,
        ("unit-bath-reform-guide", "unit-bath-toto"),
        ("按一个浴室一式更换估算；尺寸、等级、拆除、给排水、电气和入口复旧需现场确认。",),
    ),
    "wallpaper": PriceRule(
        "wallpaper",
        "墙纸/墙布（クロス）更换",
        "m2",
        1100,
        1550,
        ("wallpaper-homepro",),
        ("按标准量产クロス的材料+施工估算；下地调整、家具移动、废材处理可能另计。",),
    ),
    "flooring": PriceRule(
        "flooring",
        "复合地板更换",
        "m2",
        15000,
        20000,
        ("flooring-homepro",),
        ("按复合地板每10m²的参考总价换算；防音规格、下地修补和拆除可能另计。",),
    ),
    "kitchen": PriceRule(
        "kitchen",
        "系统厨房更换",
        "job",
        760000,
        1330000,
        ("kitchen-toto",),
        ("按I型2550mm基础厨房，并含墙、地、天花部分内装估算；不含布局大改等未知工程。",),
    ),
    "toilet": PriceRule(
        "toilet",
        "厕所设备更换",
        "job",
        80000,
        350000,
        ("toilet-andreform",),
        ("按普通洋式便器及标准撤除、安装估算；给排水移位和内装全面更新可能另计。",),
    ),
    "washstand": PriceRule(
        "washstand",
        "洗面化妆台更换",
        "job",
        150000,
        300000,
        ("washstand-ishome",),
        ("按同尺寸、原位置更换估算；该来源为大阪、兵库、和歌山地区数据。",),
    ),
    "tatami": PriceRule(
        "tatami",
        "畳表替え",
        "mat",
        8000,
        10500,
        ("tatami-meetsmore",),
        ("按标准畳表替え估算；畳尺寸、材料等级和数量折扣会影响价格。",),
    ),
}


ROOM_LABELS: Dict[Room, str] = {
    "exterior": "外立面",
    "bathroom": "卫生间/浴室",
    "kitchen": "厨房",
    "living_room": "客厅",
    "bedroom": "卧室",
    "balcony": "阳台",
}


SCOPE_PRIORITY: Dict[Scope, int] = {
    "replace": 5,
    "surface_refresh": 4,
    "repair": 3,
    "monitor": 2,
    "unknown": 1,
}


CONFIDENCE_PRIORITY: Dict[Confidence, int] = {"high": 3, "medium": 2, "low": 1}


@dataclass
class MergedObservation:
    room: Room
    component: Component
    condition: Condition
    scope: Scope
    confidence: Confidence
    quantity: float
    area_m2: Optional[float]
    notes: List[str] = field(default_factory=list)
    photo_refs: List[str] = field(default_factory=list)


def _merge_observations(photos: Iterable[PhotoRecord]) -> List[MergedObservation]:
    merged: Dict[Tuple[Room, Component], MergedObservation] = {}
    for photo in photos:
        for observation in photo.observations:
            key = (photo.room, observation.component)
            current = merged.get(key)
            if current is None:
                current = MergedObservation(
                    room=photo.room,
                    component=observation.component,
                    condition=observation.condition,
                    scope=observation.scope,
                    confidence=observation.confidence,
                    quantity=observation.quantity,
                    area_m2=observation.area_m2,
                    photo_refs=[],
                )
                merged[key] = current
            current.quantity = max(current.quantity, observation.quantity)
            if observation.area_m2 is not None:
                current.area_m2 = max(current.area_m2 or 0, observation.area_m2)
            if SCOPE_PRIORITY[observation.scope] > SCOPE_PRIORITY[current.scope]:
                current.scope = observation.scope
            if CONFIDENCE_PRIORITY[observation.confidence] > CONFIDENCE_PRIORITY[current.confidence]:
                current.confidence = observation.confidence
            if observation.condition != "unknown":
                current.condition = observation.condition
            if observation.notes and observation.notes not in current.notes:
                current.notes.append(observation.notes)
            if photo.id not in current.photo_refs:
                current.photo_refs.append(photo.id)
    return list(merged.values())


def _context_assumptions(request: RenovationEstimateRequest) -> List[str]:
    context = request.context
    missing = []
    if context.floor_area_m2 is None:
        missing.append("施工面积未提供")
    if context.location_hint is None:
        missing.append("地区提示未提供")
    if context.built_year is None:
        missing.append("房龄未提供")
    if context.structure == "unknown":
        missing.append("住宅结构未提供")
    if context.renovation_goal is None:
        missing.append("装修目标未提供")
    if missing:
        return ["以下字段缺失，区间只能作为保守初筛：" + "、".join(missing)]
    return ["地区、房龄、结构和装修目标仅用于解释价格不确定性，未替代施工公司的现场报价。"]


def build_estimate(
    request: RenovationEstimateRequest,
    *,
    analysis_source: str = "structured_observations",
) -> Dict[str, object]:
    merged = _merge_observations(request.photos)
    items: List[EstimateItem] = []
    limitations: List[str] = []
    source_ids: List[str] = []
    priced_photo_ids = set()

    for observation in merged:
        rule = RULES[observation.component]
        if observation.scope not in {"replace", "surface_refresh"}:
            limitations.append(
                f"{ROOM_LABELS[observation.room]}的{rule.name}状态为{observation.scope}，暂未计价；需要现场确认工程范围。"
            )
            continue
        if rule.unit == "m2" and observation.area_m2 is None:
            limitations.append(
                f"{ROOM_LABELS[observation.room]}的{rule.name}缺少施工面积，未从照片推造面积，因此暂未计价。"
            )
            continue
        quantity = observation.area_m2 if rule.unit == "m2" else observation.quantity
        if quantity is None:
            continue
        low = round(rule.low * quantity)
        high = round(rule.high * quantity)
        photo_observations = observation.notes or [
            f"照片标注：{rule.name}可见状态为{observation.condition}。"
        ]
        item = EstimateItem(
            room=observation.room,
            component=observation.component,
            name=rule.name,
            unit=rule.unit,
            quantity=quantity,
            condition=observation.condition,
            confidence=observation.confidence,
            photo_refs=observation.photo_refs,
            photo_observations=photo_observations,
            estimate_assumptions=list(rule.assumptions),
            range=MoneyRange(low=low, high=high),
            source_refs=[SOURCES[source_id].url for source_id in rule.source_refs],
        )
        items.append(item)
        priced_photo_ids.update(observation.photo_refs)
        for source_id in rule.source_refs:
            if source_id not in source_ids:
                source_ids.append(source_id)

    photo_details = []
    for photo in request.photos:
        photo_details.append(
            {
                "id": photo.id,
                "room": photo.room,
                "observations": [observation.model_dump() for observation in photo.observations],
            }
        )
    if not merged:
        photo_status = "no_observations"
        limitations.append("没有提供可用于估算的室内装修状态观察，未对图片内容作任何猜测。")
    else:
        photo_status = analysis_source

    if not items and merged:
        limitations.append("当前观察只有待确认、维修或监测状态，没有可直接套用的更换工程。")
    if len(priced_photo_ids) < len(request.photos):
        limitations.append("部分照片没有形成可计价项目，可能需要补充清晰角度、尺寸或人工核对。")

    total_low = sum(item.range.low for item in items)
    total_high = sum(item.range.high for item in items)
    assumptions = _context_assumptions(request)
    if request.context.location_hint and request.context.location_hint not in {"大阪市大正区", "大阪府大阪市大正区"}:
        assumptions.append("当前价格快照没有按具体市区町村建立人工费/运输费修正系数。")
    if not request.context.location_hint:
        assumptions.append("当前价格快照未进行地区人工费和运输费修正。")
    confidence: Confidence = "medium" if items and not limitations and all(
        [
            request.context.floor_area_m2 is not None,
            request.context.location_hint is not None,
            request.context.built_year is not None,
            request.context.structure != "unknown",
            request.context.renovation_goal is not None,
        ]
    ) else "low"
    if items and confidence == "low":
        assumptions.append("由于照片覆盖、数量/面积或项目背景不完整，本结果置信度为 low。")
    if not items:
        confidence = "low"

    response = {
        "analysis_id": "ren_" + secrets.token_urlsafe(9),
        "status": "completed",
        "data_class": "modeled_estimate",
        "currency": "JPY",
        "tax_basis": "approximate",
        "price_snapshot_version": PRICE_SNAPSHOT_VERSION,
        "total_range": {"low": total_low, "high": total_high},
        "items": [item.model_dump() for item in items],
        "photo_analysis": PhotoAnalysis(
            status=photo_status,
            provider=(
                "caller_structured_observations"
                if analysis_source == "structured_observations"
                else analysis_source
            ),
            photos=photo_details,
        ).model_dump(),
        "assumptions": assumptions,
        "excluded_items": [
            "管线、承重结构、地基、石棉、防水层、隐藏漏水和法规合规",
            "家具、家电和可移动物品，除非用户明确要求另行估算",
            "未提供面积的墙纸、地板、天花施工量",
        ],
        "sources": [SOURCES[source_id].model_dump() for source_id in source_ids],
        "limitations": [
            "结果是购房/投资初筛级的概算，不是施工报价、贷款评估、法律判断或结构安全鉴定。",
            *limitations,
        ],
    }
    response["confidence"] = confidence
    return response
