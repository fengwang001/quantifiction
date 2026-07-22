"""T045：融合契约 CT-LLM-1..5 穷举越界（宪法 II）。"""
from __future__ import annotations

from quant.core.types import LLMSignal
from quant.strategy.fusion import final_score


def _llm(stance, conviction=0.6, veto=False):
    return LLMSignal("binance_ums:BTCUSDT", stance, conviction, veto, 7200)


def test_ct_llm_1_veto_returns_zero():
    # veto 无条件归零，即便量化信号很强
    assert final_score(0.9, _llm(0.8, veto=True)) == 0.0


def test_ct_llm_2_opposite_never_reverses():
    # quant 正、stance 负 → 结果符号仍随 quant（不反转、不发起反向仓）
    r = final_score(0.5, _llm(-0.9))
    assert r > 0 and r == 0.5 * 0.3
    r2 = final_score(-0.5, _llm(0.9))
    assert r2 < 0 and r2 == -0.5 * 0.3


def test_ct_llm_3_boost_capped_at_50pct():
    # 同向最大加成：stance=1, conviction=0.8 → ×(1+0.5·1·0.8)=×1.4 ≤ 1.5
    r = final_score(1.0, _llm(1.0, 0.8))
    assert r == 1.4
    assert abs(r) <= abs(1.0) * 1.5


def test_ct_llm_4_none_degrades_to_quant():
    # LLM 挂掉/预算耗尽 → 纯量化，非报错
    assert final_score(0.42, None) == 0.42


def test_ct_llm_5_output_is_only_score():
    # 融合仅产出 score（不产生订单/仓位）——返回类型为 float
    assert isinstance(final_score(0.3, _llm(0.5)), float)
