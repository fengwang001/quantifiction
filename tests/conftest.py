"""共享 fixtures（T015）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.core.symbol import Market, Symbol
from quant.core.types import MarketCaps, Settlement


@pytest.fixture
def btc() -> Symbol:
    return Symbol(Market.BINANCE_UMS, "BTCUSDT")


@pytest.fixture
def binance_caps() -> MarketCaps:
    return MarketCaps(
        supports_short=True,
        settlement=Settlement.T0,
        price_limit_pct=None,
        min_lot=1,
        min_notional=Decimal("100"),
        has_l2_depth=True,
        has_liquidation_feed=True,
        trading_calendar="24/7",
    )
