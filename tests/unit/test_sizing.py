"""T032：仓位计算 + MinNotional 边界。"""
from __future__ import annotations

from decimal import Decimal

from quant.strategy.sizing import size_order, target_notional


def test_notional_from_risk_and_stop():
    # 风险 $15 / 止损 1.5% → 名义 $1000
    assert target_notional(Decimal("15"), Decimal("0.015")) == Decimal("1000")


def test_size_ok_within_bounds():
    r = size_order(price=Decimal("3000"), risk_usd=Decimal("15"), stop_pct=Decimal("0.015"),
                   equity=Decimal("1000"), capital_weight=Decimal("1.0"),
                   min_notional=Decimal("20"))
    assert r.ok
    assert r.notional == Decimal("1000")
    assert r.qty == Decimal("1000") / Decimal("3000")


def test_capped_by_capital_weight():
    # 名义想要 $1000，但 equity×weight 上限 $300 → 收敛到 300
    r = size_order(price=Decimal("3000"), risk_usd=Decimal("15"), stop_pct=Decimal("0.015"),
                   equity=Decimal("1000"), capital_weight=Decimal("0.3"),
                   min_notional=Decimal("20"))
    assert r.notional == Decimal("300")


def test_rejected_below_min_notional():
    # $100 阶段 BTC：名义被 cap 到很小 < 100×1.1 → 拒绝
    r = size_order(price=Decimal("60000"), risk_usd=Decimal("1.5"), stop_pct=Decimal("0.015"),
                   equity=Decimal("100"), capital_weight=Decimal("0.5"),
                   min_notional=Decimal("100"))
    assert not r.ok and "最小" in r.reason
