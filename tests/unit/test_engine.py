"""T025/T026：Engine 单测（无需交易所，用假网关）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.core.symbol import Market, Symbol
from quant.core.types import (
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderType,
    Position,
    Side,
)
from quant.risk.common_gates import us1_gates
from quant.risk.gate import GateChain, RiskContext
from quant.strategy.engine import Engine, SystemState

BTC = Symbol(Market.BINANCE_UMS, "BTCUSDT")


class FakeGateway:
    def __init__(self, fill=True, positions=None, has_stop=False):
        self._fill = fill
        self._positions = positions or []
        self._has_stop = has_stop
        self.stops: list = []
        self.closed: list = []

    async def submit(self, order):
        status = OrderStatus.FILLED if self._fill else OrderStatus.REJECTED
        return OrderAck(order.client_order_id, "1", status)

    async def positions(self):
        return self._positions

    async def place_protective_stop(self, pos, stop_px):
        self.stops.append((pos.symbol.uid, stop_px)); return OrderAck("s", "2", OrderStatus.SUBMITTED)

    async def has_protective_stop(self, symbol):
        return self._has_stop

    async def market_close(self, pos):
        self.closed.append(pos.symbol.uid)


def _ctx(**o):
    base = dict(equity=Decimal("1000"), hard_floor=Decimal("850"), soft_floor=Decimal("900"),
                total_notional=Decimal("0"), per_symbol_notional={}, daily_pnl_pct=0.0,
                hourly_pnl_pct=0.0, orders_this_hour=0, orders_today=0, used_weight_pct=0.0,
                market_data_age_ms=0, llm_veto=False, capital_weight={}, min_notional={})
    base.update(o); return RiskContext(**base)


def _order():
    return OrderRequest(BTC, Side.BUY, OrderType.MARKET, Decimal("0.01"), "cid")


def _pos():
    return Position(BTC, Side.BUY, Decimal("0.01"), Decimal("60000"), Decimal("0"), 1)


async def test_fill_places_protective_stop():
    gw = FakeGateway(fill=True, positions=[_pos()])
    eng = Engine(gw, GateChain(us1_gates(reconcile_ok=True)))
    ack = await eng.submit_protected(_order(), _ctx())
    assert ack.status is OrderStatus.FILLED
    # 止损价 = 60000 * (1 - 1.5%) = 59100
    assert gw.stops == [("binance_ums:BTCUSDT", Decimal("59100.000"))]


async def test_halt_gate_flats_and_halts():
    gw = FakeGateway(positions=[_pos()])
    eng = Engine(gw, GateChain(us1_gates(reconcile_ok=True)))
    ack = await eng.submit_protected(_order(), _ctx(equity=Decimal("800")))  # 破地板
    assert ack is None
    assert eng.state is SystemState.HALTED
    assert gw.closed == ["binance_ums:BTCUSDT"]  # 全平


async def test_paused_engine_rejects():
    eng = Engine(FakeGateway(), GateChain(us1_gates(reconcile_ok=True)))
    eng.pause()
    assert await eng.submit_protected(_order(), _ctx()) is None


async def test_recover_skips_when_stop_exists():
    gw = FakeGateway(positions=[_pos()], has_stop=True)
    eng = Engine(gw, GateChain(us1_gates(reconcile_ok=True)))
    await eng.recover()
    assert gw.stops == []  # 已有止损 → 不重复挂（T026）


async def test_recover_replaces_missing_stop():
    gw = FakeGateway(positions=[_pos()], has_stop=False)
    eng = Engine(gw, GateChain(us1_gates(reconcile_ok=True)))
    await eng.recover()
    assert len(gw.stops) == 1  # 缺失 → 补挂


async def test_handle_control_flat():
    gw = FakeGateway(positions=[_pos()])
    eng = Engine(gw, GateChain(us1_gates(reconcile_ok=True)))
    await eng.handle_control("flat")
    assert gw.closed == ["binance_ums:BTCUSDT"]


async def test_handle_control_pause_resume():
    eng = Engine(FakeGateway(), GateChain(us1_gates(reconcile_ok=True)))
    await eng.handle_control("pause")
    assert eng.state is SystemState.PAUSED
    await eng.handle_control("resume")
    assert eng.state is SystemState.RUNNING
