"""T052：LangGraph PostgresSaver（FR-011，宪法 V）。

checkpoint 与温层同库，graph_run_id 关联 llm_decisions，形成可回放审计链。
"""
from __future__ import annotations

from typing import Any


def make_checkpointer(pg_dsn: str) -> Any:
    """构建 PostgresSaver。需 PG 可达；无 PG 的纯逻辑测试不调用此函数。"""
    from langgraph.checkpoint.postgres import PostgresSaver

    cm = PostgresSaver.from_conn_string(pg_dsn)
    saver = cm.__enter__()
    saver.setup()
    return saver
