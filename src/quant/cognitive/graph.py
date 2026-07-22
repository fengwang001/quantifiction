"""T051：LangGraph 认知图（§6.0.1，宪法 II）。

拓扑：sentinel → (changed?) → analysts → bull/bear → trader → risk → END
          └── no change ──────────────────────────────────────→ END（省钱短路）

节点以 dict 注入，便于确定性测试（无需真 LLM）。图出口仅 trader_verdict，
后续必过 validator→breaker→fusion（不在本图内改变权限边界）。
"""
from __future__ import annotations

from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph


class CogState(TypedDict, total=False):
    symbol_uid: str
    changed: bool
    severity: int
    analyses: dict[str, Any]
    bull: str
    bear: str
    trader_verdict: dict[str, Any]
    risk_note: str


NodeFn = Callable[[CogState], CogState]


def _route_after_sentinel(state: CogState) -> str:
    # severity >= 2 或 changed → 完整辩论；否则短路省钱
    if state.get("changed") and state.get("severity", 0) >= 2:
        return "analysts"
    return END


def build_graph(nodes: dict[str, NodeFn], checkpointer: Any | None = None):
    """用注入的节点函数构建并编译图。"""
    g = StateGraph(CogState)
    for name in ("sentinel", "analysts", "researchers", "trader", "risk"):
        g.add_node(name, nodes[name])

    g.add_edge(START, "sentinel")
    g.add_conditional_edges("sentinel", _route_after_sentinel,
                            {"analysts": "analysts", END: END})
    g.add_edge("analysts", "researchers")
    g.add_edge("researchers", "trader")
    g.add_edge("trader", "risk")
    g.add_edge("risk", END)
    return g.compile(checkpointer=checkpointer)
