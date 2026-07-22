"""grsai LLM 客户端：解析/鉴权/错误/成本（注入 transport，无网络）。

响应样例取自 grsai OpenAPI 文档。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quant.cognitive.budget import BudgetGuard
from quant.cognitive.llm_client import (
    GLOBAL_BASE,
    GrsaiClient,
    LLMError,
    ModelPricing,
    cost_rmb,
    cost_usd,
    load_pricing,
    parse_completion,
)


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.last = None

    def post(self, url, headers, json):
        self.last = {"url": url, "headers": headers, "json": json}
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


# 文档非流式响应样例
DOC_RESPONSE = {
    "id": "1-2ede12b5-77cc-48f9-b1d0-7ae35ee8d444",
    "object": "",
    "created": 1777897048,
    "model": "gemini-3.1-pro",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "你好！请问有什么我可以帮您的吗？"},
         "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 2, "completion_tokens": 261, "total_tokens": 263},
    "system_fingerprint": "",
}


def test_parse_doc_response():
    r = parse_completion(DOC_RESPONSE)
    assert r.content.startswith("你好")
    assert r.total_tokens == 263
    assert r.model == "gemini-3.1-pro"


def test_complete_sends_bearer_and_body():
    t = FakeTransport(DOC_RESPONSE)
    c = GrsaiClient("sk-abc", transport=t)
    r = c.complete("gemini-3.1-pro", [{"role": "user", "content": "你好"}])
    assert r.content
    # 鉴权头 + 非流式 + 正确 URL
    assert t.last["headers"]["Authorization"] == "Bearer sk-abc"
    assert t.last["json"]["stream"] is False
    assert t.last["url"] == f"{GLOBAL_BASE}/v1/chat/completions"


def test_domestic_base_url():
    t = FakeTransport(DOC_RESPONSE)
    c = GrsaiClient("sk-x", base_url="https://grsai.dakka.com.cn", transport=t)
    c.complete("m", [{"role": "user", "content": "hi"}])
    assert t.last["url"].startswith("https://grsai.dakka.com.cn")


def test_error_response_raises():
    with pytest.raises(LLMError):
        parse_completion({"error": {"message": "generation failed"}})


def test_empty_choices_raises():
    with pytest.raises(LLMError):
        parse_completion({"choices": []})


def test_pricing_loaded_from_config_not_hardcoded():
    # 价格从 config 读，代码不写死（grsai 调价只改 yaml）
    cfg = {"pricing": {
        "gpt-5.4": {"input_per_m": 1.4, "output_per_m": 12},
        "gemini-3.1-flash-lite": {"input_per_m": 0.5, "output_per_m": 3},
    }}
    table = load_pricing(cfg)
    assert table["gpt-5.4"].output_per_m == Decimal("12")


def test_cost_rmb_input_output_separated():
    # DOC_RESPONSE: prompt=2, completion=261。gpt-5.4 定价 in1.4/out12（¥/M）
    r = parse_completion(DOC_RESPONSE)
    p = ModelPricing(Decimal("1.4"), Decimal("12"))
    expected = (Decimal(2)/Decimal(1_000_000)*Decimal("1.4")
                + Decimal(261)/Decimal(1_000_000)*Decimal("12"))
    assert cost_rmb(r, p) == expected


def test_cost_usd_conversion_and_budget():
    r = parse_completion(DOC_RESPONSE)
    p = ModelPricing(Decimal("1.4"), Decimal("12"))
    usd = cost_usd(r, p, usd_rmb_rate=Decimal("7.2"))
    g = BudgetGuard()  # USD 宪法上限 $1.20/$25
    g.charge(usd)
    assert g.can_call()  # 单次远低于日预算
