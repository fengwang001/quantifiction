"""T067：订单簿回放回测引擎（research R11，宪法 VI）。

基于自录 tick（Parquet）逐事件重放，驱动 OrderBookMaintainer 与信号计算，
产出可归因的假想成交。币安无历史 L2 深度，自录数据是唯一可信来源。

回放核心为纯逻辑：给定有序事件流，重建订单簿并回调策略。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Iterator

from quant.markets.binance_ums.feed import DepthEvent, OrderBookMaintainer, ResyncRequired


@dataclass
class ReplayStats:
    events: int = 0
    resyncs: int = 0
    signals_emitted: int = 0


def read_depth_parquet(path: Path) -> Iterator[DepthEvent]:
    """从 orderbook_delta Parquet 读取有序 DepthEvent。"""
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    rows = table.to_pylist()
    # 同一 ts 的 bid/ask 合成一个事件的简化模型：逐行成独立事件
    for r in rows:
        side = r["side"]
        level = (Decimal(str(r["price"])), Decimal(str(r["qty"])))
        yield DepthEvent(
            first_update_id=r["first_update_id"],
            final_update_id=r["final_update_id"],
            prev_update_id=r["pu"],
            bids=[level] if side == "bid" else [],
            asks=[level] if side == "ask" else [],
            ts_ms=r["ts"],
        )


def replay(
    symbol_uid: str,
    snapshot: dict,
    events: Iterable[DepthEvent],
    on_book: Callable[[OrderBookMaintainer], None] | None = None,
) -> ReplayStats:
    """重放事件流，pu 断裂时统计 resync（回测中记为缺口，不中断）。"""
    m = OrderBookMaintainer(symbol_uid)
    m.load_snapshot(snapshot, ts_ms=snapshot.get("ts", 0))
    stats = ReplayStats()
    for ev in events:
        stats.events += 1
        try:
            m.apply(ev)
        except ResyncRequired:
            stats.resyncs += 1
            # 真实系统会重拉快照；回测中跳过该事件并继续
            continue
        if on_book is not None:
            on_book(m)
    return stats
