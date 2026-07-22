"""欧易网关 + 订单簿 + 签名 契约测试（对齐 CT-EG / CT-MD）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.core.symbol import Market, Symbol
from quant.core.types import MarketCaps, OrderRequest, OrderType, Position, Settlement, Side
from quant.markets.okx_swap.feed import BookEvent, OKXOrderBookMaintainer, ResyncRequired
from quant.markets.okx_swap.gateway import LeverageLockError, OKXGateway
from quant.markets.okx_swap.okx_client import sign


def _caps():
    return MarketCaps(True, Settlement.T0, None, 1, Decimal(0), True, True, "24/7",
                      contract_val=Decimal("0.1"))


class FakeOKX:
    def __init__(self, lever="1", stop_raises=False):
        self.calls = []
        self._lever = lever
        self._stop_raises = stop_raises

    def place_order(self, **p):
        self.calls.append(("place_order", p))
        return [{"ordId": "42", "sCode": "0"}]

    def place_algo_order(self, **p):
        self.calls.append(("place_algo_order", p))
        if self._stop_raises:
            raise RuntimeError("sl rejected")
        return [{"algoId": "77", "sCode": "0"}]

    def cancel_order(self, **p):
        self.calls.append(("cancel_order", p)); return [{}]

    def positions(self, inst_type="SWAP"):
        return []

    def set_leverage(self, **p):
        self.calls.append(("set_leverage", p)); return [{"lever": self._lever}]

    def request(self, method, path, params=None):
        if "account/config" in path:
            return [{"acctLv": "2", "posMode": "net_mode"}]  # 合法：单币种保证金
        return []


ETH = Symbol(Market.OKX_SWAP, "ETH-USDT-SWAP")


def _gw(c):
    return OKXGateway(c, _caps(), [ETH])


def _order(cid="s1"):
    return OrderRequest(ETH, Side.BUY, OrderType.MARKET, Decimal("1"), cid)


# --- 鉴权签名（三要素）---
def test_sign_deterministic():
    s = sign("2026-07-21T00:00:00.000Z", "GET", "/api/v5/account/positions", "", "secret")
    assert isinstance(s, str) and len(s) > 0
    # 相同输入 → 相同签名
    assert s == sign("2026-07-21T00:00:00.000Z", "GET", "/api/v5/account/positions", "", "secret")


# --- CT-EG-1 幂等 ---
async def test_idempotent_submit():
    c = FakeOKX(); gw = _gw(c)
    a1 = await gw.submit(_order("s1"))
    a2 = await gw.submit(_order("s1"))
    assert a1 == a2
    assert sum(1 for k, _ in c.calls if k == "place_order") == 1


# --- CT-EG-6 杠杆锁定 ---
async def test_leverage_lock_refuses():
    with pytest.raises(LeverageLockError):
        await _gw(FakeOKX(lever="3")).ensure_leverage_locked()
    await _gw(FakeOKX(lever="1")).ensure_leverage_locked()  # 不抛


# --- CT-EG-2 止损失败即市价平仓 ---
async def test_stop_fail_forces_close():
    c = FakeOKX(stop_raises=True); gw = _gw(c)
    pos = Position(ETH, Side.BUY, Decimal("1"), Decimal("3000"), Decimal("0"), 1)
    with pytest.raises(RuntimeError):
        await gw.place_protective_stop(pos, Decimal("2955"))
    mkt = [p for k, p in c.calls if k == "place_order" and p.get("ordType") == "market"]
    assert mkt and mkt[0].get("reduceOnly") == "true"


# --- clOrdId 清洗（欧易仅字母数字）---
async def test_clordid_sanitized():
    c = FakeOKX(); gw = _gw(c)
    await gw.submit(_order("liq_reversal-ETH-USDT-SWAP-3"))
    cl = c.calls[0][1]["clOrdId"]
    assert cl.isalnum() and len(cl) <= 32


# --- CT-MD-1 订单簿 seqId 续接 + 断裂重建 ---
def test_orderbook_seq_continuity_and_break():
    m = OKXOrderBookMaintainer("okx_swap:ETH-USDT-SWAP")
    m.apply(BookEvent("snapshot", 100, -1, [(Decimal("3000"), Decimal("5"))],
                      [(Decimal("3001"), Decimal("5"))], 1000))
    m.apply(BookEvent("update", 101, 100, [(Decimal("3000"), Decimal("7"))], [], 1100))
    assert m.book.last_update_id == 101
    assert m.book.bids[0] == (Decimal("3000"), Decimal("7"))
    # prevSeqId 断裂（99 != 101）→ 重建
    with pytest.raises(ResyncRequired):
        m.apply(BookEvent("update", 102, 99, [], [], 1200))


def test_orderbook_checksum_mismatch_triggers_resync():
    m = OKXOrderBookMaintainer("u")
    m.apply(BookEvent("snapshot", 1, -1, [(Decimal("100"), Decimal("1"))],
                      [(Decimal("101"), Decimal("1"))], 1000))
    with pytest.raises(ResyncRequired):
        m.apply(BookEvent("update", 2, 1, [], [], 1100, checksum=123456))  # 错误校验和
