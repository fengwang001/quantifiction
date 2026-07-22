"""T022：仓位对账（CT-EG-3）。

交易所 ACCOUNT_UPDATE 推送为唯一真相；本地每 30s 与之比对，不一致立即停机。
比对逻辑为纯函数，可单测。
"""
from __future__ import annotations

from decimal import Decimal

from quant.core.types import Position, ReconcileResult

# 数量比对容差（浮点/精度噪声），超出即视为不一致
QTY_EPSILON = Decimal("0.0000001")


def compare_positions(
    local: dict[str, Decimal],
    exchange: list[Position],
    epsilon: Decimal = QTY_EPSILON,
) -> ReconcileResult:
    """local: uid→有符号数量；exchange: 交易所侧持仓（真相）。"""
    ex_map: dict[str, Decimal] = {}
    for p in exchange:
        signed = p.qty if p.side.value == "BUY" else -p.qty
        ex_map[p.symbol.uid] = signed

    uids = set(local) | set(ex_map)
    diffs: list[str] = []
    for uid in uids:
        lq = local.get(uid, Decimal(0))
        eq = ex_map.get(uid, Decimal(0))
        if abs(lq - eq) > epsilon:
            diffs.append(f"{uid}: local={lq} exchange={eq}")

    if diffs:
        return ReconcileResult(consistent=False, detail="; ".join(diffs))
    return ReconcileResult(consistent=True, detail=f"{len(uids)} symbols matched")
