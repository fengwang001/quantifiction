"""T027：Watchdog——独立进程 + 独立只读+平仓 Key（宪法 IV / FR-014）。

监控心跳/对账/权益/时亏，触发即全平停机 + 双通道告警。
决策逻辑（assess）为纯函数，可单测；进程循环与告警发送注入。

⚠️ 部署要求：独立进程运行，使用 BINANCE_WATCHDOG_KEY（仅只读+平仓），
不与 strategy 同进程——策略死了它必须仍活着。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class WatchAction(str, Enum):
    OK = "OK"
    FLAT_AND_HALT = "FLAT_AND_HALT"  # 全平 + 停机（致命）
    PAUSE = "PAUSE"                  # 暂停开新仓（非致命异常）


@dataclass(slots=True)
class WatchState:
    now_ms: int
    last_heartbeat_ms: int
    equity: Decimal
    hard_floor: Decimal
    hourly_pnl_pct: float
    reconcile_ok: bool
    api_errors: int


HEARTBEAT_TIMEOUT_MS = 60_000
HOURLY_LOSS_LIMIT_PCT = -3.0
API_ERROR_LIMIT = 10


def assess(s: WatchState) -> tuple[WatchAction, str]:
    """纯决策：返回动作 + 原因（宪法 IV 的各兜底条件）。"""
    if s.equity < s.hard_floor:
        return WatchAction.FLAT_AND_HALT, f"equity {s.equity} < floor {s.hard_floor}"
    if s.hourly_pnl_pct < HOURLY_LOSS_LIMIT_PCT:
        return WatchAction.FLAT_AND_HALT, f"hourly loss {s.hourly_pnl_pct}%"
    if (s.now_ms - s.last_heartbeat_ms) > HEARTBEAT_TIMEOUT_MS:
        return WatchAction.FLAT_AND_HALT, (
            f"heartbeat stale {s.now_ms - s.last_heartbeat_ms}ms"
        )
    if not s.reconcile_ok:
        return WatchAction.PAUSE, "position mismatch — stop opening"
    if s.api_errors > API_ERROR_LIMIT:
        return WatchAction.PAUSE, f"api errors {s.api_errors}"
    return WatchAction.OK, ""


class Watchdog:
    """把纯决策接上执行：flat 用受限网关，告警用飞书（均注入）。"""

    def __init__(self, gateway: object, alerter: object) -> None:
        self._gw = gateway
        self._alert = alerter

    async def tick(self, s: WatchState) -> WatchAction:
        action, reason = assess(s)
        if action is WatchAction.FLAT_AND_HALT:
            for pos in await self._gw.positions():  # type: ignore[attr-defined]
                await self._gw.market_close(pos)     # type: ignore[attr-defined]
            await self._alert.fatal("Watchdog 全平停机", reason)  # type: ignore[attr-defined]
        elif action is WatchAction.PAUSE:
            await self._alert.warn("Watchdog 暂停开仓", reason)   # type: ignore[attr-defined]
        return action
