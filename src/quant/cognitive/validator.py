"""T049：LLM 输出校验链 V1-V5（§6.5，contracts/llm-output.md）。

非法输出丢弃（不重试不猜测）→ 本轮降级纯量化。纯逻辑，可穷举越界单测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quant.core.types import LLMSignal

CONVICTION_CAP = 0.8
JUMP_THRESHOLD = 1.2
MIN_EVIDENCE = 2


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    signal: LLMSignal | None   # None = 丢弃，降级纯量化
    reason: str = ""


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def validate(
    raw: dict[str, Any],
    prev_stance: float | None = None,
    prev_age_sec: float = 1e9,
) -> ValidationOutcome:
    # V1：schema 必需字段
    required = {"symbol_uid", "stance", "conviction", "veto", "half_life_sec"}
    if not required.issubset(raw):
        return ValidationOutcome(None, "V1 schema 缺字段")

    # V4：证据检查（reasoning 需 ≥2 条 evidence）
    evidence = raw.get("key_risks") or raw.get("evidence") or []
    reasoning = raw.get("reasoning", "")
    if reasoning and len(evidence) < MIN_EVIDENCE:
        return ValidationOutcome(None, "V4 证据不足，疑似幻觉")

    # V2：数值 clamp
    stance = _clamp(float(raw["stance"]), -1.0, 1.0)
    conviction = _clamp(float(raw["conviction"]), 0.0, CONVICTION_CAP)

    # V3：跳变检测 → conviction 折半
    if prev_stance is not None and prev_age_sec < 3600:
        if abs(stance - prev_stance) > JUMP_THRESHOLD:
            conviction *= 0.5

    sig = LLMSignal(
        symbol_uid=raw["symbol_uid"],
        stance=stance,
        conviction=conviction,
        veto=bool(raw["veto"]),
        half_life_sec=float(raw["half_life_sec"]),
        reasoning=reasoning,
        key_risks=tuple(evidence),
    )
    return ValidationOutcome(sig)
