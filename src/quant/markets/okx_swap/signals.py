"""欧易盘口信号计算（纯函数，可单测）。

信号只作择时优化，不作独立开仓依据（宪法/spec §7.3）。
大墙 60%+ 为伪装单，用存活时长 + 被吃比例过滤（本文件给原始值，过滤在策略层）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant.core.types import OrderBook, Signal


@dataclass(frozen=True, slots=True)
class Trade:
    price: Decimal
    size: Decimal
    side: str  # "buy" | "sell"（taker 方向）
    ts_ms: int


def order_book_imbalance(book: OrderBook, depth: int = 20) -> float:
    """OBI = (Vbid - Vask)/(Vbid + Vask)，前 depth 档。范围 [-1,1]。"""
    vbid = sum((q for _, q in book.bids[:depth]), Decimal(0))
    vask = sum((q for _, q in book.asks[:depth]), Decimal(0))
    total = vbid + vask
    if total == 0:
        return 0.0
    return float((vbid - vask) / total)


def mid_price(book: OrderBook) -> Decimal:
    if not book.bids or not book.asks:
        return Decimal(0)
    return (book.bids[0][0] + book.asks[0][0]) / 2


def spread_bps(book: OrderBook) -> float:
    if not book.bids or not book.asks:
        return 0.0
    mid = mid_price(book)
    if mid == 0:
        return 0.0
    return float((book.asks[0][0] - book.bids[0][0]) / mid * 10000)


def cvd(trades: list[Trade]) -> Decimal:
    """累计成交量差 = Σ(主动买) - Σ(主动卖)。资金"能量"。"""
    buy = sum((t.size for t in trades if t.side == "buy"), Decimal(0))
    sell = sum((t.size for t in trades if t.side == "sell"), Decimal(0))
    return buy - sell


def detect_walls(book: OrderBook, k: float = 3.0, depth: int = 20) -> dict:
    """挂单墙：单档量 > k×中位档量。用中位数而非均量——大墙会抬高均量导致漏检。

    注意：欧易/币安大墙 60%+ 为伪装单，此处只给原始检测，
    存活时长 + 被吃比例的过滤在策略层做（spec §7.2）。
    """
    def side_wall(levels):
        levels = levels[:depth]
        if not levels:
            return None
        qtys = sorted(q for _, q in levels)
        median = qtys[len(qtys) // 2]
        thresh = median * Decimal(str(k))
        walls = [(p, q) for p, q in levels if q > thresh]
        return max(walls, key=lambda x: x[1]) if walls else None

    return {"bid_wall": side_wall(book.bids), "ask_wall": side_wall(book.asks)}


def funding_skew(current: Decimal, avg_8h: Decimal) -> float:
    """资金费率偏离：正=多头拥挤，负=空头拥挤。"""
    return float(current - avg_8h)


# --- 转成总线 Signal（带半衰期，宪法 II 同轴融合）---
def obi_to_signal(uid: str, book: OrderBook, depth: int = 20) -> Signal:
    obi = order_book_imbalance(book, depth)
    return Signal(uid, "obi", score=obi, confidence=0.6,
                  half_life_sec=30, evidence=(f"obi_{depth}={obi:.3f}",))


def cvd_to_signal(uid: str, trades: list[Trade], scale: Decimal = Decimal(1000)) -> Signal:
    v = cvd(trades)
    score = float(max(Decimal(-1), min(Decimal(1), v / scale)))
    return Signal(uid, "cvd", score=score, confidence=0.5,
                  half_life_sec=60, evidence=(f"cvd={v}",))
