"""T055：认知层三档调度（§6.1）。

哨兵 15min / 定时辩论(UTC 0/8/16) / 事件强制；含 max_per_day、min_interval 约束。
决策为纯函数，可单测。模型分层在 nodes 内按 tier 指定。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TriggerKind(str, Enum):
    NONE = "none"
    SENTINEL = "sentinel"
    DELIBERATION = "deliberation"
    EVENT = "event"


@dataclass(slots=True)
class ScheduleState:
    minute_of_day_utc: int          # 0-1439
    last_delib_min: int             # 上次辩论时刻（分钟）
    delib_count_today: int
    event_count_today: int
    price_move_1h_pct: float
    liq_spike_usd: float
    fomc_within_h: float | None


DELIB_TIMES = {0, 8 * 60, 16 * 60}
MAX_DELIB_PER_DAY = 8
MIN_DELIB_INTERVAL_MIN = 45
MAX_EVENT_PER_DAY = 3


def decide_trigger(s: ScheduleState) -> TriggerKind:
    # 事件强制（最高优先）
    if s.event_count_today < MAX_EVENT_PER_DAY:
        if abs(s.price_move_1h_pct) >= 5 or s.liq_spike_usd >= 50_000_000 or (
            s.fomc_within_h is not None and s.fomc_within_h <= 4
        ):
            if _delib_allowed(s):
                return TriggerKind.EVENT

    # 定时辩论
    if s.minute_of_day_utc in DELIB_TIMES and _delib_allowed(s):
        return TriggerKind.DELIBERATION

    # 哨兵（每 15min）
    if s.minute_of_day_utc % 15 == 0:
        return TriggerKind.SENTINEL

    return TriggerKind.NONE


def _delib_allowed(s: ScheduleState) -> bool:
    if s.delib_count_today >= MAX_DELIB_PER_DAY:
        return False
    if (s.minute_of_day_utc - s.last_delib_min) < MIN_DELIB_INTERVAL_MIN:
        return False
    return True
