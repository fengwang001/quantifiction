"""T009：信号总线（Redis Streams）+ 半衰期衰减（contracts/signal-bus.md）。

衰减为纯函数，可脱离 Redis 单测（CT-SB）。生产者停发 → effective 自然衰减到 0
→ 系统优雅降级为纯量化（宪法 II / CT-SB-2）。
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from quant.core.types import Signal

if TYPE_CHECKING:  # 避免非 needs_redis 测试强依赖 redis
    from redis.asyncio import Redis


def effective_value(sig: Signal, now: int | None = None) -> float:
    """有效值 = score · confidence · exp(-Δt·ln2/half_life)（CT-SB-1/2）。"""
    now = now if now is not None else int(time.time())
    dt = max(0, now - sig.emitted_at)
    if sig.half_life_sec <= 0:
        decay = 0.0
    else:
        decay = math.exp(-dt * math.log(2) / sig.half_life_sec)
    return sig.score * sig.confidence * decay


def _stream_key(symbol_uid: str) -> str:
    return f"signals:{symbol_uid}"  # 以 uid 索引（CT-SB-3）


class SignalBus:
    """Redis Streams 封装。仅在 needs_redis 环境使用。"""

    def __init__(self, redis: "Redis", maxlen: int = 10_000) -> None:
        self._r = redis
        self._maxlen = maxlen

    async def publish(self, sig: Signal) -> str:
        if not sig.evidence:
            raise ValueError("Signal.evidence 不可为空（CT-SB-4，事后归因需要）")
        payload = {"data": json.dumps(asdict(sig))}
        return await self._r.xadd(
            _stream_key(sig.symbol_uid), payload, maxlen=self._maxlen, approximate=True
        )

    async def read_latest(self, symbol_uid: str, count: int = 100) -> list[Signal]:
        entries = await self._r.xrevrange(_stream_key(symbol_uid), count=count)
        out: list[Signal] = []
        for _id, fields in entries:
            raw = fields[b"data"] if b"data" in fields else fields["data"]
            out.append(Signal(**json.loads(raw)))
        return out
