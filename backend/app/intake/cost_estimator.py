"""Acquisition-cost estimation with dated, sourced rules (AGENTS: no hard-coded rates).

Rules live in data/input/acquisition_cost_rules.json (versioned, dated sources).
Items computable from the confirmed asking price are estimated exactly from the
legal upper limits / official tables; items needing valuation basis, loan or
property details are returned as needs_input with an explanation - never guessed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .completeness import ACQUISITION_COST_ITEMS, FieldValue

RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "input" / "acquisition_cost_rules.json"

_rules_cache: dict[str, Any] | None = None


def load_rules() -> dict[str, Any]:
    global _rules_cache
    if _rules_cache is None:
        _rules_cache = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    cached = _rules_cache
    assert cached is not None
    return cached


def _numeric_value(value: Any) -> float | None:
    """Ask price arrives as a confirmed field value; accept int/float or formatted
    digit string (commas/全角 stripped). Returns None when not a clean number."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[,\s，￥¥円万]", "", value.strip())
        if cleaned and re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
            return float(cleaned)
    return None


def _broker_fee_yen(asking_yen: float, rules: Mapping[str, Any]) -> int:
    tiers = rules["broker_fee_upper_limit_yen"]["tiers"]
    if asking_yen <= 2_000_000:
        tier = next(t for t in tiers if t["up_to_yen"] == 2_000_000)
    elif asking_yen <= 4_000_000:
        tier = next(t for t in tiers if t["up_to_yen"] == 4_000_000)
    else:
        tier = next(t for t in tiers if t.get("unbounded"))
    fee = asking_yen * tier["rate"] + tier["base_yen"]
    return round(fee)


def _stamp_duty_yen(asking_yen: float, rules: Mapping[str, Any]) -> int:
    for band in rules["stamp_duty_yen_principal"]["bands"]:
        above = band.get("above_yen", 0)
        up_to = band.get("up_to_yen")
        if asking_yen > above and (up_to is None or asking_yen <= up_to):
            return int(band["tax_yen"])
    return 0


def estimate_acquisition_costs(fields: Mapping[str, FieldValue]) -> dict[str, Any]:
    """Returns per-item acquisition cost lines with status/basis, mirroring the
    ACQUISITION_COST_ITEMS ordering used by the preview contract."""
    rules = load_rules()
    ask_field = fields.get("asking_price_jpy")
    asking_yen = _numeric_value(ask_field.value) if ask_field else None

    items: list[dict[str, Any]] = []
    estimated_total = 0
    incomplete = False

    def needs_input(name: str, key: str) -> None:
        nonlocal incomplete
        incomplete = True
        items.append({"item": name, "status": "needs_input", "estimated_jpy": None, "basis": rules["items_needing_input"][key]})

    if asking_yen is None or asking_yen <= 0:
        note = "缺少已确认的挂牌价/成交价(asking_price_jpy),无法估算金额项。" if ask_field else "缺少挂牌价/成交价输入。"
        return {
            "status": "insufficient_input",
            "estimated_total_jpy": None,
            "items": [
                {"item": name, "status": "needs_input", "estimated_jpy": None, "basis": note if i == 0 else "待补充输入后估算"}
                for i, name in enumerate(ACQUISITION_COST_ITEMS)
            ],
            "calculation_version": f"acquisition-cost-{rules['version']}",
            "note": note,
        }

    # 1. broker fee (legal upper limit, tiered)
    broker = _broker_fee_yen(asking_yen, rules)
    estimated_total += broker
    items.append(
        {
            "item": "中介手续费",
            "status": "estimated",
            "estimated_jpy": broker,
            "basis": "宅建业法报酬上限阶梯(200万以下5%;200万超400万以下4%+2万;400万超3%+6万);另加消费税。",
        }
    )
    # 4. stamp duty (principal bands; relief noted)
    stamp = _stamp_duty_yen(asking_yen, rules)
    estimated_total += stamp
    items.append(
        {
            "item": "印花税",
            "status": "estimated",
            "estimated_jpy": stamp,
            "basis": "国税庁 No.7140 第1号文书(不动产买卖契约书)本则税额;住宅取得轻减措置适用时约半额。",
        }
    )
    # 3. registration tax + notary: tax needs valuation basis; notary industry range
    needs_input("登记许可税和司法书士费用", "registration_tax_and_notary")
    # 2. property acquisition tax: needs valuation
    needs_input("不动产取得税", "property_acquisition_tax")
    # 5-9. need additional inputs
    needs_input("固定资产税、都市计划税及交易清算", "fixed_asset_city_planning_settlement")
    needs_input("贷款手续费、保证费和利息", "loan_related")
    needs_input("火灾险、地震险", "insurance")
    needs_input("汇款、换汇和银行费用", "remittance_forex")
    needs_input("其他有证据的交易费用", "other_evidenced")

    return {
        "status": "partial" if incomplete else "estimated",
        "estimated_total_jpy": estimated_total,
        "items": items,
        "calculation_version": f"acquisition-cost-{rules['version']}",
        "note": "已估项为法定上限/官定表的确定性估算;needs_input 项需评估额/贷款/物件信息后另行估算。合计不含 needs_input 项。",
    }
