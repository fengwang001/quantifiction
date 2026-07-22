"""T049：认知层熔断器（§6.6）。

连续亏损 → 逐级降权直至关闭；veto 精确率过低 → veto 降级。
状态机纯逻辑，可单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CognitiveMode(str, Enum):
    FULL = "full"              # 正常：veto + 软加成
    HALF_BOOST = "half_boost"  # boost 0.5→0.25
    VETO_ONLY = "veto_only"    # 不再加成，仅否决
    OFF = "off"                # 完全关闭，纯量化


@dataclass(slots=True)
class Breaker:
    consecutive_losses: int = 0
    mode: CognitiveMode = CognitiveMode.FULL
    boost_scale: float = 1.0

    def record_trade(self, llm_boosted: bool, pnl: float) -> None:
        """仅统计 LLM 加成过的交易（§6.6）。"""
        if not llm_boosted:
            return
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self._apply()

    def _apply(self) -> None:
        n = self.consecutive_losses
        if n >= 12:
            self.mode = CognitiveMode.OFF
            self.boost_scale = 0.0
        elif n >= 8:
            self.mode = CognitiveMode.VETO_ONLY
            self.boost_scale = 0.0
        elif n >= 5:
            self.mode = CognitiveMode.HALF_BOOST
            self.boost_scale = 0.5
        else:
            self.mode = CognitiveMode.FULL
            self.boost_scale = 1.0


@dataclass(slots=True)
class VetoQuality:
    """veto 精确率：被 veto 挡掉的交易若事后多为盈利，说明 veto 帮倒忙。"""
    total: int = 0
    would_have_lost: int = 0  # veto 挡掉且事后确为亏损（veto 正确）

    def record(self, would_have_lost: bool) -> None:
        self.total += 1
        if would_have_lost:
            self.would_have_lost += 1

    @property
    def precision(self) -> float:
        return self.would_have_lost / self.total if self.total else 1.0

    @property
    def demote_to_halfsize(self) -> bool:
        # 30日精确率 < 0.4 → veto 权限降为「仓位减半」而非「禁止」
        return self.total >= 10 and self.precision < 0.4
