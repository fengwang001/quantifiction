"""T016：ExecutionGateway 契约测试 CT-EG-1..6（contracts/execution-gateway.md）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.core.symbol import Market, Symbol
from quant.core.types import OrderRequest, OrderType, Position, Side
from quant.markets.binance_ums.gateway import BinanceGateway, LeverageLockError


class FakeClient:
    """记录调用的假 UMFutures 客户端。"""

    def __init__(self, leverage_return: int = 1, stop_raises: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._lev = leverage_return
        self._stop_raises = stop_raises

    def new_order(self, **p):
        self.calls.append(("new_order", p))
        if p.get("type") == "STOP_MARKET" and self._stop_raises:
            raise RuntimeError("stop rejected by exchange")
        return {"orderId": 111, "status": "NEW"}

    def cancel_order(self, **p):
        self.calls.append(("cancel_order", p)); return {}

    def get_position_risk(self, **p):
        return []

    def change_leverage(self, **p):
        self.calls.append(("change_leverage", p)); return {"leverage": self._lev}

    def change_margin_type(self, **p):
        self.calls.append(("change_margin_type", p)); return {}

    def change_position_mode(self, **p):
        self.calls.append(("change_position_mode", p)); return {}


def _gw(client, binance_caps) -> BinanceGateway:
    return BinanceGateway(client, binance_caps, [Symbol(Market.BINANCE_UMS, "BTCUSDT")])


def _order(cid="cid-1") -> OrderRequest:
    return OrderRequest(Symbol(Market.BINANCE_UMS, "BTCUSDT"), Side.BUY,
                        OrderType.MARKET, Decimal("0.01"), cid)


async def test_ct_eg_1_idempotent(binance_caps):
    c = FakeClient(); gw = _gw(c, binance_caps)
    a1 = await gw.submit(_order("cid-1"))
    a2 = await gw.submit(_order("cid-1"))  # 重复
    assert a1 == a2
    assert sum(1 for k, _ in c.calls if k == "new_order") == 1  # 只下一次单


async def test_ct_eg_2_stop_fail_forces_market_close(binance_caps):
    c = FakeClient(stop_raises=True); gw = _gw(c, binance_caps)
    pos = Position(Symbol(Market.BINANCE_UMS, "BTCUSDT"), Side.BUY,
                   Decimal("0.01"), Decimal("60000"), Decimal("0"), 1)
    with pytest.raises(RuntimeError):
        await gw.place_protective_stop(pos, Decimal("59000"))
    # 兜底市价平仓被触发（reduceOnly market）
    market = [p for k, p in c.calls if k == "new_order" and p.get("type") == "MARKET"]
    assert market and market[0].get("reduceOnly") == "true"


async def test_ct_eg_5_uses_official_client(binance_caps):
    c = FakeClient(); gw = _gw(c, binance_caps)
    await gw.submit(_order())
    assert any(k == "new_order" for k, _ in c.calls)  # 经官方库下单，未自实现签名


async def test_ct_eg_6_leverage_lock_refuses_startup(binance_caps):
    bad = FakeClient(leverage_return=3); gw = _gw(bad, binance_caps)
    with pytest.raises(LeverageLockError):
        await gw.ensure_leverage_locked()

    good = FakeClient(leverage_return=1); gw2 = _gw(good, binance_caps)
    await gw2.ensure_leverage_locked()  # 不抛
    assert any(k == "change_leverage" and p["leverage"] == 1 for k, p in good.calls)


def test_ct_eg_4_caps_driven(binance_caps):
    # caps 暴露能力，供策略层查询而非硬编码市场（CT-EG-4）
    assert binance_caps.has_liquidation_feed is True
    assert binance_caps.min_notional == Decimal("100")


def test_ct_eg_3_reconcile_detects_mismatch():
    from quant.markets.binance_ums.reconcile import compare_positions

    # 交易所侧多出一仓 → 不一致（以交易所为真相）
    exchange = [Position(Symbol(Market.BINANCE_UMS, "BTCUSDT"), Side.BUY,
                         Decimal("0.02"), Decimal("60000"), Decimal("0"), 1)]
    local = {"binance_ums:BTCUSDT": Decimal("0.01")}
    assert compare_positions(local, exchange).consistent is False

    matched = {"binance_ums:BTCUSDT": Decimal("0.02")}
    assert compare_positions(matched, exchange).consistent is True
