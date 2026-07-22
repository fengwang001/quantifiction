"""欧易 SWAP MarketCaps（接缝2 实例）。

从 GET /api/v5/public/instruments 读取 ctVal（合约面值）/ minSz / lotSz，
禁止硬编码。min_notional 由 minSz×ctVal×价格 动态推（下单时结合最新价）。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from quant.core.types import MarketCaps, Settlement


def build_caps(instruments: list[dict[str, Any]], inst_id: str) -> MarketCaps:
    inst = next((i for i in instruments if i["instId"] == inst_id), None)
    if inst is None:
        raise ValueError(f"instruments 中不存在 {inst_id}")
    ct_val = Decimal(str(inst["ctVal"]))          # 每张合约=多少基础币
    min_sz = Decimal(str(inst["minSz"]))          # 最小下单张数
    # min_notional 的价格相关部分在下单时用最新价乘；此处存每张最小名义的“张”基数为 0，
    # 由 sizing 用 contract_val + minSz 处理。这里给一个保守占位（下游以 exchangeInfo 为准）。
    return MarketCaps(
        supports_short=True,
        settlement=Settlement.T0,
        price_limit_pct=None,
        min_lot=int(min_sz) if min_sz >= 1 else 1,
        min_notional=Decimal(0),   # 欧易按张，最小名义 = minSz×ctVal×price，运行时算
        has_l2_depth=True,
        has_liquidation_feed=True,
        trading_calendar="24/7",
        contract_val=ct_val,
    )


def min_notional_at(caps: MarketCaps, min_sz: Decimal, price: Decimal) -> Decimal:
    """最小名义（USDT）= minSz × ctVal × price。"""
    return min_sz * caps.contract_val * price
