"""T047：熔断器连续亏损 5/8/12 + veto 精确率 + 预算降级。"""
from __future__ import annotations

from decimal import Decimal

from quant.cognitive.breaker import Breaker, CognitiveMode, VetoQuality
from quant.cognitive.budget import BudgetGuard


def test_breaker_escalates():
    b = Breaker()
    for _ in range(5):
        b.record_trade(llm_boosted=True, pnl=-1)
    assert b.mode is CognitiveMode.HALF_BOOST and b.boost_scale == 0.5
    for _ in range(3):
        b.record_trade(llm_boosted=True, pnl=-1)
    assert b.mode is CognitiveMode.VETO_ONLY
    for _ in range(4):
        b.record_trade(llm_boosted=True, pnl=-1)
    assert b.mode is CognitiveMode.OFF


def test_breaker_win_resets():
    b = Breaker()
    for _ in range(6):
        b.record_trade(llm_boosted=True, pnl=-1)
    b.record_trade(llm_boosted=True, pnl=+1)
    assert b.consecutive_losses == 0 and b.mode is CognitiveMode.FULL


def test_breaker_ignores_non_boosted():
    b = Breaker()
    for _ in range(10):
        b.record_trade(llm_boosted=False, pnl=-1)
    assert b.mode is CognitiveMode.FULL  # 纯量化交易不计入 LLM 熔断


def test_veto_precision_demote():
    vq = VetoQuality()
    for _ in range(3):
        vq.record(would_have_lost=True)
    for _ in range(7):
        vq.record(would_have_lost=False)  # veto 挡掉的其实是赚的
    assert vq.precision == 0.3
    assert vq.demote_to_halfsize is True


def test_budget_degrades_when_exhausted():
    g = BudgetGuard()
    assert g.can_call()
    g.charge(Decimal("8.6"))   # 耗尽日预算(¥8.6)
    assert not g.can_call()  # → 降级纯量化
