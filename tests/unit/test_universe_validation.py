"""T031：universe U1-U5 + cognitive 预算校验（US2-AS1/AS2）。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.strategy.spec_loader import (
    ConfigError,
    load_universe,
    validate_cognitive,
    validate_universe,
)

KNOWN = {"liq_reversal"}
MN = {"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("20"), "SOLUSDT": Decimal("20")}


def _u(text):
    return load_universe(text)


def test_u2_weight_sum_must_be_one():
    u = _u("""
universe:
  ETHUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 0.7, max_notional_usd: 100}
  SOLUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 0.5, max_notional_usd: 100}
constraints: {max_live_symbols: 2, max_concurrent_positions: 2}
""")
    with pytest.raises(ConfigError, match="U2"):
        validate_universe(u, KNOWN, MN)


def test_u3_rejects_btc_at_100_capital():
    """$100 阶段 BTC max_notional=100 < 100×1.1 → 拒绝（US2-AS2）。"""
    u = _u("""
universe:
  BTCUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 1.0, max_notional_usd: 100}
constraints: {max_live_symbols: 2, max_concurrent_positions: 2}
""")
    with pytest.raises(ConfigError, match="U3"):
        validate_universe(u, KNOWN, MN)


def test_u1_live_count_limit():
    u = _u("""
universe:
  ETHUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 0.5, max_notional_usd: 100}
  SOLUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 0.5, max_notional_usd: 100}
  DOGEUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 0.0, max_notional_usd: 100}
constraints: {max_live_symbols: 2, max_concurrent_positions: 2}
""")
    with pytest.raises(ConfigError, match="U1"):
        validate_universe(u, KNOWN, MN)


def test_u4_unknown_strategy():
    u = _u("""
universe:
  ETHUSDT: {tier: live, strategies: [ghost], capital_weight: 1.0, max_notional_usd: 100}
constraints: {max_live_symbols: 2, max_concurrent_positions: 2}
""")
    with pytest.raises(ConfigError, match="U4"):
        validate_universe(u, KNOWN, MN)


def test_valid_eth_live_passes():
    u = _u("""
universe:
  ETHUSDT: {tier: live, strategies: [liq_reversal], capital_weight: 1.0, max_notional_usd: 100}
  BTCUSDT: {tier: shadow, strategies: [liq_reversal]}
constraints: {max_live_symbols: 2, max_concurrent_positions: 2}
""")
    validate_universe(u, KNOWN, MN)  # 不抛
    assert len(u.live) == 1


def test_cognitive_budget_cap():
    # 超 USD 硬上限（日 $1.20）→ 拒绝
    with pytest.raises(ConfigError):
        validate_cognitive({"cognitive": {
            "provider": {"budget_usd": {"daily": 5, "monthly": 25}},
            "deliberation": {"max_per_day": 8}}})
    # 合法
    validate_cognitive({"cognitive": {
        "provider": {"budget_usd": {"daily": 1.20, "monthly": 25}},
        "deliberation": {"max_per_day": 8}}})


def test_cognitive_requires_max_per_day():
    with pytest.raises(ConfigError, match="max_per_day"):
        validate_cognitive({"cognitive": {
            "provider": {"budget_usd": {"daily": 1.0, "monthly": 20}},
            "deliberation": {}}})
