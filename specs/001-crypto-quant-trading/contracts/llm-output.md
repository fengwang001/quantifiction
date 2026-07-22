# Contract: LLM 认知层出口 + 融合（宪法 II）

**Producer**: cognitive/graph.py（LangGraph 出口）→ validator → breaker
**Consumer**: strategy/fusion.py

## LLMSignal Schema（validator 强制）

```json
{
  "symbol_uid": "binance_ums:BTCUSDT",
  "stance": 0.45,           // [-1, 1]
  "conviction": 0.6,        // [0, 0.8]  ← 硬上限
  "veto": false,
  "half_life_sec": 7200,
  "reasoning": "...",       // 须含 >=2 条 evidence
  "key_risks": ["..."]
}
```

## 校验链（cognitive/validator.py，§6.5）
| # | 校验 | 失败处理 |
|---|---|---|
| V1 | JSON schema 合规 | 丢弃（不重试、不猜测）→ 本轮降级纯量化 |
| V2 | 数值 clamp | stance∈[-1,1]，conviction∈[0,0.8] |
| V3 | 跳变检测 | \|Δstance\|>1.2 且 <1h → conviction×0.5 |
| V4 | 证据检查 | reasoning evidence<2 → 视为幻觉，丢弃 |
| V5 | 时效 | 超 half_life → 失效 |

## 融合契约（strategy/fusion.py，纯函数，宪法 II 固化）

```python
def final_score(quant: float, llm: LLMSignal | None) -> float:
    if llm is None: return quant                 # 降级纯量化
    if llm.veto: return 0.0                       # 硬否决
    if quant * llm.stance <= 0:                   # 方向不一致
        return quant * 0.3                        # 削弱，不反转
    return quant * (1 + 0.5 * llm.stance * llm.conviction)  # ±50% 软加成
```

### 契约不变量（不可协商）
- **CT-LLM-1**: `veto=true` ⇒ 返回 0，无条件（对应 G13）。
- **CT-LLM-2**: `quant·stance ≤ 0` ⇒ 结果符号 == quant 符号（**永不反转、永不发起反向开仓**）。
- **CT-LLM-3**: |结果| ≤ |quant|×1.5（LLM 加成上限 ±50%）。
- **CT-LLM-4**: `llm is None`（挂掉/预算耗尽）⇒ 结果 == quant（纯量化降级，非报错）。
- **CT-LLM-5**: LLM 不产生订单/仓位/止损——融合输出仅为 score，后续仍过 sizing + 闸门链。

## 熔断契约（cognitive/breaker.py，§6.6）
| 触发 | 动作 |
|---|---|
| 连续 5 次 LLM 加成交易亏损 | boost 0.5→0.25 |
| 连续 8 次 | 降级 veto-only |
| 连续 12 次 | 完全关闭 + 告警 |
| 30日 veto 精确率 < 0.4 | veto 降为「仓位减半」 |
| 24h schema 失败率 > 20% | 关闭 + 告警 |

- **CT-BRK-1**: veto 精确率依赖每次 veto 的影子 PnL 记录，落 llm_decisions/system_events。

## 契约测试要点（穷举越界）
- veto=true + 强量化信号 → 0。
- stance=+1 但 quant<0 → 结果<0 且 |结果|=|quant|×0.3。
- conviction=0.99 输入 → clamp 到 0.8。
- 非法 JSON → 丢弃且 fusion 收到 None → 结果=quant。
- stance 从 -0.5 跳到 +0.9（<1h）→ conviction 折半。
