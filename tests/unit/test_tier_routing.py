"""T037：tier 路由——live 下单 / shadow 记账 / observe 跳过。"""
from __future__ import annotations

from decimal import Decimal

from quant.core.types import OrderAck, OrderStatus, Position, Side
from quant.risk.gate import GateChain, RiskContext
from quant.risk.common_gates import full_gate_chain
from quant.strategy.engine import Engine
from quant.strategy.shadow import ShadowFill
from tests.unit.test_engine import FakeGateway, _ctx  # 复用


def _pos(raw="ETHUSDT"):
    from quant.core.symbol import Market, Symbol
    return Position(Symbol(Market.BINANCE_UMS, raw), Side.BUY,
                    Decimal("0.3"), Decimal("3000"), Decimal("0"), 1)


def _engine(gw):
    return Engine(gw, GateChain(full_gate_chain(reconcile_ok=True)))


async def _route(eng, tier):
    from quant.core.symbol import Market
    # 路由逻辑与市场无关；用 binance 假仓位测（OKX 网关由 test_okx_gateway 覆盖）。
    return await eng.route_by_tier(
        raw="ETHUSDT", tier=tier, strategy="liq_reversal", side=Side.BUY,
        price=Decimal("3000"), risk_usd=Decimal("15"), stop_pct=Decimal("0.015"),
        equity=Decimal("2000"), capital_weight=Decimal("0.7"),
        min_notional=Decimal("20"), ctx=_ctx(equity=Decimal("2000")),
        market=Market.BINANCE_UMS,
    )


async def test_live_submits_and_protects():
    gw = FakeGateway(fill=True, positions=[_pos()])
    out = await _route(_engine(gw), "live")
    assert isinstance(out, OrderAck) and out.status is OrderStatus.FILLED
    assert gw.stops  # 挂了止损


async def test_shadow_records_no_order():
    gw = FakeGateway(fill=True, positions=[_pos()])
    out = await _route(_engine(gw), "shadow")
    assert isinstance(out, ShadowFill)
    assert gw.stops == []  # shadow 绝不触网关（FR-008）


async def test_observe_skips():
    gw = FakeGateway()
    assert await _route(_engine(gw), "observe") is None
