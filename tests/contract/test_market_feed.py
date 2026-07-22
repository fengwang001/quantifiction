"""T017：MarketDataFeed 契约测试 CT-MD-1..3（订单簿维护）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.markets.binance_ums.feed import (
    DepthEvent,
    OrderBookMaintainer,
    ResyncRequired,
)


def _snapshot(last_id: int = 100):
    return {"lastUpdateId": last_id, "bids": [["60000", "1"]], "asks": [["60001", "1"]]}


def _ev(U, u, pu, ts=1000, bids=None, asks=None):
    return DepthEvent(U, u, pu, bids or [], asks or [], ts)


def test_ct_md_1_pu_continuity_and_rebuild():
    m = OrderBookMaintainer("binance_ums:BTCUSDT")
    m.load_snapshot(_snapshot(100), ts_ms=1000)

    # 首个衔接事件：U<=101<=u
    m.apply(_ev(101, 105, 100, ts=1100, bids=[(Decimal("60000"), Decimal("2"))]))
    assert m.book.last_update_id == 105
    assert m.book.bids[0] == (Decimal("60000"), Decimal("2"))  # 增量合并生效

    # 后续事件 pu 必须 == 上一 u(105)
    m.apply(_ev(106, 108, 105, ts=1200))
    assert m.book.last_update_id == 108

    # pu 断裂(107 != 108) → 触发重建
    with pytest.raises(ResyncRequired):
        m.apply(_ev(109, 111, 107, ts=1300))


def test_ct_md_1_delete_level_on_zero_qty():
    m = OrderBookMaintainer("u")
    m.load_snapshot(_snapshot(100), ts_ms=1000)
    m.apply(_ev(101, 102, 100, bids=[(Decimal("60000"), Decimal("0"))]))  # 删档
    assert all(p != Decimal("60000") for p, _ in m.book.bids)


def test_ct_md_2_stale_age():
    m = OrderBookMaintainer("u")
    m.load_snapshot(_snapshot(100), ts_ms=1000)
    # 6s 后 → 年龄 > 5000ms（供 StaleDataGate）
    assert m.age_ms(now_ms=1000 + 6000) == 6000


def test_ct_md_3_no_snapshot_requires_resync():
    m = OrderBookMaintainer("u")
    with pytest.raises(ResyncRequired):
        m.apply(_ev(1, 2, 0))
    assert m.age_ms() > 1_000_000  # 无簿视为极陈旧
