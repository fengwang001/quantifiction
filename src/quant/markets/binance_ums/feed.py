"""T021：本地订单簿维护 + WS 行情（contracts/execution-gateway.md CT-MD-1）。

订单簿维护逻辑（OrderBookMaintainer）与 WS 传输解耦，可纯逻辑单测：
币安合约 depth 同步 5 步 + 每事件 `pu == 上一事件 u` 校验，不等即需重建（research R3）。

WS 连接部分复用官方库，在 US1 集成阶段接入；此处提供可测的维护核心。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from quant.core.types import OrderBook


class ResyncRequired(Exception):
    """pu 校验失败或事件早于快照 → 需重新拉快照重建。"""


@dataclass(slots=True)
class DepthEvent:
    """币安 depthUpdate：U=first_update_id, u=final_update_id, pu=prev final u。"""
    first_update_id: int   # U
    final_update_id: int   # u
    prev_update_id: int    # pu（合约独有）
    bids: list[tuple[Decimal, Decimal]]
    asks: list[tuple[Decimal, Decimal]]
    ts_ms: int


class OrderBookMaintainer:
    """按币安官方文档 5 步维护本地订单簿。"""

    def __init__(self, symbol_uid: str) -> None:
        self.symbol_uid = symbol_uid
        self._book: OrderBook | None = None
        self._synced = False  # 是否已衔接首个事件（步骤4只用一次）

    @property
    def book(self) -> OrderBook | None:
        return self._book

    def load_snapshot(self, snapshot: dict[str, Any], ts_ms: int | None = None) -> None:
        """步骤 2：以 REST 快照初始化（lastUpdateId + bids/asks）。"""
        ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
        self._synced = False  # 新快照后需重新衔接
        self._book = OrderBook(
            symbol_uid=self.symbol_uid,
            bids=[(Decimal(p), Decimal(q)) for p, q in snapshot["bids"]],
            asks=[(Decimal(p), Decimal(q)) for p, q in snapshot["asks"]],
            last_update_id=int(snapshot["lastUpdateId"]),
            prev_update_id=int(snapshot["lastUpdateId"]),
            updated_at=ts,
        )

    def apply(self, ev: DepthEvent) -> None:
        """步骤 3-5 + 合约 pu 校验。违反则抛 ResyncRequired。"""
        if self._book is None:
            raise ResyncRequired("no snapshot loaded")
        last = self._book.last_update_id

        # 步骤 3：丢弃 u < lastUpdateId 的陈旧事件
        if ev.final_update_id < last:
            return

        if not self._synced:
            # 步骤 4：快照后第一个事件须满足 U <= lastUpdateId+1 <= u
            if not (ev.first_update_id <= last + 1 <= ev.final_update_id):
                raise ResyncRequired(
                    f"首个事件未衔接快照：U={ev.first_update_id} u={ev.final_update_id} last={last}"
                )
            self._synced = True
        else:
            # 步骤 5（合约独有）：其后每个事件 pu 必须等于上一事件 u
            if ev.prev_update_id != last:
                raise ResyncRequired(
                    f"pu {ev.prev_update_id} != prev u {last} — 订单簿错位，需重建"
                )

        self._merge(self._book.bids, ev.bids, reverse=True)
        self._merge(self._book.asks, ev.asks, reverse=False)
        self._book.last_update_id = ev.final_update_id
        self._book.prev_update_id = last
        self._book.updated_at = ev.ts_ms

    @staticmethod
    def _merge(
        side: list[tuple[Decimal, Decimal]],
        updates: list[tuple[Decimal, Decimal]],
        reverse: bool,
    ) -> None:
        book = dict(side)
        for price, qty in updates:
            if qty == 0:
                book.pop(price, None)   # 数量 0 表示删档
            else:
                book[price] = qty
        side[:] = sorted(book.items(), key=lambda kv: kv[0], reverse=reverse)

    def age_ms(self, now_ms: int | None = None) -> int:
        if self._book is None:
            return 1 << 30  # 无簿 → 视为极陈旧，触发 StaleDataGate
        return self._book.age_ms(now_ms)
