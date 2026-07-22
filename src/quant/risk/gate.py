"""T014 / 接缝3：风控闸门协议 + 链执行器（contracts/risk-gate.md）。

闸门是最终裁决者（宪法 III）：engine 下单前必须完整执行链，无旁路（CT-RG-1）。
新增市场只需 append 闸门，不改动既有闸门（CT-RG-4）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable

from quant.core.types import OrderRequest


class Verdict(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    HALT = "HALT"  # 触发系统 HALTED：全平 + 停机（CT-RG-3）


@dataclass(frozen=True, slots=True)
class GateResult:
    verdict: Verdict
    gate: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.PASS


@dataclass(slots=True)
class RiskContext:
    """闸门评估所需的全部只读状态快照。"""
    equity: Decimal
    hard_floor: Decimal
    soft_floor: Decimal
    total_notional: Decimal
    per_symbol_notional: dict[str, Decimal]
    daily_pnl_pct: float
    hourly_pnl_pct: float
    orders_this_hour: int
    orders_today: int
    used_weight_pct: float
    market_data_age_ms: int
    llm_veto: bool
    capital_weight: dict[str, float]
    min_notional: dict[str, Decimal]
    risk_scale: float = 1.0  # SoftFloor 可下调（G2）


@runtime_checkable
class RiskGate(Protocol):
    name: str

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult: ...


class GateChain:
    """顺序执行；遇 REJECT/HALT 立即停止并返回该结果（CT-RG-1）。"""

    def __init__(self, gates: list[RiskGate]) -> None:
        self._gates = gates

    def evaluate(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        for gate in self._gates:
            result = gate.check(ctx, order)
            if result.verdict is not Verdict.PASS:
                return result
        return GateResult(Verdict.PASS, gate="chain")

    @property
    def gate_names(self) -> list[str]:
        return [g.name for g in self._gates]
