# Contract: RiskGate 链（接缝3）— 最终裁决者

**Consumers**: strategy/engine.py（下单前强制调用）
**Implementors**: core/risk/common_gates.py（G1-G14）

## RiskGate (Protocol)

```python
class RiskGate(Protocol):
    name: str
    def check(self, ctx: RiskContext, order: OrderRequest) -> GateResult: ...
    # GateResult: PASS | REJECT(reason) | HALT(reason)
```

`RiskContext` 提供：equity、当前持仓、当日/单小时 PnL、下单计数、rate-limit 余量、最近行情年龄、LLM 信号、universe 配置。

## 闸门链（顺序执行，任一 REJECT/HALT 即止）

| # | Gate | 条件 → 结果 |
|---|---|---|
| G1 | HardFloor | equity < 地板($850/$85) → **HALT**（全平停机） |
| G2 | SoftFloor | equity < 软地板($900/$90) → 风险参数减半（PASS 但改 ctx） |
| G3 | MaxExposure | 总名义 > equity×1.0 → REJECT |
| G4 | PerSymbol | 单标的 > equity×0.7 → REJECT |
| G5 | Correlation | BTC+ETH 同向合计 > equity×1.0 → REJECT |
| G6 | DailyDrawdown | 当日亏损 > 3% → REJECT（至次日 UTC0） |
| G7 | HourlyLoss | 单小时亏损 > 3% → **HALT** |
| G8 | OrderRate | 单小时>10 或 单日>20 → REJECT |
| G9 | MinNotional | 名义 < min_notional×1.1 → REJECT |
| G10 | RateLimit | used-weight > 80% → REJECT（降频） |
| G11 | Reconcile | 本地≠交易所 → REJECT + 触发对账停机 |
| G12 | StaleData | 行情年龄 > 5s → REJECT |
| G13 | LLMVeto | llm.veto==true → REJECT |
| G14 | SymbolCap | 单标的 > equity×capital_weight → REJECT |

## 契约不变量（宪法 III）
- **CT-RG-1**: 闸门链无旁路——engine 提交订单前必须完整执行链，无「紧急直发」通道。
- **CT-RG-2**: 闸门阈值来源于配置文件，运行期不可经 UI/API 修改（webui guards 拦截）。
- **CT-RG-3**: HALT 类结果（G1/G7/G11）必须触发系统 HALTED 态：全平 + 停机 + 双通道告警。
- **CT-RG-4**: 新增市场（A股）通过 append 追加闸门（T1Sellable/PriceLimit/LotSize/CancelRatio），不改动 G1-G14。

## 契约测试要点
- 每个闸门单测边界值（equity=849/850/851 等）。
- 链顺序：G1 HALT 时后续闸门不执行。
- 禁改：尝试运行期改 G1 阈值 → 拒绝。
- STOP 强制：FILLED 后未挂 STOP → 视为违约，测试须捕获。
