"""T023：币安 U 本位永续 MarketCaps（接缝2 实例）。

min_notional / min_lot 动态读 exchangeInfo，禁止硬编码（research R2 边界）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from quant.core.types import MarketCaps, Settlement


def build_caps(exchange_info: dict[str, Any], symbol_raw: str) -> MarketCaps:
    """从 GET /fapi/v1/exchangeInfo 的返回构造某标的的能力声明。"""
    sym = next((s for s in exchange_info["symbols"] if s["symbol"] == symbol_raw), None)
    if sym is None:
        raise ValueError(f"exchangeInfo 中不存在标的 {symbol_raw}")
    filters = {f["filterType"]: f for f in sym["filters"]}
    min_notional = Decimal(str(filters["MIN_NOTIONAL"]["notional"]))
    lot = filters.get("LOT_SIZE", {})
    min_lot_step = Decimal(str(lot.get("stepSize", "1")))
    # 永续按张/币计价，min_lot 语义上取步长（此处以整数近似，供 A 股整手对齐用）
    min_lot = 1 if min_lot_step < 1 else int(min_lot_step)
    return MarketCaps(
        supports_short=True,
        settlement=Settlement.T0,
        price_limit_pct=None,
        min_lot=min_lot,
        min_notional=min_notional,
        has_l2_depth=True,
        has_liquidation_feed=True,
        trading_calendar="24/7",
    )
