"""T059：风控参数禁改清单（宪法 III，CT-WEB-2）。

这些参数仅可改服务器配置文件 + 重启；任何 UI/API 写入一律 403 + 留痕。
理由：这些参数的存在意义即约束操作者本人；可秒改则不再是约束。
"""
from __future__ import annotations

FORBIDDEN_FIELDS = frozenset({
    "hard_floor", "soft_floor",
    "risk_usd", "single_trade_risk",
    "leverage", "max_leverage",
    "max_live_symbols", "max_concurrent_positions",
    # 闸门阈值
    "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8",
    "G9", "G10", "G11", "G12", "G13", "G14",
    "gate_threshold",
    # 认知层预算/熔断
    "daily_usd", "monthly_usd", "consecutive_losses", "breaker_threshold",
})


class ForbiddenFieldError(PermissionError):
    """尝试经 UI/API 修改禁改字段。"""


def assert_editable(field: str) -> None:
    """字段可改则通过；禁改则抛（调用方转 403 + 记 system_events）。"""
    if field in FORBIDDEN_FIELDS:
        raise ForbiddenFieldError(
            f"字段 {field!r} 为风控参数，仅可改配置文件 + 重启（宪法 III）"
        )


def filter_editable(payload: dict) -> dict:
    """返回可改字段子集；含任一禁改字段即整体拒绝。"""
    for k in payload:
        assert_editable(k)
    return payload
