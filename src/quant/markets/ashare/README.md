# markets/ashare — A 股接入（本期不实现，仅预留接缝）

宪法 VII：只在三处留接缝，其余按币安具体实现编写。**本目录当前只应有本 README。**

A 股接入时在此实现与 `markets/base.py` 相同的协议：

- `ExecutionGateway`：券商 CTP/QMT/Ptrade 适配
- `MarketDataFeed`：行情（Level-2 需授权）
- `caps.py`：`MarketCaps(supports_short=False, settlement=T1, price_limit_pct=0.10, has_liquidation_feed=False, ...)`

并向风控链 **追加**（不改 G1-G14）：
- `T1SellableGate`（只能卖昨仓）
- `PriceLimitGate`（涨跌停禁止追单）
- `LotSizeGate(100)`（整百股）
- `CancelRatioGate`（撤单率监控）

策略层通过 `caps` 查询能力自动降级（如 `has_liquidation_feed=False` → 爆仓流信号跳过），
无需改动策略代码（禁止 `if market == ...`）。
