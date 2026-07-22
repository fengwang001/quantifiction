"""T008：核心值对象（data-model A 节）。

纯数据类型，无外部依赖，可独立单测。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from quant.core.symbol import Symbol


# --- 枚举 ---
class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"


class OrderStatus(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


class Settlement(str, Enum):
    T0 = "T0"
    T1 = "T1"


# --- 市场能力（接缝2，宪法 VII）---
@dataclass(frozen=True, slots=True)
class MarketCaps:
    supports_short: bool
    settlement: Settlement
    price_limit_pct: float | None
    min_lot: int
    min_notional: Decimal
    has_l2_depth: bool
    has_liquidation_feed: bool
    trading_calendar: str  # 简化：日历标识（"24/7" / "ashare"）
    contract_val: Decimal = Decimal(1)  # 合约乘数：每张=多少基础币。币安=1(按币计)，欧易读 ctVal


# --- 执行层 ---
@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: Symbol
    side: Side
    type: OrderType
    qty: Decimal
    client_order_id: str  # 幂等键（CT-EG-1）
    price: Decimal | None = None
    reduce_only: bool = False
    stop_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderAck:
    client_order_id: str
    exchange_order_id: str
    status: OrderStatus
    ts: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True, slots=True)
class Fill:
    order_id: str
    price: Decimal
    qty: Decimal
    fee: Decimal
    is_maker: bool
    ts: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True, slots=True)
class Position:
    symbol: Symbol
    side: Side
    qty: Decimal
    entry_px: Decimal
    unrealized_pnl: Decimal
    leverage: int  # 不变量：==1（宪法 III，CT-EG-6）


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    consistent: bool
    detail: str = ""


# --- 订单簿（data-model C5，feed 本地维护）---
@dataclass(slots=True)
class OrderBook:
    symbol_uid: str
    bids: list[tuple[Decimal, Decimal]]  # 降序
    asks: list[tuple[Decimal, Decimal]]  # 升序
    last_update_id: int
    prev_update_id: int  # 上一事件 u，供 pu 校验（CT-MD-1）
    updated_at: int      # ms，供 StaleDataGate

    def age_ms(self, now_ms: int | None = None) -> int:
        return (now_ms if now_ms is not None else int(time.time() * 1000)) - self.updated_at


# --- 信号（contracts/signal-bus.md）---
@dataclass(frozen=True, slots=True)
class Signal:
    symbol_uid: str
    source: str
    score: float        # [-1, 1]
    confidence: float   # [0, 1]
    half_life_sec: float
    evidence: tuple[str, ...] = ()
    emitted_at: int = field(default_factory=lambda: int(time.time()))


# --- LLM 出口（contracts/llm-output.md，宪法 II）---
@dataclass(frozen=True, slots=True)
class LLMSignal:
    symbol_uid: str
    stance: float        # [-1, 1]
    conviction: float    # [0, 0.8]（硬上限）
    veto: bool
    half_life_sec: float
    reasoning: str = ""
    key_risks: tuple[str, ...] = ()
    emitted_at: int = field(default_factory=lambda: int(time.time()))
