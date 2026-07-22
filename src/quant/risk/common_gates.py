"""T024：US1 风控闸门子集 G1/G7/G11/G12（contracts/risk-gate.md）。

其余 G2-G6/G8-G10/G13/G14 在 US2（T035）补全。
闸门是纯函数式判断，可脱离交易所单测。
"""
from __future__ import annotations

from decimal import Decimal

from quant.core.types import OrderRequest
from quant.risk.gate import GateResult, RiskContext, Verdict


class HardFloorGate:
    """G1：权益跌破硬地板 → HALT（全平停机，宪法 I）。"""

    name = "G1_HardFloor"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.equity < ctx.hard_floor:
            return GateResult(
                Verdict.HALT, self.name,
                f"equity {ctx.equity} < hard_floor {ctx.hard_floor}",
            )
        return GateResult(Verdict.PASS, self.name)


class HourlyLossGate:
    """G7：单小时亏损 > 3% → HALT。"""

    name = "G7_HourlyLoss"
    limit_pct = -3.0

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.hourly_pnl_pct < self.limit_pct:
            return GateResult(
                Verdict.HALT, self.name,
                f"hourly_pnl {ctx.hourly_pnl_pct}% < {self.limit_pct}%",
            )
        return GateResult(Verdict.PASS, self.name)


class ReconcileGate:
    """G11：本地仓位与交易所不一致 → REJECT（并触发对账停机，CT-EG-3）。

    一致性由 engine 事先写入 ctx（reconcile_ok）；此闸门只做判定。
    """

    name = "G11_Reconcile"

    def __init__(self, reconcile_ok: bool) -> None:
        self._ok = reconcile_ok

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if not self._ok:
            return GateResult(Verdict.REJECT, self.name, "local/exchange position mismatch")
        return GateResult(Verdict.PASS, self.name)


class StaleDataGate:
    """G12：行情最后更新 > 5s → REJECT（宪法 III / CT-MD-2）。"""

    name = "G12_StaleData"
    max_age_ms = 5000

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.market_data_age_ms > self.max_age_ms:
            return GateResult(
                Verdict.REJECT, self.name,
                f"market data age {ctx.market_data_age_ms}ms > {self.max_age_ms}ms",
            )
        return GateResult(Verdict.PASS, self.name)


class SoftFloorGate:
    """G2：权益跌破软地板 → 风险参数减半（PASS 但改 ctx.risk_scale）。"""

    name = "G2_SoftFloor"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.equity < ctx.soft_floor:
            ctx.risk_scale = min(ctx.risk_scale, 0.5)
        return GateResult(Verdict.PASS, self.name)


class MaxExposureGate:
    """G3：总名义 > equity×1.0 → REJECT。"""

    name = "G3_MaxExposure"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.total_notional > ctx.equity:
            return GateResult(Verdict.REJECT, self.name,
                              f"total {ctx.total_notional} > equity {ctx.equity}")
        return GateResult(Verdict.PASS, self.name)


class PerSymbolGate:
    """G4：单标的 > equity×0.7 → REJECT。"""

    name = "G4_PerSymbol"
    ratio = Decimal("0.7")

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        cur = ctx.per_symbol_notional.get(order.symbol.uid, Decimal(0))
        if cur > ctx.equity * self.ratio:
            return GateResult(Verdict.REJECT, self.name, f"{order.symbol.uid} {cur} > 70%")
        return GateResult(Verdict.PASS, self.name)


class CorrelationGate:
    """G5：相关标的同向合计 > equity×1.0 → REJECT。

    相关簇按标的 raw 名的基础币判定（BTC/ETH），与交易所无关（宪法 VII，
    不硬编码某交易所的 uid）。
    """

    name = "G5_Correlation"
    _correlated_bases = {"BTC", "ETH"}

    def _base(self, uid: str) -> str:
        raw = uid.split(":")[-1]  # ETH-USDT-SWAP / ETHUSDT
        return raw.replace("-", "").upper()[:3]

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if self._base(order.symbol.uid) not in self._correlated_bases:
            return GateResult(Verdict.PASS, self.name)
        total = sum(
            (n for u, n in ctx.per_symbol_notional.items()
             if self._base(u) in self._correlated_bases),
            Decimal(0),
        )
        if total > ctx.equity:
            return GateResult(Verdict.REJECT, self.name, f"correlated {total} > equity")
        return GateResult(Verdict.PASS, self.name)


