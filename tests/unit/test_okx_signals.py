"""欧易信号计算 + WS 消息解析（合成数据，无网络）。"""
from __future__ import annotations

from decimal import Decimal

from quant.core.types import OrderBook
from quant.markets.okx_swap.signals import (
    Trade,
    cvd,
    detect_walls,
    order_book_imbalance,
    obi_to_signal,
    spread_bps,
)
from quant.markets.okx_swap.ws_feed import parse_books_message, parse_trades_message


def _book(bids, asks):
    return OrderBook("okx_swap:ETH-USDT-SWAP",
                     [(Decimal(p), Decimal(q)) for p, q in bids],
                     [(Decimal(p), Decimal(q)) for p, q in asks],
                     last_update_id=1, prev_update_id=0, updated_at=0)


def test_obi_buy_pressure():
    # 买量 > 卖量 → OBI > 0
    book = _book([("100", "10"), ("99", "5")], [("101", "2"), ("102", "1")])
    obi = order_book_imbalance(book)
    assert obi > 0
    # (15-3)/(15+3) = 0.666...
    assert abs(obi - (12/18)) < 1e-9


def test_obi_balanced():
    book = _book([("100", "5")], [("101", "5")])
    assert order_book_imbalance(book) == 0.0


def test_spread_bps():
    book = _book([("100", "1")], [("100.1", "1")])
    assert spread_bps(book) > 0


def test_cvd_signed():
    trades = [Trade(Decimal("100"), Decimal("3"), "buy", 0),
              Trade(Decimal("100"), Decimal("1"), "sell", 0)]
    assert cvd(trades) == Decimal("2")   # 3 buy - 1 sell


def test_detect_wall():
    # 一档远大于均量 → 识别为墙
    book = _book([("100", "1"), ("99", "1"), ("98", "20")],
                 [("101", "1"), ("102", "1")])
    walls = detect_walls(book, k=3.0)
    assert walls["bid_wall"] is not None
    assert walls["bid_wall"][0] == Decimal("98")


def test_obi_signal_evidence_nonempty():
    sig = obi_to_signal("okx_swap:ETH-USDT-SWAP", _book([("100", "5")], [("101", "1")]))
    assert sig.source == "obi" and sig.evidence  # 非空证据（CT-SB-4）


# --- WS 消息解析（OKX 文档格式）---
def test_parse_books_snapshot():
    msg = {"arg": {"channel": "books", "instId": "ETH-USDT-SWAP"}, "action": "snapshot",
           "data": [{"seqId": 100, "prevSeqId": -1, "ts": "1700000000000",
                     "bids": [["1934.05", "12", "0", "3"]], "asks": [["1934.06", "1", "0", "1"]],
                     "checksum": -123}]}
    inst, ev = parse_books_message(msg)
    assert inst == "ETH-USDT-SWAP"
    assert ev.action == "snapshot" and ev.seq_id == 100
    assert ev.bids[0] == (Decimal("1934.05"), Decimal("12"))
    assert ev.checksum == -123


def test_parse_trades():
    msg = {"arg": {"channel": "trades"},
           "data": [{"px": "1934.17", "sz": "740.42", "side": "sell", "ts": "1700000000000"}]}
    trades = parse_trades_message(msg)
    assert trades[0].side == "sell" and trades[0].size == Decimal("740.42")
