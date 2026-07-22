"""Foundational 模块单测（证明骨架可跑绿）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.core.bus import effective_value
from quant.risk.gate import GateChain, GateResult, RiskContext, Verdict
from quant.core.symbol import Market, Symbol
from quant.core.types import OrderRequest, OrderType, Side, Signal


# --- T007 Symbol ---
def test_symbol_uid_roundtrip(btc: Symbol) -> None:
    assert btc.uid == "binance_ums:BTCUSDT"
    assert Symbol.parse(btc.uid) == btc


def test_symbol_parse_rejects_bare() -> None:
    with pytest.raises(ValueError):
        Symbol.parse("BTCUSDT")


# --- T009 总线衰减（CT-SB-2 的纯函数核心）---
def test_effective_value_decays_to_near_zero() -> None:
    sig = Signal("binance_ums:BTCUSDT", "obi", score=1.0, confidence=1.0,
                 half_life_sec=60, evidence=("x",), emitted_at=0)
    # 一个半衰期后 ≈ 0.5
    assert abs(effective_value(sig, now=60) - 0.5) < 1e-6
    # 10 个半衰期后趋近 0（生产者停发 → 优雅降级）
    assert effective_value(sig, now=600) < 0.001


def test_effective_value_half_life_zero_is_dead() -> None:
    sig = Signal("u", "s", 1.0, 1.0, half_life_sec=0, evidence=("x",), emitted_at=0)
    assert effective_value(sig, now=0) == 0.0


# --- T014 闸门链（CT-RG-1 无旁路 + 顺序短路）---
class _AlwaysPass:
    name = "pass"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        return GateResult(Verdict.PASS, self.name)


class _AlwaysHalt:
    name = "halt"

    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult:
        return GateResult(Verdict.HALT, self.name, "test halt")


def _ctx() -> RiskContext:
    return RiskContext(
        equity=Decimal("1000"), hard_floor=Decimal("850"), soft_floor=Decimal("900"),
        total_notional=Decimal("0"), per_symbol_notional={}, daily_pnl_pct=0.0,
        hourly_pnl_pct=0.0, orders_this_hour=0, orders_today=0, used_weight_pct=0.0,
        market_data_age_ms=0, llm_veto=False, capital_weight={}, min_notional={},
    )


def _order() -> OrderRequest:
    return OrderRequest(Symbol(Market.BINANCE_UMS, "BTCUSDT"), Side.BUY,
                        OrderType.MARKET, Decimal("0.01"), "cid-1")


def test_gate_chain_short_circuits_on_halt() -> None:
    chain = GateChain([_AlwaysPass(), _AlwaysHalt(), _AlwaysPass()])
    res = chain.evaluate(_ctx(), _order())
    assert res.verdict is Verdict.HALT
    assert res.gate == "halt"


def test_gate_chain_all_pass() -> None:
    chain = GateChain([_AlwaysPass(), _AlwaysPass()])
    assert chain.evaluate(_ctx(), _order()).ok
