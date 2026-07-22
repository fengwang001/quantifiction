"""T036：影子模式（FR-008）。

shadow 层记录假想成交入账 trade_ledger(tier=shadow)，绝不向交易所下单。
用于零风险收集对比样本，驱动币种升降级（宪法 VI）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant.core.types import OrderRequest, Side

# taker 往返成本模型（VIP0）：单边 0.05%
TAKER_FEE_RATE = Decimal("0.0005")


@dataclass(frozen=True, slots=True)
class ShadowFill:
    symbol_uid: str
    strategy: str
    side: Side
    price: Decimal
    qty: Decimal
    notional: Decimal
    fee: Decimal
    tier: str = "shadow"


def simulate_fill(order: OrderRequest, strategy: str, mark_price: Decimal) -> ShadowFill:
    """以标记价假想成交，计入 taker 费；不触及网关。"""
    notional = mark_price * order.qty
    fee = notional * TAKER_FEE_RATE
    return ShadowFill(
        symbol_uid=order.symbol.uid,
        strategy=strategy,
        side=order.side,
        price=mark_price,
        qty=order.qty,
        notional=notional,
        fee=fee,
    )
