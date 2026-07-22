"""欧易 SWAP 本地订单簿维护（CT-MD-1 等价物）。

欧易 books 频道：每条消息带 seqId 与 prevSeqId，续接校验 prevSeqId == 上一条 seqId
（等价于币安的 pu 校验）；并可用 checksum(CRC32) 校验前 25 档一致性。
断裂即抛 ResyncRequired 触发重订阅/重拉快照。维护核心纯逻辑，可单测。
"""
from __future__ import annotations

import time
import zlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from quant.core.types import OrderBook


class ResyncRequired(Exception):
    pass


@dataclass(slots=True)
class BookEvent:
    action: str                 # "snapshot" | "update"
    seq_id: int
    prev_seq_id: int            # -1 表示无前序（snapshot）
    bids: list[tuple[Decimal, Decimal]]
    asks: list[tuple[Decimal, Decimal]]
    ts_ms: int
    checksum: int | None = None


class OKXOrderBookMaintainer:
    def __init__(self, symbol_uid: str) -> None:
        self.symbol_uid = symbol_uid
        self._book: OrderBook | None = None
        self._last_seq = -1

    @property
    def book(self) -> OrderBook | None:
        return self._book

    def apply(self, ev: BookEvent) -> None:
        if ev.action == "snapshot":
            self._book = OrderBook(
                symbol_uid=self.symbol_uid,
                bids=sorted(ev.bids, key=lambda x: x[0], reverse=True),
                asks=sorted(ev.asks, key=lambda x: x[0]),
                last_update_id=ev.seq_id,
                prev_update_id=ev.prev_seq_id,
                updated_at=ev.ts_ms,
            )
            self._last_seq = ev.seq_id
            return

        if self._book is None:
            raise ResyncRequired("no snapshot loaded")
        # 续接校验：prevSeqId 必须等于上一条 seqId（等价 pu 校验）
        if ev.prev_seq_id != self._last_seq:
            raise ResyncRequired(
                f"prevSeqId {ev.prev_seq_id} != last seqId {self._last_seq} — 订单簿错位"
            )
        _merge(self._book.bids, ev.bids, reverse=True)
        _merge(self._book.asks, ev.asks, reverse=False)
        self._book.prev_update_id = self._last_seq
        self._book.last_update_id = ev.seq_id
        self._book.updated_at = ev.ts_ms
        self._last_seq = ev.seq_id

        if ev.checksum is not None:
            got = crc32_checksum(self._book)
            if got != ev.checksum:
                raise ResyncRequired(f"checksum 不符：本地 {got} != 推送 {ev.checksum}")

    def age_ms(self, now_ms: int | None = None) -> int:
        if self._book is None:
            return 1 << 30
        return self._book.age_ms(now_ms)


def _merge(side: list[tuple[Decimal, Decimal]], updates: list[tuple[Decimal, Decimal]],
           reverse: bool) -> None:
    book = dict(side)
    for price, qty in updates:
        if qty == 0:
            book.pop(price, None)
        else:
            book[price] = qty
    side[:] = sorted(book.items(), key=lambda kv: kv[0], reverse=reverse)


def crc32_checksum(book: OrderBook) -> int:
    """欧易校验和：前 25 档 bid/ask 交叉拼接 price:qty，CRC32（有符号 32 位）。"""
    parts: list[str] = []
    for i in range(25):
        if i < len(book.bids):
            parts.append(f"{book.bids[i][0]}:{book.bids[i][1]}")
        if i < len(book.asks):
            parts.append(f"{book.asks[i][0]}:{book.asks[i][1]}")
    raw = ":".join(parts)
    crc = zlib.crc32(raw.encode())
    return crc - (1 << 32) if crc >= (1 << 31) else crc  # 转有符号
