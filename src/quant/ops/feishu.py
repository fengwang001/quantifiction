"""T028：飞书出站告警/日报 + 加急消息双通道（FR-016，仅出站）。

- 致命告警走「群机器人 Webhook + 加急消息」双通道（§10.3.4）
- 本地去重聚合：同类告警 1 分钟内合并为一条（防限流丢失关键告警）
- 不做入站控制（飞书交互回调需公网，与安全设计冲突）

HTTP 传输注入，便于单测。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class Transport(Protocol):
    async def post_webhook(self, text: str, urgent: bool) -> None: ...
    async def post_urgent(self, text: str) -> None: ...  # 加急消息直达个人


DEDUP_WINDOW_MS = 60_000


@dataclass
class FeishuAlerter:
    transport: Transport
    dedup_window_ms: int = DEDUP_WINDOW_MS
    _last_sent: dict[str, int] = field(default_factory=dict)

    def _now(self) -> int:
        return int(time.time() * 1000)

    def _suppressed(self, key: str, now: int) -> bool:
        last = self._last_sent.get(key)
        if last is not None and (now - last) < self.dedup_window_ms:
            return True
        self._last_sent[key] = now
        return False

    async def info(self, title: str, detail: str = "") -> None:
        await self.transport.post_webhook(f"ℹ️ {title}\n{detail}", urgent=False)

    async def warn(self, title: str, detail: str = "", now: int | None = None) -> None:
        now = now if now is not None else self._now()
        if self._suppressed(f"warn:{title}", now):
            return
        await self.transport.post_webhook(f"⚠️ {title}\n{detail}", urgent=False)

    async def fatal(self, title: str, detail: str = "", now: int | None = None) -> None:
        """致命告警：双通道。去重仅作用于群消息，加急始终送达。"""
        now = now if now is not None else self._now()
        if not self._suppressed(f"fatal:{title}", now):
            await self.transport.post_webhook(f"🔴 {title}\n{detail}", urgent=True)
        # 加急消息为第二通道，不受群消息去重影响（宪法 IV 致命告警不单通道）
        await self.transport.post_urgent(f"🔴 {title}\n{detail}")

    async def daily_report(self, card: dict[str, Any]) -> None:
        await self.transport.post_webhook(_render_report(card), urgent=False)


def _render_report(card: dict[str, Any]) -> str:
    lines = [f"📊 {card.get('date', '')} 日报 | 权益 {card.get('equity', '')}"]
    for row in card.get("rows", []):
        lines.append(str(row))
    return "\n".join(lines)
