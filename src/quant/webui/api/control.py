"""T058：控制指令中转（CT-WEB-3，宪法 IV）。

API 进程不持有交易 Key，只向 Redis `control:cmd` 写指令，
由 strategy 进程消费执行。API 被攻破的最坏后果是停机，而非资金转移。
"""
from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any

CONTROL_STREAM = "control:cmd"


class Command(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    FLAT = "flat"


class ControlWriter:
    """只写 Redis，不接触交易所（注入 redis client）。"""

    def __init__(self, redis: Any) -> None:
        self._r = redis

    async def send(self, cmd: Command, actor: str = "webui") -> str:
        payload = {
            "cmd": cmd.value,
            "actor": actor,
            "ts": str(int(time.time() * 1000)),
        }
        return await self._r.xadd(CONTROL_STREAM, payload)


def parse_command(fields: dict) -> Command:
    raw = fields.get(b"cmd") if b"cmd" in fields else fields.get("cmd")
    if isinstance(raw, bytes):
        raw = raw.decode()
    return Command(raw)
