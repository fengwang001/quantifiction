"""欧易实时行情：WS 客户端（生产）+ REST 轮询适配（开发/受限网络）。

- WS：订阅 books（订单簿增量）/ trades（逐笔）。消息解析为纯逻辑，可用合成消息单测。
  上香港服务器直连 OKX 用 WS；本机受代理限制连不上 8443，故提供 REST 轮询回退。
- REST 轮询：/market/books + /market/trades，走代理可用，用于开发时看实时信号。
两条路径产出同样的 OrderBook / Trade，喂同一信号层。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from quant.markets.okx_swap.feed import BookEvent, OKXOrderBookMaintainer
from quant.markets.okx_swap.signals import Trade


# --- WS 消息解析（纯逻辑，合成消息可测）---
def parse_books_message(msg: dict[str, Any]) -> tuple[str, BookEvent] | None:
    """解析 books 频道消息 → (instId, BookEvent)。action: snapshot|update。"""
    arg = msg.get("arg", {})
    inst = arg.get("instId", "")
    data = msg.get("data") or []
    if not data:
        return None
    d = data[0]
    action = msg.get("action", "snapshot")
    ev = BookEvent(
        action=action,
        seq_id=int(d.get("seqId", -1)),
        prev_seq_id=int(d.get("prevSeqId", -1)),
        bids=[(Decimal(p), Decimal(q)) for p, q, *_ in d.get("bids", [])],
        asks=[(Decimal(p), Decimal(q)) for p, q, *_ in d.get("asks", [])],
        ts_ms=int(d.get("ts", 0)),
        checksum=int(d["checksum"]) if "checksum" in d else None,
    )
    return inst, ev


def parse_trades_message(msg: dict[str, Any]) -> list[Trade]:
    """解析 trades 频道消息 → [Trade]。"""
    out: list[Trade] = []
    for d in msg.get("data") or []:
        out.append(Trade(price=Decimal(d["px"]), size=Decimal(d["sz"]),
                         side=d["side"], ts_ms=int(d["ts"])))
    return out


# --- REST 轮询适配（开发/受限网络，走代理可用）---
class RestPoller:
    """用 REST 快照模拟实时：每次拉全量订单簿 + 最新逐笔。"""

    def __init__(self, client: Any, inst_id: str, uid: str) -> None:
        self._c = client
        self._inst = inst_id
        self._uid = uid
        self._maintainer = OKXOrderBookMaintainer(uid)

    def poll_book(self, depth: int = 20):
        books = self._c.request("GET", "/api/v5/market/books",
                                {"instId": self._inst, "sz": str(depth)})
        b = books[0]
        ev = BookEvent(
            action="snapshot",
            seq_id=int(b.get("ts", 0)),   # REST 无 seqId，用 ts 占位
            prev_seq_id=-1,
            bids=[(Decimal(p), Decimal(q)) for p, q, *_ in b["bids"]],
            asks=[(Decimal(p), Decimal(q)) for p, q, *_ in b["asks"]],
            ts_ms=int(b["ts"]),
        )
        self._maintainer.apply(ev)
        return self._maintainer.book

    def poll_trades(self, limit: int = 50) -> list[Trade]:
        data = self._c.request("GET", "/api/v5/market/trades",
                               {"instId": self._inst, "limit": str(limit)})
        return [Trade(Decimal(d["px"]), Decimal(d["sz"]), d["side"], int(d["ts"]))
                for d in data]
