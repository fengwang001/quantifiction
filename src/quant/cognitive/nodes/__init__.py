"""LangGraph 节点工厂：用 grsai 客户端 + 分层模型构建认知节点。

节点输出结构化 dict；trader 产 trader_verdict（stance/conviction/veto + reasoning），
交由 graph 出口的 validator→breaker→fusion 约束（宪法 II，本文件不改变权限边界）。
LLM 客户端注入，便于确定性测试。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from quant.cognitive.graph import CogState

TRADER_INSTRUCTION = (
    "你是交易裁决者。仅输出 JSON，字段："
    '{"stance": -1..1, "conviction": 0..0.8, "veto": bool, '
    '"half_life_sec": 数字, "reasoning": "简述", "key_risks": ["至少两条"]}。'
    "stance 为方向偏好，veto=true 表示今日建议不交易。不要输出 JSON 以外内容。"
)


def _extract_json(text: str) -> dict[str, Any]:
    """从 LLM 文本中稳健提取 JSON（容忍前后噪声）。"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def build_llm_nodes(client: Any, models: dict[str, str]) -> dict[str, Callable[[CogState], CogState]]:
    """models: {"sentinel","researcher","trader"} → grsai 模型名。"""

    def sentinel(state: CogState) -> CogState:
        # 轻量巡检：是否重大变化（便宜模型）。此处示意，落地接入数据源摘要。
        msg = [{"role": "user", "content": f"标的 {state.get('symbol_uid')} 是否发生重大变化？只答 severity 0-3 的数字。"}]
        r = client.complete(models["sentinel"], msg)
        sev = _first_int(r.content)
        return {**state, "changed": sev >= 2, "severity": sev}

    def analysts(state: CogState) -> CogState:
        # 并行分析在落地时展开；此处占位聚合
        return {**state, "analyses": {}}

    def researchers(state: CogState) -> CogState:
        bull = client.complete(models["researcher"],
                               [{"role": "user", "content": f"作为多头，论证做多 {state.get('symbol_uid')} 的理由。"}])
        bear = client.complete(models["researcher"],
                               [{"role": "user", "content": f"作为空头，论证做空 {state.get('symbol_uid')} 的理由。"}])
        return {**state, "bull": bull.content, "bear": bear.content}

    def trader(state: CogState) -> CogState:
        prompt = (
            f"{TRADER_INSTRUCTION}\n标的：{state.get('symbol_uid')}\n"
            f"多头观点：{state.get('bull', '')}\n空头观点：{state.get('bear', '')}"
        )
        r = client.complete(models["trader"], [{"role": "user", "content": prompt}])
        verdict = _extract_json(r.content)
        verdict.setdefault("symbol_uid", state.get("symbol_uid"))
        return {**state, "trader_verdict": verdict}

    def risk(state: CogState) -> CogState:
        # 只读复核，可标记不可否决交易（§6 Risk Review）
        return {**state, "risk_note": ""}

    return {"sentinel": sentinel, "analysts": analysts,
            "researchers": researchers, "trader": trader, "risk": risk}


def _first_int(text: str) -> int:
    for ch in text:
        if ch.isdigit():
            return int(ch)
    return 0
