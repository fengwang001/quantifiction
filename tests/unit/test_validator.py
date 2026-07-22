"""T046：validator V1-V5。"""
from __future__ import annotations

from quant.cognitive.validator import validate


def _raw(**o):
    base = dict(symbol_uid="binance_ums:BTCUSDT", stance=0.5, conviction=0.6,
                veto=False, half_life_sec=7200)
    base.update(o); return base


def test_v1_missing_field_discarded():
    assert validate({"stance": 0.5}).signal is None


def test_v2_clamps_conviction_to_cap():
    out = validate(_raw(conviction=0.99))
    assert out.signal.conviction == 0.8


def test_v2_clamps_stance():
    assert validate(_raw(stance=5.0)).signal.stance == 1.0


def test_v4_evidence_required_when_reasoning_present():
    out = validate(_raw(reasoning="因为...", key_risks=["only-one"]))
    assert out.signal is None  # <2 条证据 → 幻觉丢弃


def test_v4_passes_with_enough_evidence():
    out = validate(_raw(reasoning="因为...", key_risks=["a", "b"]))
    assert out.signal is not None


def test_v3_jump_halves_conviction():
    # stance 从 -0.5 跳到 +0.9（间隔 <1h）→ conviction 折半
    out = validate(_raw(stance=0.9, conviction=0.8), prev_stance=-0.5, prev_age_sec=600)
    assert out.signal.conviction == 0.4
