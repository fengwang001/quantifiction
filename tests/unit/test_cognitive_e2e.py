"""端到端：grsai 客户端 → 节点 → LangGraph → verdict → validator → fusion。

用假 LLM 客户端，验证认知层全链路及宪法 II 约束在真实图上成立。
"""
from __future__ import annotations

import json

import pytest

from quant.cognitive.llm_client import ChatResult
from quant.cognitive.nodes import build_llm_nodes
from quant.cognitive.validator import validate
from quant.strategy.fusion import final_score


class FakeClient:
    """按模型返回预设文本。"""

    def __init__(self, by_model):
        self.by_model = by_model
        self.calls = []

    def complete(self, model, messages, temperature=None):
        self.calls.append(model)
        text = self.by_model.get(model, "0")
        return ChatResult(text, 1, 1, 2, model, "req-1")


MODELS = {"sentinel": "flash", "researcher": "pro", "trader": "pro"}


def test_full_deliberation_produces_valid_signal():
    pytest.importorskip("langgraph")
    from quant.cognitive.graph import build_graph

    verdict = {"stance": 0.5, "conviction": 0.6, "veto": False,
               "half_life_sec": 7200, "reasoning": "承接强",
               "key_risks": ["FOMC 临近", "杠杆拥挤"]}
    client = FakeClient({
        "flash": "3",                       # severity=3 → 触发完整辩论
        "pro": json.dumps(verdict, ensure_ascii=False),
    })
    app = build_graph(build_llm_nodes(client, MODELS))
    out = app.invoke({"symbol_uid": "binance_ums:BTCUSDT"})

    # 图产出 verdict → 过校验 → 融合
    tv = out["trader_verdict"]
    outcome = validate(tv)
    assert outcome.signal is not None
    score = final_score(quant=0.4, llm=outcome.signal)
    assert score > 0.4  # 同向软加成


def test_sentinel_short_circuit_skips_expensive_models():
    pytest.importorskip("langgraph")
    from quant.cognitive.graph import build_graph

    client = FakeClient({"flash": "0"})  # severity=0 → 短路
    app = build_graph(build_llm_nodes(client, MODELS))
    app.invoke({"symbol_uid": "u"})
    assert client.calls == ["flash"]  # 只调便宜模型，省钱（宪法成本约束）


def test_trader_veto_blocks_via_fusion():
    pytest.importorskip("langgraph")
    from quant.cognitive.graph import build_graph

    verdict = {"stance": 0.9, "conviction": 0.7, "veto": True,
               "half_life_sec": 7200, "reasoning": "黑天鹅",
               "key_risks": ["监管", "流动性枯竭"]}
    client = FakeClient({"flash": "3", "pro": json.dumps(verdict, ensure_ascii=False)})
    app = build_graph(build_llm_nodes(client, MODELS))
    out = app.invoke({"symbol_uid": "u"})
    sig = validate(out["trader_verdict"]).signal
    assert final_score(0.8, sig) == 0.0  # veto 硬否决（宪法 II）
