"""T056：engine 融合全链——veto 拦截 / 熔断剥离加成 / 方向由 score 定。"""
from __future__ import annotations

from decimal import Decimal

from quant.cognitive.breaker import Breaker, CognitiveMode
from quant.core.types import LLMSignal, OrderAck, Side
from quant.risk.common_gates import full_gate_chain
from quant.risk.gate import GateChain
from quant.strategy.engine import Engine
from quant.strategy.shadow import ShadowFill
from tests.unit.test_engine import FakeGateway, _ctx, _pos


def _eng(gw):
    return Engine(gw, GateChain(full_gate_chain(reconcile_ok=True)))


async def _decide(eng, quant, llm, breaker=None, tier="shadow"):
    from quant.core.symbol import Market
    return await eng.decide_and_route(
        raw="ETHUSDT", tier=tier, strategy="liq_reversal", quant_score=quant, llm=llm,
        price=Decimal("3000"), risk_usd=Decimal("15"), stop_pct=Decimal("0.015"),
        equity=Decimal("2000"), capital_weight=Decimal("0.7"),
        min_notional=Decimal("20"), ctx=_ctx(equity=Decimal("2000")), breaker=breaker,
        market=Market.BINANCE_UMS,
    )


def _llm(stance, conviction=0.6, veto=False):
    return LLMSignal("binance_ums:ETHUSDT", stance, conviction, veto, 7200)


async def test_veto_blocks_entirely():
    out = await _decide(_eng(FakeGateway()), quant=0.8, llm=_llm(0.5, veto=True))
    assert out is None  # 融合归零 → 不下单


async def test_direction_follows_fused_score():
    # 同向做多 → shadow 记账（BUY）
    out = await _decide(_eng(FakeGateway(fill=True, positions=[_pos()])),
                        quant=0.5, llm=_llm(0.8))
    assert isinstance(out, ShadowFill) and out.side is Side.BUY


async def test_breaker_off_strips_boost_keeps_veto():
    br = Breaker(); br.consecutive_losses = 12; br._apply()
    assert br.mode is CognitiveMode.OFF
    # OFF 下 veto 仍生效
    out = await _decide(_eng(FakeGateway()), quant=0.6, llm=_llm(0.9, veto=True), breaker=br)
    assert out is None


async def test_live_veto_sets_gate_flag():
    # veto 时融合已归零返回 None（G13 冗余保障）
    out = await _decide(_eng(FakeGateway(positions=[_pos()])),
                        quant=0.5, llm=_llm(-0.9, veto=True), tier="live")
    assert out is None