class DailyDrawdownGate:
    """G6：当日亏损 > 3% → REJECT（至次日 UTC0）。"""

    name = "G6_DailyDrawdown"
    limit_pct = -3.0

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.daily_pnl_pct < self.limit_pct:
            return GateResult(Verdict.REJECT, self.name, f"daily {ctx.daily_pnl_pct}%")
        return GateResult(Verdict.PASS, self.name)


class OrderRateGate:
    """G8：单小时 > 10 或 单日 > 20 → REJECT。"""

    name = "G8_OrderRate"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.orders_this_hour >= 10 or ctx.orders_today >= 20:
            return GateResult(Verdict.REJECT, self.name,
                              f"rate h={ctx.orders_this_hour} d={ctx.orders_today}")
        return GateResult(Verdict.PASS, self.name)


class MinNotionalGate:
    """G9：名义 < min_notional×1.1 → REJECT。"""

    name = "G9_MinNotional"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        mn = ctx.min_notional.get(order.symbol.uid)
        if mn is None:
            return GateResult(Verdict.PASS, self.name)
        notional = ctx.per_symbol_notional.get(order.symbol.uid, Decimal(0))
        if 0 < notional < mn * Decimal("1.1"):
            return GateResult(Verdict.REJECT, self.name, f"{notional} < {mn}×1.1")
        return GateResult(Verdict.PASS, self.name)


class RateLimitGate:
    """G10：币安权重占用 > 80% → REJECT（降频）。"""

    name = "G10_RateLimit"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.used_weight_pct > 80.0:
            return GateResult(Verdict.REJECT, self.name, f"weight {ctx.used_weight_pct}%")
        return GateResult(Verdict.PASS, self.name)


class LLMVetoGate:
    """G13：认知层 veto → REJECT（宪法 II）。"""

    name = "G13_LLMVeto"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        if ctx.llm_veto:
            return GateResult(Verdict.REJECT, self.name, "LLM veto")
        return GateResult(Verdict.PASS, self.name)


class SymbolCapGate:
    """G14：单标的 > equity×capital_weight → REJECT。"""

    name = "G14_SymbolCap"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        w = ctx.capital_weight.get(order.symbol.uid)
        if w is None:
            return GateResult(Verdict.PASS, self.name)
        cur = ctx.per_symbol_notional.get(order.symbol.uid, Decimal(0))
        if cur > ctx.equity * Decimal(str(w)):
            return GateResult(Verdict.REJECT, self.name, f"{cur} > cap {w}")
        return GateResult(Verdict.PASS, self.name)


def us1_gates(reconcile_ok: bool) -> list:
    """US1 阶段的闸门链（顺序：先致命 HALT，再 REJECT）。"""
    return [HardFloorGate(), HourlyLossGate(), ReconcileGate(reconcile_ok), StaleDataGate()]


def full_gate_chain(reconcile_ok: bool) -> list:
    """US2 起的完整闸门链 G1-G14（HALT 类靠前）。"""
    return [
        HardFloorGate(),        # G1 HALT
        HourlyLossGate(),       # G7 HALT
        ReconcileGate(reconcile_ok),  # G11
        StaleDataGate(),        # G12
        SoftFloorGate(),        # G2
        MaxExposureGate(),      # G3
        PerSymbolGate(),        # G4
        CorrelationGate(),      # G5
        DailyDrawdownGate(),    # G6
        OrderRateGate(),        # G8
        MinNotionalGate(),      # G9
        RateLimitGate(),        # G10
        LLMVetoGate(),          # G13
        SymbolCapGate(),        # G14
    ]
