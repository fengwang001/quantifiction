"""T013 / 接缝2：市场接入协议（contracts/execution-gateway.md）。

strategy 层只依赖这些协议，不依赖任何具体市场实现（宪法 VII）。
A 股接入时实现同一组协议于 markets/ashare/。
"""
from __future__ import annotations

from decimal import Decimal
from typing import AsyncIterator, Protocol, runtime_checkable

from quant.core.types import (
    MarketCaps,
    OrderAck,
    OrderBook,
    OrderRequest,
    Position,
    ReconcileResult,
)


@runtime_checkable
class ExecutionGateway(Protocol):
    async def submit(self, order: OrderRequest) -> OrderAck: ...

    async def cancel(self, client_order_id: str) -> None: ...

    async def positions(self) -> list[Position]: ...

    async def reconcile(self) -> ReconcileResult: ...

    async def place_protective_stop(self, pos: Position, stop_px: Decimal) -> OrderAck: ...

    async def ensure_leverage_locked(self) -> None:
        """CT-EG-6：设杠杆=1 / CROSSED / 单向并校验；不一致须拒绝启动。"""
        ...

    @property
    def caps(self) -> MarketCaps: ...


@runtime_checkable
class MarketDataFeed(Protocol):
    async def subscribe(self, symbols: list) -> None: ...

    def orderbook(self, uid: str) -> OrderBook: ...

    def last_update_age_ms(self, uid: str) -> int: ...

    def stream_events(self) -> AsyncIterator: ...
