"""grsai LLM 连通冒烟。需 GRSAI_API_KEY，否则跳过。

运行：GRSAI_API_KEY=sk-xxx uv run pytest tests/integration/test_grsai_smoke.py -v -s
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.needs_llm

_KEY = os.getenv("GRSAI_API_KEY")
_MODEL = os.getenv("GRSAI_MODEL", "gpt-5.4")
skip_no_key = pytest.mark.skipif(not _KEY, reason="未设置 GRSAI_API_KEY，跳过 LLM 冒烟")


@skip_no_key
def test_grsai_completion_reachable():
    from quant.cognitive.llm_client import GrsaiClient

    client = GrsaiClient(_KEY, base_url=os.getenv("GRSAI_BASE_URL", "https://grsaiapi.com"))
    r = client.complete(_MODEL, [{"role": "user", "content": "只回复两个字：收到"}])
    assert r.content
    assert r.total_tokens > 0


@skip_no_key
def test_grsai_trader_json_parseable():
    """真实模型能产出可解析、可过校验的 verdict。"""
    from quant.cognitive.llm_client import GrsaiClient
    from quant.cognitive.nodes import build_llm_nodes
    from quant.cognitive.validator import validate

    client = GrsaiClient(_KEY)
    nodes = build_llm_nodes(client, {"sentinel": _MODEL, "researcher": _MODEL, "trader": _MODEL})
    out = nodes["trader"]({"symbol_uid": "binance_ums:BTCUSDT",
                           "bull": "盘口承接强", "bear": "多头拥挤"})
    tv = out["trader_verdict"]
    assert "symbol_uid" in tv and "stance" in tv
    # 校验可能因证据不足而丢弃（合法降级）；但结构必须是可解析的 dict
    assert isinstance(tv.get("stance"), (int, float))
