"""T048：量化信号 × LLM 信号融合（宪法 II，contracts/llm-output.md）。

不对称边界（不可协商）：
  - veto=true → 0（硬否决）
  - 方向不一致 → quant×0.3（削弱，永不反转、永不发起反向开仓）
  - 方向一致 → quant×(1 + 0.5·stance·conviction)（±50% 软加成）
  - llm 缺失（挂掉/预算耗尽）→ quant（纯量化降级，非报错）
"""
from __future__ import annotations

from quant.core.types import LLMSignal

LLM_MAX_BOOST = 0.5


def final_score(quant: float, llm: LLMSignal | None) -> float:
    if llm is None:
        return quant                      # CT-LLM-4：纯量化降级
    if llm.veto:
        return 0.0                         # CT-LLM-1：硬否决
    if quant * llm.stance <= 0:            # CT-LLM-2：方向不一致
        return quant * 0.3                 # 削弱，不反转
    # CT-LLM-3：同向软加成，|结果| ≤ |quant|×1.5
    return quant * (1 + LLM_MAX_BOOST * llm.stance * llm.conviction)
