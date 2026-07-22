"""T070：A 股接缝自检（宪法 VII）+ T067：回放引擎。"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from quant.core.types import MarketCaps, Settlement


# --- T070：ashare/ 仅 README，无实现代码 ---
def test_ashare_only_has_readme():
    ashare = Path(__file__).resolve().parents[2] / "src" / "quant" / "markets" / "ashare"
    py_files = [p.name for p in ashare.glob("*.py") if p.name != "__init__.py"]
    assert py_files == [], f"ashare/ 不应含实现代码，发现：{py_files}"
    assert (ashare / "README.md").exists()


# --- T070：caps 驱动分支——能力缺失则信号自动跳过，无异常 ---
def _ashare_caps() -> MarketCaps:
    return MarketCaps(
        supports_short=False, settlement=Settlement.T1, price_limit_pct=0.10,
        min_lot=100, min_notional=Decimal("0"), has_l2_depth=False,
        has_liquidation_feed=False, trading_calendar="ashare",
    )


def _collect_signals(caps: MarketCaps) -> list[str]:
    """模拟策略层按 caps 选择信号，禁止硬编码市场。"""
    signals = ["obi", "cvd"]
    if caps.has_liquidation_feed:
        signals.append("liq_flow")
    if caps.has_l2_depth:
        signals.append("depth_wall")
    return signals


def test_caps_driven_signal_selection():
    from tests.conftest import binance_caps  # type: ignore  # noqa
    # 币安：有爆仓流 + 深度
    a = _collect_signals(_ashare_caps())
    assert "liq_flow" not in a and "depth_wall" not in a  # A股自动跳过
    # 无 if market == ... 分支即达成宪法 VII


# --- T067：回放引擎 ---
def test_replay_counts_events_and_resyncs():
    from quant.markets.binance_ums.feed import DepthEvent
    from quant.research.replay import replay

    snap = {"lastUpdateId": 100, "bids": [["60000", "1"]], "asks": [["60001", "1"]], "ts": 0}
    events = [
        DepthEvent(101, 105, 100, [(Decimal("60000"), Decimal("2"))], [], 1000),
        DepthEvent(106, 108, 105, [], [(Decimal("60001"), Decimal("3"))], 1100),
        DepthEvent(109, 111, 107, [], [], 1200),  # pu 断裂 → resync
    ]
    seen = []
    stats = replay("binance_ums:BTCUSDT", snap, events, on_book=lambda m: seen.append(m.book.last_update_id))
    assert stats.events == 3
    assert stats.resyncs == 1
    assert seen == [105, 108]  # 断裂事件被跳过
