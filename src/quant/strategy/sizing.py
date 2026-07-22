"""T034：仓位计算（宪法 I，FR-007）。

以工作资金风险预算为基数（非全部本金）：
    单笔风险 = 工作资金 × 10%（$150→$15 / $100 阶段 $15→$1.5）
    名义敞口 = 单笔风险 / 止损幅度
    数量     = 名义敞口 / 价格
容量约束：名义 ∈ [min_notional×1.1, equity×capital_weight]。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MIN_NOTIONAL_BUFFER = Decimal("1.1")


@dataclass(frozen=True, slots=True)
class SizingResult:
    ok: bool
    qty: Decimal
    notional: Decimal
    reason: str = ""


def target_notional(risk_usd: Decimal, stop_pct: Decimal) -> Decimal:
    if stop_pct <= 0:
        raise ValueError("stop_pct 必须 > 0")
    return risk_usd / stop_pct


def size_order(
    price: Decimal,
    risk_usd: Decimal,
    stop_pct: Decimal,
    equity: Decimal,
    capital_weight: Decimal,
    min_notional: Decimal,
    contract_val: Decimal = Decimal(1),
) -> SizingResult:
    """qty 语义：币安为基础币数量（ctVal=1）；欧易为合约张数（qty=名义/(价格×ctVal)）。"""
    notional = target_notional(risk_usd, stop_pct)

    cap = equity * capital_weight
    if notional > cap:
        notional = cap  # 收敛到单标的敞口上限（G14 会二次把关）

    floor = min_notional * MIN_NOTIONAL_BUFFER
    if notional < floor:
        return SizingResult(
            False, Decimal(0), notional,
            f"名义 {notional} < 最小 {floor}（资金不足以在该标的安全下单）",
        )

    if price <= 0 or contract_val <= 0:
        return SizingResult(False, Decimal(0), notional, "价格或合约乘数非法")
    qty = notional / (price * contract_val)
    return SizingResult(True, qty, notional)
