"""T018：RiskGate 契约测试 CT-RG-1..4 + G1/G7/G11/G12。"""
from __future__ import annotations

from decimal import Decimal

from quant.core.symbol import Market, Symbol
from quant.core.types import OrderRequest, OrderType, Side
from quant.risk.common_gates import (
    HardFloorGate,
    HourlyLossGate,
    ReconcileGate,
    StaleDataGate,
    us1_gates,
)
from quant.risk.gate import GateChain, RiskContext, Verdict


def _ctx(**over):
    base = dict(
        equity=Decimal("1000"), hard_floor=Decimal("850"), soft_floor=Decimal("900"),
        total_notional=Decimal("0"), per_symbol_notional={}, daily_pnl_pct=0.0,
        hourly_pnl_pct=0.0, orders_this_hour=0, orders_today=0, used_weight_pct=0.0,
        market_data_age_ms=0, llm_veto=False, capital_weight={}, min_notional={},
    )
    base.update(over)
    return RiskContext(**base)


def _order():
    return OrderRequest(Symbol(Market.BINANCE_UMS, "BTCUSDT"), Side.BUY,
                        OrderType.MARKET, Decimal("0.01"), "cid")


def test_g1_hard_floor_halts():
    r = HardFloorGate().check(_ctx(equity=Decimal("849")), _order())
    assert r.verdict is Verdict.HALT


def test_g7_hourly_loss_halts():
    r = HourlyLossGate().check(_ctx(hourly_pnl_pct=-3.5), _order())
    assert r.verdict is Verdict.HALT


def test_g11_reconcile_rejects_on_mismatch():
    assert ReconcileGate(reconcile_ok=False).check(_ctx(), _order()).verdict is Verdict.REJECT
    assert ReconcileGate(reconcile_ok=True).check(_ctx(), _order()).ok


def test_g12_stale_data_rejects():
    r = StaleDataGate().check(_ctx(market_data_age_ms=6000), _order())
    assert r.verdict is Verdict.REJECT


def test_ct_rg_1_chain_no_bypass_short_circuit():
    # G1 HALT 时后续闸门不执行（顺序 + 无旁路）
    chain = GateChain(us1_gates(reconcile_ok=True))
    res = chain.evaluate(_ctx(equity=Decimal("800")), _order())
    assert res.verdict is Verdict.HALT
    assert res.gate == "G1_HardFloor"


def test_ct_rg_1_all_pass_when_healthy():
    chain = GateChain(us1_gates(reconcile_ok=True))
    assert chain.evaluate(_ctx(), _order()).ok
