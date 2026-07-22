"""T054：llm_decisions 全文落库（FR-009，宪法 V）。

留存完整 prompt/output/bull/bear——现在不存，未来不可补回。行构建为纯逻辑。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    symbol_uid: str
    trigger: str            # scheduled | sentinel | event
    graph_run_id: str
    model_versions: dict[str, str]
    full_prompt: str
    full_output: str
    bull_argument: str
    bear_argument: str
    trader_verdict: dict[str, Any]
    token_cost: float
    latency_ms: int


INSERT_SQL = """
INSERT INTO llm_decisions
 (decision_id, symbol_uid, trigger, graph_run_id, model_versions,
  full_prompt, full_output, bull_argument, bear_argument, trader_verdict,
  token_cost, latency_ms)
VALUES
 (%(decision_id)s, %(symbol_uid)s, %(trigger)s, %(graph_run_id)s, %(model_versions)s,
  %(full_prompt)s, %(full_output)s, %(bull_argument)s, %(bear_argument)s,
  %(trader_verdict)s, %(token_cost)s, %(latency_ms)s)
"""


def to_row(rec: DecisionRecord) -> dict:
    return {
        **{k: getattr(rec, k) for k in rec.__slots__},  # type: ignore[attr-defined]
        "model_versions": json.dumps(rec.model_versions),
        "trader_verdict": json.dumps(rec.trader_verdict),
    }


def write_decision(conn, rec: DecisionRecord) -> None:
    if not rec.full_prompt or not rec.full_output:
        raise ValueError("full_prompt/full_output 不可为空（宪法 V）")
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, to_row(rec))
    conn.commit()
