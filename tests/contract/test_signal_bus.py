"""T017a：信号总线契约测试 CT-SB-1..4（contracts/signal-bus.md）【C2】。"""
from __future__ import annotations

import pytest

from quant.core.bus import SignalBus, effective_value
from quant.core.types import Signal


def _sig(source, score, hl, emitted=0, ev=("x",)):
    return Signal("binance_ums:BTCUSDT", source, score, 1.0, hl, ev, emitted_at=emitted)


def test_ct_sb_1_fast_slow_same_axis():
    # 快信号(盘口，短 half_life)与慢信号(政策，长 half_life)在同一数轴相加
    fast = _sig("obi", 0.4, hl=30)
    slow = _sig("policy", 0.3, hl=7200)
    total = effective_value(fast, now=0) + effective_value(slow, now=0)
    assert total == pytest.approx(0.7)


def test_ct_sb_2_producer_stops_decays_to_zero():
    # 生产者停发 → Δt 增大 → effective 自然衰减到 ~0（优雅降级，宪法 II）
    s = _sig("obi", 1.0, hl=60, emitted=0)
    assert effective_value(s, now=60) == pytest.approx(0.5)
    assert effective_value(s, now=600) < 1e-3


def test_ct_sb_3_uid_indexed():
    from quant.core.bus import _stream_key
    assert _stream_key("binance_ums:BTCUSDT") == "signals:binance_ums:BTCUSDT"


async def test_ct_sb_4_evidence_required():
    # evidence 为空 → 拒绝发布（事后归因需要）
    class _FakeRedis:
        async def xadd(self, *a, **k):  # pragma: no cover - 不应被调用
            raise AssertionError("不应发布空 evidence 信号")

    bus = SignalBus(_FakeRedis())
    with pytest.raises(ValueError):
        await bus.publish(_sig("obi", 0.5, hl=60, ev=()))
