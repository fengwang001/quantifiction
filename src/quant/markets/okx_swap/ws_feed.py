"""欧易实时行情：WS 客户端（生产）+ REST 轮询适配（开发/受限网络）。

- WS：订阅 books（订单簿增量）/ trades（逐笔）。消息解析为纯逻辑，可用合成消息单测。
  上香港服务器直连 OKX 用 WS；本机受代理限制连不上 8443，故提供 REST 轮询回退。
- REST 轮询：/market/books + /market/trades，走代理可用，用于开发时看实时信号。
两条路径产出同样的 OrderBook / Trade，喂同一信号层。
"""
from __future__ import annotations

import asyncio
import json
import socket
import ssl
import threading
import time
from collections import deque
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

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


# --- WS 实时（生产/透明代理 Clash）---
class WSPoller:
    """WS 实时行情，接口同 RestPoller（poll_book/poll_trades），毫秒级更新。

    后台线程跑 asyncio：订阅 books（增量+checksum）/ trades（逐笔），
    在内存维护最新订单簿与滚动逐笔。主循环调 poll_* 只读内存快照，零阻塞。

    受限网络下经 HTTP CONNECT 代理隧道（如 Clash 混合端口，透传 TLS）连
    wss://ws.okx.com:8443。若 WS 尚未就绪/断线，poll_* 自动回退 REST，无冷启动缺口。
    """

    def __init__(self, client: Any, inst_id: str, uid: str,
                 ws_url: str = "wss://ws.okx.com:8443/ws/v5/public",
                 proxy: str | None = None) -> None:
        self._rest = RestPoller(client, inst_id, uid)   # 回退与冷启动
        self._inst = inst_id
        self._url = ws_url
        self._proxy = proxy
        self._maintainer = OKXOrderBookMaintainer(uid)
        self._trades: deque[Trade] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._book_ready = False
        self._last_msg_ts = 0.0
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._run, name="okx-ws", daemon=True)
        self._th.start()

    # 主循环接口（线程安全，只读内存）
    def poll_book(self, depth: int = 20):
        with self._lock:
            fresh = self._book_ready and (time.time() - self._last_msg_ts) < 15
            book = self._maintainer.book if fresh else None
        if book is not None and book.bids and book.asks:
            return book
        return self._rest.poll_book(depth)     # WS 未就绪/陈旧 → REST 回退

    def poll_trades(self, limit: int = 50) -> list[Trade]:
        with self._lock:
            fresh = (time.time() - self._last_msg_ts) < 15
            if fresh and self._trades:
                return list(self._trades)[-limit:]
        return self._rest.poll_trades(limit)

    @property
    def live(self) -> bool:
        return self._book_ready and (time.time() - self._last_msg_ts) < 15

    def stop(self) -> None:
        self._stop.set()

    # 后台线程
    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while not self._stop.is_set():
            try:
                loop.run_until_complete(self._session())
            except Exception:  # noqa: BLE001
                pass
            if not self._stop.is_set():
                time.sleep(3)   # 断线重连退避

    async def _open_sock(self) -> socket.socket:
        """经 HTTP CONNECT 代理（可选）建到 ws 主机的裸 TCP，交给 websockets 做 TLS。"""
        u = urlparse(self._url)
        host, port = u.hostname, u.port or 8443
        if self._proxy:
            p = urlparse(self._proxy)
            s = socket.create_connection((p.hostname, p.port), timeout=12)
            s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\n"
                      f"Host: {host}:{port}\r\n\r\n".encode())
            resp = s.recv(1024).decode(errors="replace")
            if "200" not in resp.split("\r\n")[0]:
                s.close()
                raise ConnectionError(f"代理 CONNECT 失败: {resp[:60]}")
        else:
            s = socket.create_connection((host, port), timeout=12)
        s.setblocking(False)
        return s

    async def _session(self) -> None:
        import websockets
        u = urlparse(self._url)
        sock = await self._open_sock()
        ctx = ssl.create_default_context()
        async with websockets.connect(self._url, sock=sock, ssl=ctx,
                                      server_hostname=u.hostname,
                                      ping_interval=20, ping_timeout=10) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": [
                {"channel": "books", "instId": self._inst},
                {"channel": "trades", "instId": self._inst},
            ]}))
            while not self._stop.is_set():
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                if raw == "pong":
                    continue
                msg = json.loads(raw)
                ch = msg.get("arg", {}).get("channel")
                if ch == "books":
                    parsed = parse_books_message(msg)
                    if parsed:
                        with self._lock:
                            self._maintainer.apply(parsed[1])
                            self._book_ready = True
                            self._last_msg_ts = time.time()
                elif ch == "trades":
                    tr = parse_trades_message(msg)
                    if tr:
                        with self._lock:
                            self._trades.extend(tr)
                            self._last_msg_ts = time.time()
